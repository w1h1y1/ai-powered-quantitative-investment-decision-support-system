import json
import pickle
from pathlib import Path
from statistics import mean, pstdev
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.ml_service import PREDICTION_QUALITY_GATE_THRESHOLDS
from prediction.regime_feature_diagnostics import (
    CLASSIFICATION_REGIME_FEATURE_SETS,
    REGIME_EXPERIMENT_LABELS,
    REGRESSION_REGIME_FEATURE_SETS,
    TREND_REGIME_THRESHOLDS,
    VOLATILITY_REGIME_THRESHOLDS,
    build_regime_experiment_datasets,
    chronological_target_shift_report,
    evaluate_classification_development,
    evaluate_classification_independent_test,
    evaluate_regression_development,
    evaluate_regression_independent_test,
    regime_composition_report,
    regime_shift_report,
    select_regime_feature_candidate,
)
from prediction.services import PredictionDataError, _load_prediction_bars


DEFAULT_CONTEXTS = {
    'AAPL': (504, 756),
    'NVDA': (504, 756, 1260),
    'MSFT': (504, 756),
}


def _classification_fold_pass_count(result):
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    passed = 0
    diagnostics = []
    for metrics, fold in zip(result['fold_metrics'], result['folds']):
        training_up = sum(fold['y_classification_train'])
        training_down = len(fold['y_classification_train']) - training_up
        majority = 1 if training_up > training_down else 0
        labels = fold['y_classification_validation']
        baseline_accuracy = sum(label == majority for label in labels) / len(labels)
        baseline_improvement = metrics['accuracy'] - baseline_accuracy
        fold_passed = (
            metrics['actual_up_count'] > 0
            and metrics['actual_down_count'] > 0
            and metrics['predicted_up_count'] > 0
            and metrics['predicted_down_count'] > 0
            and metrics['balanced_accuracy']
            >= thresholds['minimum_balanced_accuracy']
            and metrics['macro_f1'] >= thresholds['minimum_macro_f1']
            and baseline_improvement
            >= thresholds['minimum_accuracy_improvement_over_baseline']
        )
        passed += fold_passed
        diagnostics.append({
            **metrics,
            'fold': fold['fold'],
            'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'],
            'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'],
            'majority_baseline_accuracy': float(baseline_accuracy),
            'accuracy_improvement_over_baseline': float(baseline_improvement),
            'fold_passed': bool(fold_passed),
        })
    return int(passed), diagnostics


def _classification_summary(result):
    metrics = result['metrics']
    gate = result['quality_gate']
    fold_pass_count, fold_diagnostics = _classification_fold_pass_count(result)
    standard_deviation = metrics['std_macro_f1']
    stability = (
        'stable' if standard_deviation <= 0.05
        else 'moderate' if standard_deviation <= 0.10
        else 'unstable'
    )
    return {
        'selected_model': result['selected_model'],
        'selected_params': result['selected_params'],
        'selected_threshold': result['selected_threshold'],
        'walk_forward': {
            'accuracy': metrics['accuracy'],
            'balanced_accuracy': metrics['mean_balanced_accuracy'],
            'macro_f1': metrics['mean_macro_f1'],
            'roc_auc': metrics['mean_roc_auc'],
            'minimum_class_recall': metrics['mean_minimum_class_recall'],
            'majority_baseline_accuracy': gate['observed']['baseline_accuracy'],
            'accuracy_improvement_over_baseline': (
                gate['observed']['accuracy_improvement_over_baseline']
            ),
            'fold_pass_count': fold_pass_count,
            'fold_count': len(result['folds']),
            'fold_pass_ratio': float(fold_pass_count / len(result['folds'])),
            'macro_f1_standard_deviation': standard_deviation,
            'stability': stability,
            'quality_gate_passed': gate['passed'],
            'quality_gate_reason_codes': gate['reason_codes'],
        },
        'folds': fold_diagnostics,
        'threshold_stability': result['threshold_stability'],
        'purge_gap': result['purge_gap'],
        'all_fold_purges_safe': result['all_fold_purges_safe'],
        'independent_test_accessed': result['independent_test_accessed'],
        'independent_test_used_for_selection': result[
            'independent_test_used_for_selection'
        ],
    }


def _regression_summary(result):
    metrics = result['metrics']
    fold_maes = [fold['mae'] for fold in metrics['folds']]
    mean_fold_mae = mean(fold_maes)
    fold_mae_cv = metrics['fold_mae_std'] / mean_fold_mae if mean_fold_mae else 0.0
    stability = (
        'stable' if fold_mae_cv <= 0.25
        else 'moderate' if fold_mae_cv <= 0.50
        else 'unstable'
    )
    return {
        'selected_model': result['selected_model'],
        'selected_family': result['selected_family'],
        'selected_params': result['selected_params'],
        'walk_forward': {
            'mae': metrics['model_metrics']['mae'],
            'rmse': metrics['model_metrics']['rmse'],
            'r2': metrics['model_metrics']['r2'],
            'zero_return_baseline_mae': metrics['zero_return_baseline']['mae'],
            'zero_return_baseline_rmse': metrics['zero_return_baseline']['rmse'],
            'mae_improvement': metrics['mae_improvement_over_zero'],
            'rmse_improvement': metrics['rmse_improvement_over_zero'],
            'improving_fold_count': metrics['improving_fold_count'],
            'improving_fold_ratio': metrics['improving_fold_ratio'],
            'fold_count': len(metrics['folds']),
            'fold_mae_standard_deviation': metrics['fold_mae_std'],
            'fold_mae_coefficient_of_variation': float(fold_mae_cv),
            'stability': stability,
            'quality_gate_passed': result['quality_gate']['passed'],
            'quality_gate_reason_codes': result['quality_gate']['reason_codes'],
        },
        'folds': metrics['folds'],
        'purge_gap': result['purge_gap'],
        'all_fold_purges_safe': result['all_fold_purges_safe'],
        'independent_test_accessed': result['independent_test_accessed'],
        'independent_test_used_for_selection': result[
            'independent_test_used_for_selection'
        ],
    }


def _aggregate(results, task):
    aggregates = []
    for experiment in REGIME_EXPERIMENT_LABELS:
        rows = [row for row in results if row['experiment'] == experiment]
        if task == 'classification':
            values = [row['summary']['walk_forward'] for row in rows]
            aggregates.append({
                'experiment': experiment,
                'label': REGIME_EXPERIMENT_LABELS[experiment],
                'context_count': len(rows),
                'mean_balanced_accuracy': float(mean(
                    value['balanced_accuracy'] for value in values
                )),
                'mean_macro_f1': float(mean(value['macro_f1'] for value in values)),
                'mean_roc_auc': float(mean(value['roc_auc'] for value in values)),
                'mean_minimum_class_recall': float(mean(
                    value['minimum_class_recall'] for value in values
                )),
                'mean_baseline_improvement': float(mean(
                    value['accuracy_improvement_over_baseline'] for value in values
                )),
                'mean_fold_pass_ratio': float(mean(
                    value['fold_pass_ratio'] for value in values
                )),
                'between_context_macro_f1_standard_deviation': float(pstdev(
                    value['macro_f1'] for value in values
                )),
                'walk_forward_gate_pass_count': sum(
                    value['quality_gate_passed'] for value in values
                ),
            })
        else:
            values = [row['summary']['walk_forward'] for row in rows]
            aggregates.append({
                'experiment': experiment,
                'label': REGIME_EXPERIMENT_LABELS[experiment],
                'context_count': len(rows),
                'mean_mae_improvement': float(mean(
                    value['mae_improvement'] for value in values
                )),
                'mean_rmse_improvement': float(mean(
                    value['rmse_improvement'] for value in values
                )),
                'mean_improving_fold_ratio': float(mean(
                    value['improving_fold_ratio'] for value in values
                )),
                'mean_r2': float(mean(value['r2'] for value in values)),
                'mean_fold_mae_coefficient_of_variation': float(mean(
                    value['fold_mae_coefficient_of_variation'] for value in values
                )),
                'walk_forward_gate_pass_count': sum(
                    value['quality_gate_passed'] for value in values
                ),
            })
    return aggregates


def _test_summary(task, evaluation):
    if task == 'classification':
        metrics = evaluation['metrics']
        return {
            'balanced_accuracy': metrics['balanced_accuracy'],
            'macro_f1': metrics['macro_f1'],
            'roc_auc': metrics['roc_auc'],
            'minimum_class_recall': metrics['minimum_class_recall'],
            'majority_baseline_accuracy': metrics['majority_baseline_accuracy'],
            'accuracy_improvement_over_baseline': metrics[
                'accuracy_improvement_over_baseline'
            ],
            'quality_gate_passed': evaluation['quality_gate']['passed'],
            'quality_gate_reason_codes': evaluation['quality_gate']['reason_codes'],
            'final_quality_gate_passed': evaluation['final_quality_gate']['passed'],
            'isolation': {
                key: evaluation[key] for key in (
                    'test_used_for_model_selection',
                    'test_used_for_threshold_selection',
                    'test_used_for_feature_selection',
                    'model_refit_after_test',
                    'test_evaluation_count',
                    'purge_gap',
                    'validation_test_purge_safe',
                )
            },
        }
    metrics = evaluation['metrics']
    gate = evaluation['quality_gate']
    return {
        'mae': metrics['model_metrics']['mae'],
        'rmse': metrics['model_metrics']['rmse'],
        'r2': metrics['model_metrics']['r2'],
        'zero_return_baseline_mae': metrics['zero_return_baseline']['mae'],
        'zero_return_baseline_rmse': metrics['zero_return_baseline']['rmse'],
        'mae_improvement': gate['observed']['mae_improvement'],
        'rmse_improvement': gate['observed']['rmse_improvement'],
        'quality_gate_passed': gate['passed'],
        'quality_gate_reason_codes': gate['reason_codes'],
        'final_quality_gate_passed': evaluation['final_quality_gate']['passed'],
        'isolation': {
            key: evaluation[key] for key in (
                'test_used_for_model_selection',
                'test_used_for_feature_selection',
                'model_refit_after_test',
                'test_evaluation_count',
                'purge_gap',
                'validation_test_purge_safe',
            )
        },
    }


class Command(BaseCommand):
    help = (
        'Run offline regime-shift diagnostics and A-E regime-normalized feature '
        'ablations with Development-only feature selection.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+')
        parser.add_argument('--lookbacks', nargs='+', type=int)
        parser.add_argument('--output')
        parser.add_argument('--format', choices=('json', 'table'), default='table')
        parser.add_argument('--development-cache-dir')
        parser.add_argument('--development-only', action='store_true')

    def handle(self, *args, **options):
        requested_symbols = (
            tuple(dict.fromkeys(value.upper() for value in options['symbols']))
            if options['symbols'] else tuple(DEFAULT_CONTEXTS)
        )
        requested_lookbacks = (
            tuple(sorted(set(options['lookbacks']))) if options['lookbacks'] else None
        )
        contexts = {
            symbol: tuple(
                lookback for lookback in DEFAULT_CONTEXTS.get(symbol, (504, 756))
                if requested_lookbacks is None or lookback in requested_lookbacks
            )
            for symbol in requested_symbols
        }
        report = {
            'configuration': {
                'contexts': contexts,
                'classification_horizon': 1,
                'classification_purge_gap': 1,
                'regression_horizon': 10,
                'regression_purge_gap': 10,
                'experiments': REGIME_EXPERIMENT_LABELS,
                'classification_feature_sets': CLASSIFICATION_REGIME_FEATURE_SETS,
                'regression_feature_sets': REGRESSION_REGIME_FEATURE_SETS,
                'volatility_regime_thresholds': VOLATILITY_REGIME_THRESHOLDS,
                'trend_regime_thresholds': TREND_REGIME_THRESHOLDS,
                'production_targets_changed': False,
                'production_quality_gates_changed': False,
                'production_prediction_lab_changed': False,
                'feature_selection_source': 'development_purged_walk_forward_only',
            },
            'development_classification': [],
            'development_regression': [],
            'classification_aggregates': [],
            'regression_aggregates': [],
            'development_regime_shift': [],
            'post_selection_regime_shift': [],
            'regime_composition': [],
            'classification_candidate_selection': None,
            'regression_candidate_selection': None,
            'independent_test_results': {
                'classification': [],
                'regression': [],
            },
            'isolation_audit': {},
        }
        bundles = {}
        raw_classification = []
        raw_regression = []
        cache_directory = (
            Path(options['development_cache_dir']).resolve()
            if options['development_cache_dir'] else None
        )
        if cache_directory is not None:
            cache_directory.mkdir(parents=True, exist_ok=True)

        # Phase 1: only Development blocks and purged Walk-Forward Validation.
        for symbol, lookbacks in contexts.items():
            if not lookbacks:
                continue
            security = (
                Security.objects.filter(symbol=symbol, is_active=True)
                .order_by('-country', 'mic_code', 'exchange', 'id')
                .first()
            )
            if security is None:
                raise PredictionDataError(f'No active local Security exists for {symbol}.')
            longest_bars, market_metadata = _load_prediction_bars(
                security, max(lookbacks),
            )
            for lookback in lookbacks:
                bars = tuple(longest_bars[-lookback:])
                classification_bundle = build_regime_experiment_datasets(
                    bars, 1, 'classification',
                )
                regression_bundle = build_regime_experiment_datasets(
                    bars, 10, 'regression',
                )
                bundles[(symbol, lookback)] = {
                    'bars': bars,
                    'market_metadata': market_metadata,
                    'classification': classification_bundle,
                    'regression': regression_bundle,
                }
                cache_path = (
                    cache_directory / f'{symbol}_{lookback}.pickle'
                    if cache_directory is not None else None
                )
                if cache_path is not None and cache_path.exists():
                    with cache_path.open('rb') as cache_file:
                        cached = pickle.load(cache_file)
                    if cached.get('cache_schema') != 'regime-development-v1':
                        raise ValueError(f'Unsupported research cache schema: {cache_path}')
                    raw_classification.extend(cached['raw_classification'])
                    raw_regression.extend(cached['raw_regression'])
                    report['development_classification'].extend(
                        cached['development_classification']
                    )
                    report['development_regression'].extend(
                        cached['development_regression']
                    )
                    cached_common = {
                        'symbol': symbol,
                        'lookback': lookback,
                        'market_date_range': cached[
                            'development_regime_shift'
                        ]['market_date_range'],
                    }
                    report['development_regime_shift'].append({
                        **cached_common,
                        **regime_shift_report(
                            bars,
                            classification_bundle['datasets']['A'],
                            classification_bundle['rows'],
                            include_test=False,
                        ),
                        'classification_target_shift': chronological_target_shift_report(
                            bars,
                            classification_bundle['datasets']['A'],
                            include_test=False,
                        ),
                        'regression_target_shift': chronological_target_shift_report(
                            bars,
                            regression_bundle['datasets']['A'],
                            include_test=False,
                        ),
                    })
                    report['regime_composition'].append({
                        **cached_common,
                        'classification': regime_composition_report(
                            classification_bundle['datasets']['A'],
                            classification_bundle['rows'],
                            'classification',
                        ),
                        'regression': regime_composition_report(
                            regression_bundle['datasets']['A'],
                            regression_bundle['rows'],
                            'regression',
                        ),
                    })
                    self.stderr.write(
                        f'loaded development checkpoint {symbol} lookback={lookback}'
                    )
                    continue
                common = {
                    'symbol': symbol,
                    'lookback': lookback,
                    'market_date_range': {
                        'first': bars[0].date.isoformat(),
                        'last': bars[-1].date.isoformat(),
                        'source': market_metadata['source'],
                    },
                }
                context_regime_shift = {
                    **common,
                    **regime_shift_report(
                        bars,
                        classification_bundle['datasets']['A'],
                        classification_bundle['rows'],
                        include_test=False,
                    ),
                    'classification_target_shift': chronological_target_shift_report(
                        bars,
                        classification_bundle['datasets']['A'],
                        include_test=False,
                    ),
                    'regression_target_shift': chronological_target_shift_report(
                        bars,
                        regression_bundle['datasets']['A'],
                        include_test=False,
                    ),
                }
                context_regime_composition = {
                    **common,
                    'classification': regime_composition_report(
                        classification_bundle['datasets']['A'],
                        classification_bundle['rows'],
                        'classification',
                    ),
                    'regression': regime_composition_report(
                        regression_bundle['datasets']['A'],
                        regression_bundle['rows'],
                        'regression',
                    ),
                }
                report['development_regime_shift'].append(context_regime_shift)
                report['regime_composition'].append(context_regime_composition)
                context_raw_classification = []
                context_raw_regression = []
                context_classification_summaries = []
                context_regression_summaries = []
                for experiment in REGIME_EXPERIMENT_LABELS:
                    started = monotonic()
                    class_result = evaluate_classification_development(
                        classification_bundle['datasets'][experiment],
                    )
                    class_raw = {
                        **common,
                        'experiment': experiment,
                        **class_result,
                    }
                    raw_classification.append(class_raw)
                    context_raw_classification.append(class_raw)
                    class_summary = {
                        **common,
                        'experiment': experiment,
                        'label': REGIME_EXPERIMENT_LABELS[experiment],
                        'feature_count': len(
                            classification_bundle['datasets'][experiment].feature_names
                        ),
                        'common_sample_count': classification_bundle['common_sample_count'],
                        'summary': _classification_summary(class_result),
                        'duration_seconds': float(monotonic() - started),
                    }
                    context_classification_summaries.append(class_summary)
                    report['development_classification'].append(class_summary)
                    started = monotonic()
                    regression_result = evaluate_regression_development(
                        regression_bundle['datasets'][experiment],
                    )
                    regression_raw = {
                        **common,
                        'experiment': experiment,
                        **regression_result,
                    }
                    raw_regression.append(regression_raw)
                    context_raw_regression.append(regression_raw)
                    regression_summary = {
                        **common,
                        'experiment': experiment,
                        'label': REGIME_EXPERIMENT_LABELS[experiment],
                        'feature_count': len(
                            regression_bundle['datasets'][experiment].regression_feature_names
                        ),
                        'common_sample_count': regression_bundle['common_sample_count'],
                        'summary': _regression_summary(regression_result),
                        'duration_seconds': float(monotonic() - started),
                    }
                    context_regression_summaries.append(regression_summary)
                    report['development_regression'].append(regression_summary)
                    self.stderr.write(
                        f'development {symbol} lookback={lookback} exp={experiment} '
                        f'class_ba={class_result["metrics"]["mean_balanced_accuracy"]:.4f} '
                        f'reg_mae_imp={regression_result["metrics"]["mae_improvement_over_zero"]:.4f}'
                    )
                if cache_path is not None:
                    cache_payload = {
                        'cache_schema': 'regime-development-v1',
                        'symbol': symbol,
                        'lookback': lookback,
                        'raw_classification': context_raw_classification,
                        'raw_regression': context_raw_regression,
                        'development_classification': context_classification_summaries,
                        'development_regression': context_regression_summaries,
                        'development_regime_shift': context_regime_shift,
                        'regime_composition': context_regime_composition,
                    }
                    with cache_path.open('wb') as cache_file:
                        pickle.dump(cache_payload, cache_file)
                    self.stderr.write(f'wrote development checkpoint {cache_path}')

        report['classification_aggregates'] = _aggregate(
            report['development_classification'], 'classification',
        )
        report['regression_aggregates'] = _aggregate(
            report['development_regression'], 'regression',
        )
        classification_selection = select_regime_feature_candidate(
            raw_classification, 'classification',
        )
        regression_selection = select_regime_feature_candidate(
            raw_regression, 'regression',
        )
        report['classification_candidate_selection'] = classification_selection
        report['regression_candidate_selection'] = regression_selection
        class_experiment = classification_selection['selected_experiment']
        regression_experiment = regression_selection['selected_experiment']
        self.stderr.write(
            'frozen candidates: classification='
            f'{class_experiment or "none"} regression={regression_experiment or "none"}'
        )

        # Phase 2: Test-period drift is diagnostic only and computed after both
        # candidates are frozen. Model Test evaluation is run only when a stable
        # candidate exists; A is evaluated once solely as the frozen reference.
        if not options['development_only']:
            for (symbol, lookback), bundle in bundles.items():
                common = {'symbol': symbol, 'lookback': lookback}
                report['post_selection_regime_shift'].append({
                    **common,
                    **regime_shift_report(
                        bundle['bars'],
                        bundle['classification']['datasets']['A'],
                        bundle['classification']['rows'],
                        include_test=True,
                    ),
                    'classification_target_shift': chronological_target_shift_report(
                        bundle['bars'],
                        bundle['classification']['datasets']['A'],
                        include_test=True,
                    ),
                    'regression_target_shift': chronological_target_shift_report(
                        bundle['bars'],
                        bundle['regression']['datasets']['A'],
                        include_test=True,
                    ),
                })
                if class_experiment is not None:
                    for experiment, role in (
                        ('A', 'production_feature_baseline'),
                        (class_experiment, 'frozen_regime_candidate'),
                    ):
                        development = next(
                            row for row in raw_classification
                            if row['symbol'] == symbol
                            and row['lookback'] == lookback
                            and row['experiment'] == experiment
                        )
                        evaluation = evaluate_classification_independent_test(
                            bundle['classification']['datasets'][experiment], development,
                        )
                        report['independent_test_results']['classification'].append({
                            **common,
                            'experiment': experiment,
                            'role': role,
                            'result': _test_summary('classification', evaluation),
                        })
                if regression_experiment is not None:
                    for experiment, role in (
                        ('A', 'production_feature_baseline'),
                        (regression_experiment, 'frozen_regime_candidate'),
                    ):
                        development = next(
                            row for row in raw_regression
                            if row['symbol'] == symbol
                            and row['lookback'] == lookback
                            and row['experiment'] == experiment
                        )
                        evaluation = evaluate_regression_independent_test(
                            bundle['regression']['datasets'][experiment], development,
                        )
                        report['independent_test_results']['regression'].append({
                            **common,
                            'experiment': experiment,
                            'role': role,
                            'result': _test_summary('regression', evaluation),
                        })

        report['isolation_audit'] = {
            'classification_candidate_frozen_before_test': True,
            'regression_candidate_frozen_before_test': True,
            'independent_test_used_for_feature_selection': False,
            'independent_test_used_for_model_selection': False,
            'independent_test_used_for_threshold_selection': False,
            'classification_candidate_count': 1 if class_experiment else 0,
            'regression_candidate_count': 1 if regression_experiment else 0,
            'non_candidate_experiments_tested': False,
            'test_period_drift_computed_after_candidate_freeze': True,
            'production_target_changed': False,
            'production_quality_gate_changed': False,
            'production_frontend_or_api_changed': False,
            'development_only_run': bool(options['development_only']),
        }

        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
        if options['output']:
            path = Path(options['output']).resolve()
            path.write_text(serialized, encoding='utf-8')
            self.stderr.write(f'wrote report to {path}')
        if options['format'] == 'json':
            self.stdout.write(serialized)
            return
        for row in report['classification_aggregates']:
            self.stdout.write(
                f'CLASS {row["experiment"]} BA={row["mean_balanced_accuracy"]:.4f} '
                f'MF1={row["mean_macro_f1"]:.4f} AUC={row["mean_roc_auc"]:.4f} '
                f'MinR={row["mean_minimum_class_recall"]:.4f}'
            )
        for row in report['regression_aggregates']:
            self.stdout.write(
                f'REG {row["experiment"]} MAEimp={row["mean_mae_improvement"]:.4f} '
                f'RMSEimp={row["mean_rmse_improvement"]:.4f} '
                f'fold={row["mean_improving_fold_ratio"]:.4f}'
            )
        self.stdout.write(
            f'classification_candidate={class_experiment or "None"} '
            f'regression_candidate={regression_experiment or "None"}'
        )
