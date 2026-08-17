import json
from pathlib import Path
from statistics import mean, pstdev
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.feature_diagnostics import (
    CLASSIFICATION_FEATURE_SETS,
    FEATURE_EXPERIMENT_LABELS,
    REGRESSION_FEATURE_SETS,
    build_experiment_dataset,
    evaluate_classification_dataset,
    experiment_feature_names,
    feature_quality_report,
    regime_sensitivity_report,
    regression_experiment_result,
    target_alignment_example,
    target_distribution,
)
from prediction.feature_service import build_prediction_feature_dataset
from prediction.services import PredictionDataError, _load_prediction_bars


DEFAULT_SYMBOLS = ('NVDA', 'AAPL', 'MSFT')
DEFAULT_LOOKBACKS = (504, 756)


def _relative_improvement(baseline, model):
    baseline = float(baseline or 0.0)
    model = float(model or 0.0)
    return (baseline - model) / baseline if baseline > 0 else 0.0


def _classification_summary(result):
    walk_forward = result['walk_forward_metrics']
    test = result['independent_test_metrics']
    walk_forward_gate = result['walk_forward_quality_gate']
    return {
        'selected_model': result['selected_model'],
        'selected_params': result['selected_params'],
        'selected_threshold': result['selected_threshold'],
        'sample_count': int(
            walk_forward['actual_up_count'] + walk_forward['actual_down_count']
        ),
        'walk_forward': {
            'balanced_accuracy': walk_forward['mean_balanced_accuracy'],
            'macro_f1': walk_forward['mean_macro_f1'],
            'roc_auc': walk_forward['mean_roc_auc'],
            'minimum_class_recall': walk_forward['mean_minimum_class_recall'],
            'worst_fold_minimum_class_recall': (
                walk_forward['worst_fold_minimum_class_recall']
            ),
            'std_macro_f1': walk_forward['std_macro_f1'],
            'accuracy': walk_forward['accuracy'],
            'majority_baseline_accuracy': (
                walk_forward_gate['observed']['baseline_accuracy']
            ),
            'accuracy_improvement_over_baseline': (
                walk_forward_gate['observed']['accuracy_improvement_over_baseline']
            ),
            'gate_passed': walk_forward_gate['passed'],
            'reason_codes': walk_forward_gate['reason_codes'],
        },
        'independent_test': {
            'balanced_accuracy': test['balanced_accuracy'],
            'macro_f1': test['macro_f1'],
            'roc_auc': test['roc_auc'],
            'minimum_class_recall': test['minimum_class_recall'],
            'accuracy': test['accuracy'],
            'majority_baseline_accuracy': test['majority_class_baseline_accuracy'],
            'accuracy_improvement_over_baseline': (
                test['accuracy_improvement_over_baseline']
            ),
            'gate_passed': result['independent_test_quality_gate']['passed'],
            'reason_codes': result['independent_test_quality_gate']['reason_codes'],
        },
        'final_gate_passed': result['final_quality_gate']['passed'],
        'folds': result['walk_forward_metrics'].get('fold_metrics', []),
        'purge_safe': all(fold['purge_safe'] for fold in result['folds']),
        'test_used_for_selection': result['test_used_for_selection'],
    }


def _regression_summary(result):
    if result.get('status') == 'insufficient_data':
        return {
            'status': 'insufficient_data',
            'unavailable_reason': result.get('unavailable_reason'),
            'selected_model': None,
            'selected_params': None,
            'walk_forward': {},
            'independent_test': {},
            'final_gate_passed': False,
            'folds': [],
            'purge_safe': all(fold['purge_safe'] for fold in result['folds']),
            'test_used_for_selection': False,
        }
    walk_forward = result['walk_forward_metrics']
    walk_model = walk_forward.get('model_metrics') or {}
    walk_baseline = walk_forward.get('zero_return_baseline') or {}
    test = result['independent_test_metrics']
    test_baseline = test.get('zero_return_baseline') or {}
    return {
        'selected_model': result['selected_model'],
        'selected_params': result['selected_params'],
        'walk_forward': {
            'mae': walk_model.get('mae'),
            'rmse': walk_model.get('rmse'),
            'r2': walk_model.get('r2'),
            'zero_return_baseline_mae': walk_baseline.get('mae'),
            'zero_return_baseline_rmse': walk_baseline.get('rmse'),
            'mae_improvement': _relative_improvement(
                walk_baseline.get('mae'), walk_model.get('mae'),
            ),
            'rmse_improvement': _relative_improvement(
                walk_baseline.get('rmse'), walk_model.get('rmse'),
            ),
            'improving_fold_count': walk_forward.get('improving_fold_count'),
            'improving_fold_ratio': walk_forward.get('improving_fold_ratio'),
            'gate_passed': result['walk_forward_quality_gate'].get('passed'),
            'reason_codes': result['walk_forward_quality_gate'].get('reason_codes', []),
        },
        'independent_test': {
            'mae': test.get('mae'),
            'rmse': test.get('rmse'),
            'r2': test.get('r2'),
            'zero_return_baseline_mae': test_baseline.get('mae'),
            'zero_return_baseline_rmse': test_baseline.get('rmse'),
            'mae_improvement': _relative_improvement(
                test_baseline.get('mae'), test.get('mae'),
            ),
            'rmse_improvement': _relative_improvement(
                test_baseline.get('rmse'), test.get('rmse'),
            ),
            'gate_passed': result['independent_test_quality_gate'].get('passed'),
            'reason_codes': result['independent_test_quality_gate'].get(
                'reason_codes', []
            ),
        },
        'final_gate_passed': (result.get('final_quality_gate') or {}).get('passed'),
        'folds': walk_forward.get('folds', []),
        'purge_safe': all(fold['purge_safe'] for fold in result['folds']),
        'test_used_for_selection': result['test_used_for_selection'],
    }


def _aggregate_experiment_results(results, task):
    aggregated = []
    for experiment in FEATURE_EXPERIMENT_LABELS:
        rows = [row[task] for row in results if row.get('status') == 'complete']
        rows = [row for row in rows if row['experiment'] == experiment]
        if not rows:
            continue
        if task == 'classification':
            wf_macro = [row['walk_forward']['macro_f1'] for row in rows]
            wf_balanced = [row['walk_forward']['balanced_accuracy'] for row in rows]
            wf_auc = [
                row['walk_forward']['roc_auc']
                for row in rows
                if row['walk_forward']['roc_auc'] is not None
            ]
            wf_minimum_recall = [
                row['walk_forward']['minimum_class_recall'] for row in rows
            ]
            score = (
                0.40 * mean(wf_macro)
                + 0.30 * mean(wf_balanced)
                + 0.20 * (mean(wf_auc) if wf_auc else 0.5)
                + 0.10 * mean(wf_minimum_recall)
                - 0.10 * pstdev(wf_macro)
            )
            aggregated.append({
                'experiment': experiment,
                'label': FEATURE_EXPERIMENT_LABELS[experiment],
                'walk_forward_only_selection_score': score,
                'mean_walk_forward_macro_f1': mean(wf_macro),
                'mean_walk_forward_balanced_accuracy': mean(wf_balanced),
                'mean_walk_forward_roc_auc': mean(wf_auc) if wf_auc else None,
                'mean_walk_forward_minimum_class_recall': mean(wf_minimum_recall),
                'walk_forward_gate_pass_count': sum(
                    row['walk_forward']['gate_passed'] for row in rows
                ),
                'independent_test_gate_pass_count_report_only': sum(
                    row['independent_test']['gate_passed'] for row in rows
                ),
                'run_count': len(rows),
            })
        else:
            wf_mae = [row['walk_forward']['mae_improvement'] for row in rows]
            wf_rmse = [row['walk_forward']['rmse_improvement'] for row in rows]
            improving = [row['walk_forward']['improving_fold_ratio'] for row in rows]
            score = (
                0.55 * mean(wf_mae)
                + 0.30 * mean(wf_rmse)
                + 0.15 * mean(improving)
                - 0.10 * pstdev(wf_mae)
            )
            aggregated.append({
                'experiment': experiment,
                'label': FEATURE_EXPERIMENT_LABELS[experiment],
                'walk_forward_only_selection_score': score,
                'mean_walk_forward_mae_improvement': mean(wf_mae),
                'mean_walk_forward_rmse_improvement': mean(wf_rmse),
                'mean_walk_forward_improving_fold_ratio': mean(improving),
                'walk_forward_gate_pass_count': sum(
                    row['walk_forward']['gate_passed'] for row in rows
                ),
                'independent_test_gate_pass_count_report_only': sum(
                    row['independent_test']['gate_passed'] for row in rows
                ),
                'run_count': len(rows),
            })
    return sorted(
        aggregated,
        key=lambda row: row['walk_forward_only_selection_score'],
        reverse=True,
    )


class Command(BaseCommand):
    help = (
        'Run fixed A-E point-in-time feature ablations, target-noise diagnostics, '
        'feature-quality checks, and regime-drift checks without changing production.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+', default=list(DEFAULT_SYMBOLS))
        parser.add_argument('--lookbacks', nargs='+', type=int, default=list(DEFAULT_LOOKBACKS))
        parser.add_argument('--classification-horizon', type=int, default=1)
        parser.add_argument('--regression-horizon', type=int, default=10)
        parser.add_argument('--output')
        parser.add_argument('--format', choices=('json', 'table'), default='table')

    def handle(self, *args, **options):
        symbols = tuple(dict.fromkeys(value.strip().upper() for value in options['symbols']))
        lookbacks = tuple(sorted(set(options['lookbacks'])))
        class_horizon = options['classification_horizon']
        regression_horizon = options['regression_horizon']
        report = {
            'configuration': {
                'symbols': symbols,
                'lookbacks': lookbacks,
                'classification_forecast_horizon': class_horizon,
                'classification_purge_gap': class_horizon,
                'regression_forecast_horizon': regression_horizon,
                'regression_purge_gap': regression_horizon,
                'feature_experiments': FEATURE_EXPERIMENT_LABELS,
                'target_noise_diagnostics': (
                    'Use diagnose_classification_target_noise; this broad feature '
                    'command does not open Test for multiple noise bands.'
                ),
                'quality_gate_changes': False,
                'production_feature_changes': False,
                'feature_selection_source': 'purged_walk_forward_validation_only',
                'independent_test_role': 'report_and_post-selection_confirmation_only',
            },
            'current_features': {
                'classification': CLASSIFICATION_FEATURE_SETS['A'],
                'regression': REGRESSION_FEATURE_SETS['A'],
                'shared': sorted(
                    set(CLASSIFICATION_FEATURE_SETS['A'])
                    & set(REGRESSION_FEATURE_SETS['A'])
                ),
                'classification_only': sorted(
                    set(CLASSIFICATION_FEATURE_SETS['A'])
                    - set(REGRESSION_FEATURE_SETS['A'])
                ),
                'regression_only': sorted(
                    set(REGRESSION_FEATURE_SETS['A'])
                    - set(CLASSIFICATION_FEATURE_SETS['A'])
                ),
            },
            'experiment_features': {
                task: {
                    experiment: experiment_feature_names(task, experiment)
                    for experiment in FEATURE_EXPERIMENT_LABELS
                }
                for task in ('classification', 'regression')
            },
            'results': [],
            'feature_quality': [],
            'regime_sensitivity': [],
        }

        for symbol in symbols:
            security = (
                Security.objects.filter(symbol=symbol, is_active=True)
                .order_by('-country', 'mic_code', 'exchange', 'id')
                .first()
            )
            if security is None:
                report['results'].append({
                    'symbol': symbol,
                    'status': 'error',
                    'error': 'No active local Security exists for this symbol.',
                })
                continue
            try:
                longest_bars, market_metadata = _load_prediction_bars(
                    security, max(lookbacks),
                )
            except PredictionDataError as exc:
                report['results'].append({
                    'symbol': symbol,
                    'status': 'market_data_unavailable',
                    'error': str(exc),
                })
                continue

            for lookback in lookbacks:
                bars = tuple(longest_bars[-lookback:])
                production_classification = build_prediction_feature_dataset(
                    bars, class_horizon,
                )
                production_regression = build_prediction_feature_dataset(
                    bars, regression_horizon,
                )
                common = {
                    'symbol': symbol,
                    'lookback': lookback,
                    'status': 'complete',
                    'market_date_range': {
                        'first': bars[0].date.isoformat(),
                        'last': bars[-1].date.isoformat(),
                        'source': market_metadata['source'],
                    },
                    'targets': {
                        'classification': target_distribution(production_classification),
                        'regression': target_distribution(production_regression),
                        'classification_alignment_example': target_alignment_example(
                            bars, production_classification,
                        ),
                        'regression_alignment_example': target_alignment_example(
                            bars, production_regression,
                        ),
                    },
                }
                for experiment in FEATURE_EXPERIMENT_LABELS:
                    started = monotonic()
                    classification_dataset = build_experiment_dataset(
                        bars, class_horizon, 'classification', experiment,
                    )
                    regression_dataset = build_experiment_dataset(
                        bars, regression_horizon, 'regression', experiment,
                    )
                    classification = _classification_summary(
                        evaluate_classification_dataset(classification_dataset),
                    )
                    classification['experiment'] = experiment
                    classification['feature_count'] = len(
                        classification_dataset.feature_names
                    )
                    regression = _regression_summary(
                        regression_experiment_result(
                            regression_dataset,
                            current_price=float(bars[-1].close),
                        ),
                    )
                    regression['experiment'] = experiment
                    regression['feature_count'] = len(
                        regression_dataset.regression_feature_names
                    )
                    row = {
                        **common,
                        'experiment': experiment,
                        'experiment_label': FEATURE_EXPERIMENT_LABELS[experiment],
                        'classification': classification,
                        'regression': regression,
                        'duration_seconds': monotonic() - started,
                        'fair_comparison': {
                            'shared_classification_rows_across_A_to_E': (
                                classification_dataset.sample_count
                            ),
                            'shared_regression_rows_across_A_to_E': (
                                regression_dataset.sample_count
                            ),
                            'identical_split_rules': True,
                            'independent_test_excluded_from_selection': True,
                        },
                    }
                    report['results'].append(row)
                    self.stderr.write(
                        f'completed {symbol} {lookback} {experiment} '
                        f'class_wf={classification["walk_forward"]["macro_f1"]:.4f} '
                        f'reg_wf_mae_imp={regression["walk_forward"]["mae_improvement"]:.4f} '
                        f'seconds={row["duration_seconds"]:.1f}'
                    )

                for task, horizon in (
                    ('classification', class_horizon),
                    ('regression', regression_horizon),
                ):
                    for experiment in ('A', 'E'):
                        dataset = build_experiment_dataset(
                            bars, horizon, task, experiment,
                        )
                        report['feature_quality'].append({
                            'symbol': symbol,
                            'lookback': lookback,
                            'task': task,
                            'experiment': experiment,
                            **feature_quality_report(dataset, task, bars=bars),
                        })

                if lookback == max(lookbacks):
                    regime_dataset = build_experiment_dataset(
                        bars, class_horizon, 'classification', 'E',
                    )
                    report['regime_sensitivity'].append({
                        'symbol': symbol,
                        'lookback': lookback,
                        **regime_sensitivity_report(bars, regime_dataset),
                    })

        report['walk_forward_only_rankings'] = {
            'classification': _aggregate_experiment_results(
                report['results'], 'classification',
            ),
            'regression': _aggregate_experiment_results(
                report['results'], 'regression',
            ),
        }
        report['selection_integrity'] = {
            'ranking_uses_independent_test': False,
            'ranking_uses_walk_forward_only': True,
            'test_results_are_reported_after_each_fixed_experiment': True,
            'production_features_were_modified': False,
            'production_target_was_modified': False,
            'quality_gates_were_modified': False,
        }
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
        if options['output']:
            output_path = Path(options['output']).resolve()
            output_path.write_text(serialized, encoding='utf-8')
            self.stderr.write(f'wrote report to {output_path}')

        if options['format'] == 'json':
            self.stdout.write(serialized)
            return
        for row in report['results']:
            if row.get('status') != 'complete':
                self.stdout.write(
                    f'{row.get("symbol")} | {row.get("status")} | {row.get("error", "")}'
                )
                continue
            classification = row['classification']
            regression = row['regression']
            self.stdout.write(' | '.join((
                row['symbol'],
                f'lookback={row["lookback"]}',
                f'experiment={row["experiment"]}',
                f'class_wf_ba={classification["walk_forward"]["balanced_accuracy"]:.4f}',
                f'class_wf_macro={classification["walk_forward"]["macro_f1"]:.4f}',
                f'class_test_ba={classification["independent_test"]["balanced_accuracy"]:.4f}',
                f'class_test_macro={classification["independent_test"]["macro_f1"]:.4f}',
                f'class_gate={classification["final_gate_passed"]}',
                f'reg_wf_mae_imp={regression["walk_forward"]["mae_improvement"]:.4f}',
                f'reg_fold_ratio={regression["walk_forward"]["improving_fold_ratio"]:.4f}',
                f'reg_test_mae_imp={regression["independent_test"]["mae_improvement"]:.4f}',
                f'reg_test_rmse_imp={regression["independent_test"]["rmse_improvement"]:.4f}',
                f'reg_gate={regression["final_gate_passed"]}',
            )))
        self.stdout.write('Walk-Forward-only rankings:')
        self.stdout.write(json.dumps(
            report['walk_forward_only_rankings'], indent=2, allow_nan=False,
        ))
