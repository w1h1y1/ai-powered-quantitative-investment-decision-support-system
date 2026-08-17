import json
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.services import (
    PredictionDataError,
    _load_prediction_bars,
    generate_prediction_market_data,
)


DEFAULT_SYMBOLS = ('AAPL', 'NVDA', 'MSFT', 'AMZN', 'AVGO')
DEFAULT_LOOKBACKS = (504, 756, 1260)


def _relative_improvement(baseline, model):
    baseline = float(baseline or 0.0)
    model = float(model or 0.0)
    return (baseline - model) / baseline if baseline > 0 else 0.0


def _classification_folds(payload):
    metadata_folds = {
        fold['fold']: fold
        for fold in payload.get('ml_metadata', {}).get('walk_forward_folds', ())
    }
    metric_folds = {
        fold['fold']: fold
        for fold in payload.get('model_metrics', {}).get('walk_forward_folds', ())
    }
    return [
        {
            **metadata_folds.get(fold_number, {}),
            **metric_folds.get(fold_number, {}),
        }
        for fold_number in sorted(set(metadata_folds) | set(metric_folds))
    ]


def _summarize_payload(payload, duration_seconds):
    model_metrics = payload.get('model_metrics') or {}
    metadata = payload.get('ml_metadata') or {}
    classification_walk_forward = payload.get('walk_forward_quality_gate') or {}
    classification_test = payload.get('independent_test_quality_gate') or {}
    classification_final = payload.get('final_classification_quality_gate') or {}
    validation_metrics = model_metrics.get('validation_selection_metrics') or {}
    classification_walk_forward_observed = classification_walk_forward.get('observed') or {}
    classification_test_observed = classification_test.get('observed') or {}
    classification_walk_forward_baseline = float(
        classification_walk_forward_observed.get('baseline_accuracy', 0.0)
    )
    classification_test_baseline = float(
        classification_test_observed.get(
            'baseline_accuracy',
            model_metrics.get('majority_class_baseline_accuracy', 0.0),
        )
    )

    regression_metrics = model_metrics.get('regression') or {}
    regression_walk_forward = regression_metrics.get('walk_forward_quality_metrics') or {}
    regression_walk_forward_model = regression_walk_forward.get('model_metrics') or {}
    regression_walk_forward_baseline = regression_walk_forward.get('zero_return_baseline') or {}
    regression_test_baseline = regression_metrics.get('zero_return_baseline') or {}
    regression_walk_forward_gate = payload.get('regression_walk_forward_quality_gate') or {}
    regression_test_gate = payload.get('regression_independent_test_quality_gate') or {}
    regression_final_gate = payload.get('final_regression_quality_gate') or {}
    regression_split = metadata.get('regression_evaluation_split') or {}

    classification_folds = _classification_folds(payload)
    regression_folds = list(regression_walk_forward.get('folds') or ())
    return {
        'symbol': payload.get('symbol'),
        'lookback': payload.get('lookback'),
        'historical_data_count': payload.get('historical_data_count'),
        'latest_market_date': payload.get('latest_market_date'),
        'requested_start_date': payload.get('market_data', {}).get('requested_start_date'),
        'requested_end_date': payload.get('market_data', {}).get('requested_end_date'),
        'market_data_source': payload.get('market_data', {}).get('source'),
        'fetched_from_provider': payload.get('market_data', {}).get('fetched_from_provider'),
        'ml_cache_hit': payload.get('ml_cache', {}).get('hit'),
        'duration_seconds': round(duration_seconds, 3),
        'classification': {
            'forecast_horizon': payload.get('classification_forecast_horizon'),
            'purge_gap': payload.get('classification_purge_gap'),
            'usable_labeled_samples': metadata.get('classification_usable_labeled_samples'),
            'training_samples': model_metrics.get('training_samples'),
            'validation_samples': model_metrics.get('validation_samples'),
            'independent_test_samples': model_metrics.get('test_samples'),
            'walk_forward_fold_count': metadata.get('walk_forward_fold_count'),
            'folds': classification_folds,
            'walk_forward': {
                'accuracy': validation_metrics.get('accuracy'),
                'balanced_accuracy': validation_metrics.get('balanced_accuracy'),
                'macro_f1': validation_metrics.get('macro_f1'),
                'minimum_class_recall': validation_metrics.get('minimum_class_recall'),
                'roc_auc': validation_metrics.get('roc_auc'),
                'majority_baseline_accuracy': classification_walk_forward_baseline,
                'improvement_over_baseline': (
                    float(validation_metrics.get('accuracy', 0.0))
                    - classification_walk_forward_baseline
                ),
                'gate_passed': classification_walk_forward.get('passed'),
                'reason_codes': classification_walk_forward.get('reason_codes', []),
            },
            'independent_test': {
                'accuracy': model_metrics.get('accuracy'),
                'balanced_accuracy': model_metrics.get('balanced_accuracy'),
                'macro_f1': model_metrics.get('macro_f1'),
                'minimum_class_recall': model_metrics.get('minimum_class_recall'),
                'roc_auc': model_metrics.get('roc_auc'),
                'majority_baseline_accuracy': classification_test_baseline,
                'improvement_over_baseline': (
                    float(model_metrics.get('accuracy', 0.0))
                    - classification_test_baseline
                ),
                'gate_passed': classification_test.get('passed'),
                'reason_codes': classification_test.get('reason_codes', []),
            },
            'final_gate_passed': classification_final.get('passed'),
            'selected_candidate_model': payload.get('selected_candidate_model'),
            'selected_candidate_threshold': payload.get('selected_candidate_threshold'),
            'published_threshold': payload.get('selected_threshold'),
            'threshold_stability': model_metrics.get('threshold_stability'),
        },
        'regression': {
            'forecast_horizon': payload.get('regression_forecast_horizon'),
            'purge_gap': payload.get('regression_purge_gap'),
            'usable_labeled_samples': metadata.get('regression_usable_labeled_samples'),
            'training_samples': regression_split.get('training_samples'),
            'validation_samples': regression_split.get('validation_samples'),
            'independent_test_samples': regression_split.get('test_samples'),
            'walk_forward_fold_count': regression_split.get('walk_forward_fold_count'),
            'folds': regression_folds,
            'walk_forward': {
                'mae': regression_walk_forward_model.get('mae'),
                'rmse': regression_walk_forward_model.get('rmse'),
                'r2': regression_walk_forward_model.get('r2'),
                'zero_return_baseline_mae': regression_walk_forward_baseline.get('mae'),
                'zero_return_baseline_rmse': regression_walk_forward_baseline.get('rmse'),
                'mae_improvement': _relative_improvement(
                    regression_walk_forward_baseline.get('mae'),
                    regression_walk_forward_model.get('mae'),
                ),
                'rmse_improvement': _relative_improvement(
                    regression_walk_forward_baseline.get('rmse'),
                    regression_walk_forward_model.get('rmse'),
                ),
                'improving_fold_count': regression_walk_forward.get('improving_fold_count'),
                'improving_fold_ratio': regression_walk_forward.get('improving_fold_ratio'),
                'gate_passed': regression_walk_forward_gate.get('passed'),
                'reason_codes': regression_walk_forward_gate.get('reason_codes', []),
            },
            'independent_test': {
                'mae': regression_metrics.get('mae'),
                'rmse': regression_metrics.get('rmse'),
                'r2': regression_metrics.get('r2'),
                'zero_return_baseline_mae': regression_test_baseline.get('mae'),
                'zero_return_baseline_rmse': regression_test_baseline.get('rmse'),
                'mae_improvement': _relative_improvement(
                    regression_test_baseline.get('mae'),
                    regression_metrics.get('mae'),
                ),
                'rmse_improvement': _relative_improvement(
                    regression_test_baseline.get('rmse'),
                    regression_metrics.get('rmse'),
                ),
                'gate_passed': regression_test_gate.get('passed'),
                'reason_codes': regression_test_gate.get('reason_codes', []),
            },
            'final_gate_passed': regression_final_gate.get('passed'),
            'selected_candidate_model': payload.get('selected_regression_candidate_model'),
        },
        'isolation': {
            'walk_forward_shuffle': metadata.get('walk_forward_shuffle'),
            'final_test_untouched': metadata.get('final_test_untouched'),
            'test_used_for_model_selection': metadata.get(
                'independent_test_used_for_model_selection'
            ),
            'test_used_for_hyperparameter_tuning': metadata.get(
                'independent_test_used_for_hyperparameter_tuning'
            ),
            'test_used_for_threshold_selection': metadata.get(
                'independent_test_used_for_threshold_selection'
            ),
            'test_used_for_regression_model_selection': metadata.get(
                'independent_test_used_for_regression_model_selection'
            ),
        },
    }


class Command(BaseCommand):
    help = (
        'Compare Prediction classification and regression diagnostics across real '
        'historical lookbacks without changing models, quality gates, or split rules.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+', default=list(DEFAULT_SYMBOLS))
        parser.add_argument('--lookbacks', nargs='+', type=int, default=list(DEFAULT_LOOKBACKS))
        parser.add_argument('--classification-horizon', type=int, default=1)
        parser.add_argument('--regression-horizon', type=int, default=10)
        parser.add_argument('--format', choices=('json', 'table'), default='table')

    def handle(self, *args, **options):
        symbols = tuple(dict.fromkeys(symbol.strip().upper() for symbol in options['symbols']))
        lookbacks = tuple(sorted(set(options['lookbacks'])))
        classification_horizon = options['classification_horizon']
        regression_horizon = options['regression_horizon']
        report = {
            'configuration': {
                'symbols': symbols,
                'lookbacks': lookbacks,
                'classification_forecast_horizon': classification_horizon,
                'regression_forecast_horizon': regression_horizon,
                'model_or_gate_changes': False,
                'independent_test_role': 'publication_only',
            },
            'results': [],
        }

        for symbol in symbols:
            security = (
                Security.objects
                .filter(symbol=symbol, is_active=True)
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

            # Ask the existing Prediction market-data service for the longest
            # requested window first. This fills missing provider history once;
            # every experiment still slices and trains on its own lookback.
            try:
                _load_prediction_bars(security, max(lookbacks))
            except PredictionDataError as exc:
                self.stderr.write(f'{symbol} longest-window prefetch: {exc}')

            for lookback in lookbacks:
                started = monotonic()
                try:
                    payload = generate_prediction_market_data(
                        security=security,
                        classification_forecast_horizon=classification_horizon,
                        regression_forecast_horizon=regression_horizon,
                        lookback=lookback,
                    )
                except PredictionDataError as exc:
                    report['results'].append({
                        'symbol': symbol,
                        'lookback': lookback,
                        'status': 'market_data_unavailable',
                        'error': str(exc),
                    })
                    self.stderr.write(f'{symbol} lookback={lookback}: {exc}')
                    continue

                result = _summarize_payload(payload, monotonic() - started)
                result['status'] = 'complete'
                report['results'].append(result)
                self.stderr.write(
                    f'completed {symbol} lookback={lookback} '
                    f'class={result["classification"]["final_gate_passed"]} '
                    f'reg={result["regression"]["final_gate_passed"]}'
                )

        if options['format'] == 'json':
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
            return

        for result in report['results']:
            if result.get('status') != 'complete':
                self.stdout.write(
                    f'{result.get("symbol")} {result.get("lookback", "-")} | '
                    f'{result.get("status")} | {result.get("error", "")}'
                )
                continue
            classification = result['classification']
            regression = result['regression']
            self.stdout.write(' | '.join((
                result['symbol'],
                f'lookback={result["lookback"]}',
                f'data={result["historical_data_count"]}',
                f'class_wf_ba={classification["walk_forward"]["balanced_accuracy"]:.4f}',
                f'class_test_ba={classification["independent_test"]["balanced_accuracy"]:.4f}',
                f'class_gate={classification["final_gate_passed"]}',
                f'reg_wf_mae_imp={regression["walk_forward"]["mae_improvement"]:.4f}',
                f'reg_test_mae_imp={regression["independent_test"]["mae_improvement"]:.4f}',
                f'reg_gate={regression["final_gate_passed"]}',
                f'cache={result["ml_cache_hit"]}',
                f'seconds={result["duration_seconds"]}',
            )))
            self.stdout.write('  CLASS ' + ' | '.join((
                f'n={classification["training_samples"]}/{classification["validation_samples"]}/{classification["independent_test_samples"]}',
                f'folds={classification["walk_forward_fold_count"]}',
                f'train_by_fold={[fold.get("training_samples") for fold in classification["folds"]]}',
                f'wf_acc={classification["walk_forward"]["accuracy"]:.4f}',
                f'wf_macro_f1={classification["walk_forward"]["macro_f1"]:.4f}',
                f'wf_min_recall={classification["walk_forward"]["minimum_class_recall"]:.4f}',
                f'wf_auc={classification["walk_forward"]["roc_auc"]:.4f}',
                f'wf_baseline={classification["walk_forward"]["majority_baseline_accuracy"]:.4f}',
                f'wf_acc_imp={classification["walk_forward"]["improvement_over_baseline"]:.4f}',
                f'wf_gate={classification["walk_forward"]["gate_passed"]}',
                f'test_acc={classification["independent_test"]["accuracy"]:.4f}',
                f'test_macro_f1={classification["independent_test"]["macro_f1"]:.4f}',
                f'test_min_recall={classification["independent_test"]["minimum_class_recall"]:.4f}',
                f'test_auc={classification["independent_test"]["roc_auc"]:.4f}',
                f'test_baseline={classification["independent_test"]["majority_baseline_accuracy"]:.4f}',
                f'test_acc_imp={classification["independent_test"]["improvement_over_baseline"]:.4f}',
                f'test_gate={classification["independent_test"]["gate_passed"]}',
                f'model={classification["selected_candidate_model"]}',
                f'threshold={classification["selected_candidate_threshold"]}',
                f'threshold_stability={(classification["threshold_stability"] or {}).get("status")}',
            )))
            self.stdout.write('  REG ' + ' | '.join((
                f'n={regression["training_samples"]}/{regression["validation_samples"]}/{regression["independent_test_samples"]}',
                f'folds={regression["walk_forward_fold_count"]}',
                f'train_by_fold={[fold.get("training_samples") for fold in regression["folds"]]}',
                f'wf_mae={regression["walk_forward"]["mae"]:.6f}',
                f'wf_rmse={regression["walk_forward"]["rmse"]:.6f}',
                f'wf_r2={regression["walk_forward"]["r2"]:.4f}',
                f'wf_zero_mae={regression["walk_forward"]["zero_return_baseline_mae"]:.6f}',
                f'wf_zero_rmse={regression["walk_forward"]["zero_return_baseline_rmse"]:.6f}',
                f'wf_mae_imp={regression["walk_forward"]["mae_improvement"]:.4f}',
                f'wf_rmse_imp={regression["walk_forward"]["rmse_improvement"]:.4f}',
                f'improving_folds={regression["walk_forward"]["improving_fold_count"]}/{regression["walk_forward_fold_count"]}',
                f'wf_gate={regression["walk_forward"]["gate_passed"]}',
                f'test_mae={regression["independent_test"]["mae"]:.6f}',
                f'test_rmse={regression["independent_test"]["rmse"]:.6f}',
                f'test_r2={regression["independent_test"]["r2"]:.4f}',
                f'test_zero_mae={regression["independent_test"]["zero_return_baseline_mae"]:.6f}',
                f'test_zero_rmse={regression["independent_test"]["zero_return_baseline_rmse"]:.6f}',
                f'test_mae_imp={regression["independent_test"]["mae_improvement"]:.4f}',
                f'test_rmse_imp={regression["independent_test"]["rmse_improvement"]:.4f}',
                f'test_gate={regression["independent_test"]["gate_passed"]}',
                f'model={regression["selected_candidate_model"]}',
            )))
