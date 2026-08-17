import json
from pathlib import Path
from statistics import mean, pstdev
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.feature_service import FEATURE_NAMES, build_prediction_feature_dataset
from prediction.services import PredictionDataError, _load_prediction_bars
from prediction.target_noise_diagnostics import (
    TARGET_NOISE_BANDS,
    evaluate_frozen_noise_band_on_independent_test,
    evaluate_noise_band_development,
    future_return_distribution,
    select_research_candidate_noise_band,
)


DEFAULT_SYMBOLS = ('AAPL', 'NVDA', 'MSFT')
DEFAULT_LOOKBACKS = (504, 756)


def _coverage_summary(coverage):
    return {
        key: coverage[key]
        for key in (
            'original_sample_count',
            'retained_sample_count',
            'excluded_sample_count',
            'coverage_ratio',
            'up_count',
            'down_count',
            'up_ratio',
            'down_ratio',
        )
    }


def _development_summary(symbol, lookback, evaluation, duration):
    metrics = evaluation['metrics']
    quality_gate = evaluation['quality_gate']
    return {
        'symbol': symbol,
        'lookback': lookback,
        'noise_band': evaluation['noise_band'],
        'coverage': _coverage_summary(evaluation['coverage']),
        'selected_model': evaluation['selected_model'],
        'selected_params': evaluation['selected_params'],
        'selected_threshold': evaluation['selected_threshold'],
        'walk_forward': {
            'accuracy': metrics['accuracy'],
            'balanced_accuracy': metrics['mean_balanced_accuracy'],
            'macro_f1': metrics['mean_macro_f1'],
            'roc_auc': metrics['mean_roc_auc'],
            'minimum_class_recall': metrics['mean_minimum_class_recall'],
            'worst_fold_minimum_class_recall': (
                metrics['worst_fold_minimum_class_recall']
            ),
            'majority_baseline_accuracy': (
                quality_gate['observed']['baseline_accuracy']
            ),
            'accuracy_improvement_over_majority_baseline': (
                quality_gate['observed']['accuracy_improvement_over_baseline']
            ),
            'quality_gate_passed': quality_gate['passed'],
            'quality_gate_reason_codes': quality_gate['reason_codes'],
        },
        'folds': evaluation['folds'],
        'fold_pass_count': evaluation['fold_pass_count'],
        'fold_count': evaluation['fold_count'],
        'fold_pass_ratio': evaluation['fold_pass_ratio'],
        'fold_stability': evaluation['fold_stability'],
        'purge_gap': evaluation['purge_gap'],
        'walk_forward_chronological': evaluation['walk_forward_chronological'],
        'all_fold_purges_safe': evaluation['all_fold_purges_safe'],
        'independent_test_accessed': evaluation['independent_test_accessed'],
        'independent_test_used_for_selection': (
            evaluation['independent_test_used_for_selection']
        ),
        'duration_seconds': duration,
    }


def _test_summary(symbol, lookback, evaluation, role):
    metrics = evaluation['metrics']
    return {
        'symbol': symbol,
        'lookback': lookback,
        'noise_band': evaluation['noise_band'],
        'role': role,
        'coverage': _coverage_summary(evaluation['coverage']),
        'frozen_model': evaluation['frozen_model'],
        'frozen_params': evaluation['frozen_params'],
        'frozen_threshold': evaluation['frozen_threshold'],
        'independent_test': {
            'accuracy': metrics['accuracy'],
            'balanced_accuracy': metrics['balanced_accuracy'],
            'macro_f1': metrics['macro_f1'],
            'roc_auc': metrics['roc_auc'],
            'minimum_class_recall': metrics['minimum_class_recall'],
            'majority_baseline_accuracy': metrics['majority_baseline_accuracy'],
            'accuracy_improvement_over_majority_baseline': (
                metrics['accuracy_improvement_over_baseline']
            ),
            'quality_gate_passed': evaluation['quality_gate']['passed'],
            'quality_gate_reason_codes': evaluation['quality_gate']['reason_codes'],
        },
        'isolation': {
            key: evaluation[key]
            for key in (
                'test_used_for_model_selection',
                'test_used_for_hyperparameter_tuning',
                'test_used_for_threshold_selection',
                'model_refit_after_test',
                'test_evaluation_count_for_this_frozen_context',
                'validation_test_purge_safe',
            )
        },
    }


def _aggregate_development(results):
    aggregates = []
    for band in TARGET_NOISE_BANDS:
        rows = [row for row in results if row['noise_band'] == band]
        metrics = [row['walk_forward'] for row in rows]
        macro_values = [row['macro_f1'] for row in metrics]
        aggregates.append({
            'noise_band': band,
            'context_count': len(rows),
            'average_coverage': mean(row['coverage']['coverage_ratio'] for row in rows),
            'average_up_ratio': mean(row['coverage']['up_ratio'] for row in rows),
            'average_down_ratio': mean(row['coverage']['down_ratio'] for row in rows),
            'average_balanced_accuracy': mean(row['balanced_accuracy'] for row in metrics),
            'average_macro_f1': mean(macro_values),
            'average_roc_auc': mean(row['roc_auc'] for row in metrics),
            'average_minimum_class_recall': mean(
                row['minimum_class_recall'] for row in metrics
            ),
            'average_majority_baseline_accuracy': mean(
                row['majority_baseline_accuracy'] for row in metrics
            ),
            'average_improvement_over_majority_baseline': mean(
                row['accuracy_improvement_over_majority_baseline'] for row in metrics
            ),
            'average_fold_pass_ratio': mean(row['fold_pass_ratio'] for row in rows),
            'between_context_macro_f1_standard_deviation': pstdev(macro_values),
            'average_within_context_macro_f1_standard_deviation': mean(
                row['fold_stability']['macro_f1_standard_deviation'] for row in rows
            ),
            'quality_gate_pass_count': sum(
                row['quality_gate_passed'] for row in metrics
            ),
        })
    return aggregates


class Command(BaseCommand):
    help = (
        'Compare research-only one-day classification noise bands on Development '
        'Walk-Forward first, then evaluate at most one frozen candidate on Test.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+', default=list(DEFAULT_SYMBOLS))
        parser.add_argument('--lookbacks', nargs='+', type=int, default=list(DEFAULT_LOOKBACKS))
        parser.add_argument('--output')
        parser.add_argument('--format', choices=('json', 'table'), default='table')

    def handle(self, *args, **options):
        symbols = tuple(dict.fromkeys(symbol.upper() for symbol in options['symbols']))
        lookbacks = tuple(sorted(set(options['lookbacks'])))
        report = {
            'configuration': {
                'symbols': symbols,
                'lookbacks': lookbacks,
                'classification_forecast_horizon': 1,
                'purge_gap': 1,
                'noise_bands': TARGET_NOISE_BANDS,
                'feature_names': FEATURE_NAMES,
                'feature_set_changed': False,
                'candidate_models_changed': False,
                'quality_gate_changed': False,
                'production_target_changed': False,
                'regression_pipeline_touched': False,
            },
            'production_target': {
                'future_return': 'close[t + 1] / close[t] - 1',
                'label': '1 (UP) when future_return > 0, otherwise 0 (DOWN)',
                'source': 'prediction/feature_service.py',
            },
            'return_distributions': [],
            'development_results': [],
            'development_aggregates': [],
            'candidate_selection': None,
            'independent_test_results': [],
        }
        datasets = {}
        raw_development_results = []

        # Phase 1: use only pre-Test development rows and purged validation folds.
        for symbol in symbols:
            security = (
                Security.objects.filter(symbol=symbol, is_active=True)
                .order_by('-country', 'mic_code', 'exchange', 'id')
                .first()
            )
            if security is None:
                raise PredictionDataError(f'No active local Security exists for {symbol}.')
            bars, market_metadata = _load_prediction_bars(security, max(lookbacks))
            for lookback in lookbacks:
                current_bars = tuple(bars[-lookback:])
                dataset = build_prediction_feature_dataset(current_bars, horizon=1)
                datasets[(symbol, lookback)] = dataset
                report['return_distributions'].append({
                    'symbol': symbol,
                    'lookback': lookback,
                    'market_date_range': {
                        'first': current_bars[0].date.isoformat(),
                        'last': current_bars[-1].date.isoformat(),
                        'source': market_metadata['source'],
                    },
                    **future_return_distribution(dataset, development_only=True),
                })
                for band in TARGET_NOISE_BANDS:
                    started = monotonic()
                    evaluation = evaluate_noise_band_development(dataset, band)
                    raw = {
                        'symbol': symbol,
                        'lookback': lookback,
                        **evaluation,
                    }
                    raw_development_results.append(raw)
                    summary = _development_summary(
                        symbol, lookback, evaluation, monotonic() - started,
                    )
                    report['development_results'].append(summary)
                    self.stderr.write(
                        f'development {symbol} lookback={lookback} band={band:.4f} '
                        f'coverage={summary["coverage"]["coverage_ratio"]:.3f} '
                        f'ba={summary["walk_forward"]["balanced_accuracy"]:.4f} '
                        f'macro_f1={summary["walk_forward"]["macro_f1"]:.4f}'
                    )

        report['development_aggregates'] = _aggregate_development(
            report['development_results'],
        )
        selection_inputs = [
            {
                'symbol': result['symbol'],
                'lookback': result['lookback'],
                'noise_band': result['noise_band'],
                'coverage': result['coverage'],
                'metrics': result['metrics'],
                'quality_gate': result['quality_gate'],
                'fold_stability': result['fold_stability'],
            }
            for result in raw_development_results
        ]
        selection = select_research_candidate_noise_band(selection_inputs)
        report['candidate_selection'] = selection
        selected_band = selection['research_candidate_noise_band']
        self.stderr.write(
            'development-only research candidate: '
            + (f'{selected_band:.4f}' if selected_band is not None else 'none')
        )

        # Phase 2 starts only after the candidate choice is frozen. Production
        # baseline Test is evaluated once for comparison; only the one selected
        # research band (if any) is allowed one Test pass per context.
        for context, dataset in datasets.items():
            symbol, lookback = context
            baseline_development = next(
                result for result in raw_development_results
                if result['symbol'] == symbol
                and result['lookback'] == lookback
                and result['noise_band'] == 0.0
            )
            baseline_test = evaluate_frozen_noise_band_on_independent_test(
                dataset, baseline_development,
            )
            report['independent_test_results'].append(
                _test_summary(symbol, lookback, baseline_test, 'production_baseline')
            )
            if selected_band is not None:
                candidate_development = next(
                    result for result in raw_development_results
                    if result['symbol'] == symbol
                    and result['lookback'] == lookback
                    and result['noise_band'] == selected_band
                )
                candidate_test = evaluate_frozen_noise_band_on_independent_test(
                    dataset, candidate_development,
                )
                report['independent_test_results'].append(
                    _test_summary(
                        symbol, lookback, candidate_test, 'frozen_research_candidate',
                    )
                )

        report['isolation_audit'] = {
            'candidate_selected_before_any_test_evaluation': True,
            'candidate_selection_source': 'development_purged_walk_forward_only',
            'independent_test_used_for_noise_band_selection': False,
            'non_candidate_research_bands_tested': False,
            'research_candidate_count': 1 if selected_band is not None else 0,
            'production_baseline_test_evaluations': len(datasets),
            'research_candidate_test_evaluations': (
                len(datasets) if selected_band is not None else 0
            ),
            'test_passes_per_frozen_context': 1,
        }

        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
        if options['output']:
            path = Path(options['output']).resolve()
            path.write_text(serialized, encoding='utf-8')
            self.stderr.write(f'wrote report to {path}')
        if options['format'] == 'json':
            self.stdout.write(serialized)
            return
        for row in report['development_results']:
            metrics = row['walk_forward']
            coverage = row['coverage']
            self.stdout.write(' | '.join((
                row['symbol'],
                f'lookback={row["lookback"]}',
                f'band={row["noise_band"]:.4f}',
                f'coverage={coverage["coverage_ratio"]:.4f}',
                f'up={coverage["up_ratio"]:.4f}',
                f'down={coverage["down_ratio"]:.4f}',
                f'wf_ba={metrics["balanced_accuracy"]:.4f}',
                f'wf_macro_f1={metrics["macro_f1"]:.4f}',
                f'wf_auc={metrics["roc_auc"]:.4f}',
                f'wf_min_recall={metrics["minimum_class_recall"]:.4f}',
                f'baseline_imp={metrics["accuracy_improvement_over_majority_baseline"]:.4f}',
                f'fold_pass={row["fold_pass_count"]}/{row["fold_count"]}',
            )))
        self.stdout.write(
            'research_candidate_noise_band='
            + (str(selected_band) if selected_band is not None else 'None')
        )
