import json
from pathlib import Path
from statistics import mean, pstdev
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.confidence_abstention_diagnostics import (
    ABSTENTION_RULES,
    evaluate_abstention_development,
    evaluate_frozen_abstention_on_independent_test,
    select_research_candidate_abstention_rule,
)
from prediction.feature_service import FEATURE_NAMES, build_prediction_feature_dataset
from prediction.services import PredictionDataError, _load_prediction_bars


DEFAULT_SYMBOLS = ('AAPL', 'NVDA', 'MSFT')
DEFAULT_LOOKBACKS = (504, 756)


def _optional_mean(values):
    values = [float(value) for value in values if value is not None]
    return float(mean(values)) if values else None


def _optional_std(values):
    values = [float(value) for value in values if value is not None]
    return float(pstdev(values)) if values else None


def _aggregate_development(results):
    aggregates = []
    for rule in ABSTENTION_RULES:
        rows = [
            next(item for item in result['rules'] if item['name'] == rule['name'])
            for result in results
        ]
        pooled = [row['pooled_walk_forward'] for row in rows]
        aggregates.append({
            **rule,
            'context_count': len(rows),
            'average_coverage': _optional_mean(row['coverage'] for row in pooled),
            'minimum_context_coverage': min(row['coverage'] for row in pooled),
            'maximum_context_coverage': max(row['coverage'] for row in pooled),
            'average_balanced_accuracy': _optional_mean(
                row['balanced_accuracy'] for row in pooled
            ),
            'average_macro_f1': _optional_mean(row['macro_f1'] for row in pooled),
            'average_minimum_class_recall': _optional_mean(
                row['minimum_class_recall'] for row in pooled
            ),
            'average_roc_auc': _optional_mean(row['roc_auc'] for row in pooled),
            'average_majority_baseline_accuracy': _optional_mean(
                row['majority_baseline_accuracy'] for row in pooled
            ),
            'average_improvement_over_majority_baseline': _optional_mean(
                row['accuracy_improvement_over_majority_baseline'] for row in pooled
            ),
            'between_context_macro_f1_standard_deviation': _optional_std(
                row['macro_f1'] for row in pooled
            ),
            'average_within_context_fold_macro_f1_standard_deviation': _optional_mean(
                row['fold_stability']['macro_f1_standard_deviation'] for row in rows
            ),
            'empty_fold_count': int(sum(
                row['fold_stability']['empty_fold_count'] for row in rows
            )),
        })
    return aggregates


def _test_delta(row):
    baseline = row['no_abstention']
    candidate = row['frozen_research_candidate']
    if candidate is None:
        return None
    return {
        'coverage_change': float(candidate['coverage'] - baseline['coverage']),
        'accuracy_change': (
            float(candidate['accuracy'] - baseline['accuracy'])
            if candidate['accuracy'] is not None else None
        ),
        'balanced_accuracy_change': (
            float(candidate['balanced_accuracy'] - baseline['balanced_accuracy'])
            if candidate['balanced_accuracy'] is not None else None
        ),
        'macro_f1_change': (
            float(candidate['macro_f1'] - baseline['macro_f1'])
            if candidate['macro_f1'] is not None else None
        ),
        'minimum_class_recall_change': (
            float(candidate['minimum_class_recall'] - baseline['minimum_class_recall'])
            if candidate['minimum_class_recall'] is not None else None
        ),
        'baseline_improvement_change': (
            float(
                candidate['accuracy_improvement_over_majority_baseline']
                - baseline['accuracy_improvement_over_majority_baseline']
            )
            if candidate['accuracy_improvement_over_majority_baseline'] is not None
            else None
        ),
    }


class Command(BaseCommand):
    help = (
        'Run research-only confidence-based abstention diagnostics on one-day '
        'classification. Candidate selection is Development-only.'
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
                'abstention_rules': ABSTENTION_RULES,
                'feature_names': FEATURE_NAMES,
                'feature_set_changed': False,
                'classification_target_changed': False,
                'candidate_models_changed': False,
                'model_quality_gates_changed': False,
                'regression_pipeline_touched': False,
                'production_api_or_frontend_touched': False,
            },
            'production_probability_audit': {
                'flow': (
                    'point-in-time features -> selected classifier -> raw class-1 '
                    'predict_proba -> Walk-Forward-selected threshold -> UP/DOWN -> '
                    'deterministic Confidence mapping'
                ),
                'probability_increase_source': 'selected classifier raw predict_proba for class 1',
                'selected_threshold_source': 'purged Development Walk-Forward validation only',
                'production_direction_rule': 'UP when probability > selected threshold; DOWN otherwise',
                'probability_calibration': 'none',
                'candidate_probability_comparability': (
                    'Not guaranteed: Logistic Regression and Random Forest scores are uncalibrated.'
                ),
                'production_confidence_rule': (
                    '55% probability strength abs(p-0.5)*2 plus 45% independent-Test '
                    'quality (mean accuracy, positive F1, and ROC-AUC/accuracy fallback); '
                    'mapped deterministically to High/Medium/Low.'
                ),
                'model_level_gate_distinct_from_instance_abstention': True,
            },
            'development_results': [],
            'development_aggregates': [],
            'probability_quality_aggregates': {},
            'candidate_selection': None,
            'independent_test_results': [],
            'isolation_audit': {},
        }
        datasets = {}
        raw_results = []

        # Phase 1: every rule is compared only on pre-Test purged Walk-Forward
        # predictions. No Test feature, label, probability, coverage, or metric
        # is opened before the single candidate is frozen.
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
                started = monotonic()
                evaluation = evaluate_abstention_development(dataset)
                row = {
                    'symbol': symbol,
                    'lookback': lookback,
                    'market_date_range': {
                        'first': current_bars[0].date.isoformat(),
                        'last': current_bars[-1].date.isoformat(),
                        'source': market_metadata['source'],
                    },
                    'duration_seconds': float(monotonic() - started),
                    **evaluation,
                }
                raw_results.append(row)
                report['development_results'].append(row)
                baseline = next(rule for rule in row['rules'] if rule['name'] == 'none')
                self.stderr.write(
                    f'development {symbol} lookback={lookback} '
                    f'model={row["selected_model"]} threshold={row["selected_threshold"]:.4f} '
                    f'ba={baseline["pooled_walk_forward"]["balanced_accuracy"]:.4f} '
                    f'macro_f1={baseline["pooled_walk_forward"]["macro_f1"]:.4f}'
                )

        report['development_aggregates'] = _aggregate_development(raw_results)
        probability_rows = [row['probability_quality'] for row in raw_results]
        report['probability_quality_aggregates'] = {
            'context_count': len(probability_rows),
            'calibration_method': 'none',
            'average_brier_score': _optional_mean(row['brier_score'] for row in probability_rows),
            'average_log_loss': _optional_mean(row['log_loss'] for row in probability_rows),
            'average_roc_auc': _optional_mean(row['roc_auc'] for row in probability_rows),
            'average_expected_calibration_error': _optional_mean(
                row['expected_calibration_error'] for row in probability_rows
            ),
            'brier_score_standard_deviation': _optional_std(
                row['brier_score'] for row in probability_rows
            ),
            'expected_calibration_error_standard_deviation': _optional_std(
                row['expected_calibration_error'] for row in probability_rows
            ),
        }
        selection_inputs = [
            {
                'symbol': row['symbol'],
                'lookback': row['lookback'],
                'rules': row['rules'],
                'independent_test_accessed': False,
            }
            for row in raw_results
        ]
        selection = select_research_candidate_abstention_rule(selection_inputs)
        report['candidate_selection'] = selection
        selected_rule = selection['research_candidate_abstention_rule']
        self.stderr.write(
            'development-only research candidate: '
            + (selected_rule['name'] if selected_rule else 'none')
        )

        # Phase 2: after freezing at most one rule, fit the frozen selected model
        # once per context and call Test predict_proba once. The same Test score
        # array supplies the no-abstention comparison and the sole candidate.
        for context, dataset in datasets.items():
            symbol, lookback = context
            development = next(
                row for row in raw_results
                if row['symbol'] == symbol and row['lookback'] == lookback
            )
            test_result = evaluate_frozen_abstention_on_independent_test(
                dataset, development, selected_rule,
            )
            test_row = {
                'symbol': symbol,
                'lookback': lookback,
                **test_result,
            }
            test_row['candidate_delta_vs_no_abstention'] = _test_delta(test_row)
            report['independent_test_results'].append(test_row)

        report['isolation_audit'] = {
            'candidate_selected_before_any_test_evaluation': True,
            'candidate_selection_source': 'development_purged_walk_forward_only',
            'independent_test_used_for_candidate_selection': False,
            'non_candidate_rules_tested': False,
            'research_candidate_count': 1 if selected_rule else 0,
            'test_probability_passes_per_context': 1,
            'candidate_test_evaluations_per_context': 1 if selected_rule else 0,
            'test_used_for_model_selection': False,
            'test_used_for_hyperparameter_tuning': False,
            'test_used_for_threshold_selection': False,
            'calibration_fit_on_test': False,
            'calibration_experiment_run': False,
        }

        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
        if options['output']:
            path = Path(options['output']).resolve()
            path.write_text(serialized, encoding='utf-8')
            self.stderr.write(f'wrote report to {path}')
        if options['format'] == 'json':
            self.stdout.write(serialized)
            return
        for aggregate in report['development_aggregates']:
            self.stdout.write(' | '.join((
                aggregate['label'],
                f'coverage={aggregate["average_coverage"]:.4f}',
                f'ba={aggregate["average_balanced_accuracy"]:.4f}',
                f'macro_f1={aggregate["average_macro_f1"]:.4f}',
                f'min_recall={aggregate["average_minimum_class_recall"]:.4f}',
                'baseline_imp='
                f'{aggregate["average_improvement_over_majority_baseline"]:.4f}',
            )))
        self.stdout.write(
            'research_candidate_abstention_rule='
            + (selected_rule['name'] if selected_rule else 'None')
        )
