import json
from statistics import mean

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from market.models import Security, SecurityDailyPrice
from prediction.feature_service import build_prediction_feature_dataset
from prediction.ml_service import (
    _regression_metrics,
    _regression_model,
    _regression_prediction_diagnostics,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    evaluate_final_regression_quality_gate,
    evaluate_regression_independent_test_quality_gate,
    evaluate_regression_quality_gate,
    tune_regression_models,
)
from prediction.services import _prices_to_bars


class Command(BaseCommand):
    help = (
        'Read cached daily prices and print reproducible purged Walk-Forward and '
        'independent Test regression diagnostics without fetching or writing market data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            default=['AAPL', 'AMZN', 'NVDA', 'MSFT', 'GOOGL', 'AVGO'],
        )
        parser.add_argument('--horizons', nargs='+', type=int, default=[5, 10, 20])
        parser.add_argument('--lookback', type=int, default=504)
        parser.add_argument('--summary', action='store_true')
        parser.add_argument('--table', action='store_true')
        parser.add_argument('--include-folds', action='store_true')

    def handle(self, *args, **options):
        lookback = options['lookback']
        report = {
            'lookback': lookback,
            'selection_source': 'purged_walk_forward_validation',
            'independent_test_role': 'publication_only',
            'results': [],
        }
        for raw_symbol in options['symbols']:
            symbol = raw_symbol.strip().upper()
            security = Security.objects.filter(symbol=symbol).order_by('id').first()
            if security is None:
                raise CommandError(f'No local Security exists for {symbol}.')
            prices = list(
                SecurityDailyPrice.objects.filter(security=security)
                .order_by('-date')[:lookback]
            )
            prices.reverse()
            if len(prices) < lookback:
                raise CommandError(
                    f'{symbol} has {len(prices)} cached daily prices; {lookback} are required.'
                )
            bars = _prices_to_bars(prices)
            for horizon in options['horizons']:
                dataset = build_prediction_feature_dataset(bars, horizon)
                split = build_purged_chronological_split(dataset)
                folds = build_purged_walk_forward_folds(dataset, split)
                if len(folds) < 2:
                    report['results'].append({
                        'symbol': symbol,
                        'horizon': horizon,
                        'status': 'insufficient_data',
                        'usable_samples': dataset.sample_count,
                        'fold_count': len(folds),
                    })
                    continue
                tuning = tune_regression_models(folds)
                selected = tuning['selected']
                walk_forward_gate = evaluate_regression_quality_gate(selected)

                model = _regression_model(selected)
                development_end = split['development_end']
                development_labels = dataset.regression_labels[:development_end]
                model.fit(
                    dataset.regression_features[:development_end],
                    development_labels,
                )
                test_labels = np.asarray(split['y_regression_test'], dtype=float)
                test_predictions = np.asarray(
                    model.predict(split['x_regression_test']),
                    dtype=float,
                )
                zero_predictions = np.zeros(len(test_labels), dtype=float)
                development_mean = float(mean(development_labels))
                historical_mean_predictions = np.full(
                    len(test_labels),
                    development_mean,
                    dtype=float,
                )
                test_evaluation = {
                    'source': 'independent_test',
                    'sample_count': len(test_labels),
                    'model_metrics': _regression_metrics(test_labels, test_predictions),
                    'zero_return_baseline': {
                        'name': 'zero_future_return',
                        **_regression_metrics(test_labels, zero_predictions),
                    },
                    'historical_training_mean_baseline': {
                        'name': 'development_training_mean_future_return',
                        'training_mean_return': development_mean,
                        **_regression_metrics(test_labels, historical_mean_predictions),
                    },
                    'prediction_diagnostics': _regression_prediction_diagnostics(
                        test_labels,
                        test_predictions,
                    ),
                }
                independent_test_gate = evaluate_regression_independent_test_quality_gate(
                    test_evaluation,
                )
                final_gate = evaluate_final_regression_quality_gate(
                    walk_forward_gate,
                    independent_test_gate,
                )
                report['results'].append({
                    'symbol': symbol,
                    'horizon': horizon,
                    'latest_market_date': bars[-1].date.isoformat(),
                    'usable_samples': dataset.sample_count,
                    'walk_forward_samples': selected['sample_count'],
                    'test_samples': len(test_labels),
                    'fold_count': len(folds),
                    'selected_model': selected['model'],
                    'selected_params': selected['params'],
                    'walk_forward': selected,
                    'walk_forward_quality_gate': walk_forward_gate,
                    'independent_test': test_evaluation,
                    'independent_test_quality_gate': independent_test_gate,
                    'final_quality_gate': final_gate,
                    'candidate_count': tuning['candidate_count'],
                    'candidates': tuning['candidates'],
                    'test_used_for_selection': False,
                })
                self.stderr.write(f'completed {symbol} horizon={horizon}')
        if options['table']:
            for result in report['results']:
                if result.get('status') == 'insufficient_data':
                    self.stdout.write(
                        f'{result["symbol"]} h={result["horizon"]} insufficient_data'
                    )
                    continue
                walk_forward = result['walk_forward']
                test = result['independent_test']
                self.stdout.write(
                    ' | '.join((
                        f'{result["symbol"]} h={result["horizon"]}',
                        f'n={result["usable_samples"]}/{result["walk_forward_samples"]}/{result["test_samples"]}',
                        f'folds={result["fold_count"]}',
                        f'model={result["selected_model"]} {result["selected_params"]}',
                        f'wf_mae={walk_forward["model_metrics"]["mae"]:.6f}/{walk_forward["zero_return_baseline"]["mae"]:.6f}',
                        f'wf_rmse={walk_forward["model_metrics"]["rmse"]:.6f}/{walk_forward["zero_return_baseline"]["rmse"]:.6f}',
                        f'wf_improving_folds={walk_forward["improving_fold_count"]}/{len(walk_forward["folds"])}',
                        f'wf_gate={result["walk_forward_quality_gate"]["passed"]}',
                        f'test_mae={test["model_metrics"]["mae"]:.6f}/{test["zero_return_baseline"]["mae"]:.6f}',
                        f'test_rmse={test["model_metrics"]["rmse"]:.6f}/{test["zero_return_baseline"]["rmse"]:.6f}',
                        f'test_gate={result["independent_test_quality_gate"]["passed"]}',
                        f'final={result["final_quality_gate"]["passed"]}',
                    ))
                )
                if options['include_folds']:
                    for fold in walk_forward['folds']:
                        self.stdout.write(
                            '  '
                            + ' | '.join((
                                f'fold={fold["fold"]}',
                                f'train={fold["training_samples"]}',
                                f'validation={fold["validation_samples"]}',
                                f'gap={fold["gap_size"]}',
                                f'purge_safe={fold["purge_safe"]}',
                                f'mae={fold["mae"]:.6f}/{fold["zero_return_baseline"]["mae"]:.6f}',
                                f'rmse={fold["rmse"]:.6f}/{fold["zero_return_baseline"]["rmse"]:.6f}',
                                f'beats_zero={fold["beats_zero_on_mae_and_rmse"]}',
                            ))
                        )
            return
        if options['summary']:
            report['results'] = [
                result
                if result.get('status') == 'insufficient_data'
                else {
                    'symbol': result['symbol'],
                    'horizon': result['horizon'],
                    'latest_market_date': result['latest_market_date'],
                    'usable_samples': result['usable_samples'],
                    'walk_forward_samples': result['walk_forward_samples'],
                    'test_samples': result['test_samples'],
                    'fold_count': result['fold_count'],
                    'selected_model': result['selected_model'],
                    'selected_params': result['selected_params'],
                    'walk_forward_model_metrics': result['walk_forward']['model_metrics'],
                    'walk_forward_zero_baseline': result['walk_forward']['zero_return_baseline'],
                    'walk_forward_historical_mean_baseline': (
                        result['walk_forward']['historical_training_mean_baseline']
                    ),
                    'walk_forward_prediction_diagnostics': (
                        result['walk_forward']['prediction_diagnostics']
                    ),
                    'walk_forward_improving_fold_ratio': (
                        result['walk_forward']['improving_fold_ratio']
                    ),
                    'walk_forward_folds': result['walk_forward']['folds'],
                    'walk_forward_quality_gate': result['walk_forward_quality_gate'],
                    'independent_test': result['independent_test'],
                    'independent_test_quality_gate': result['independent_test_quality_gate'],
                    'final_quality_gate': result['final_quality_gate'],
                    'candidate_count': result['candidate_count'],
                    'candidate_summary': [{
                        'model': candidate['model'],
                        'params': candidate['params'],
                        'selected': candidate['selected'],
                        'mae': candidate['model_metrics']['mae'],
                        'rmse': candidate['model_metrics']['rmse'],
                        'improving_fold_ratio': candidate['improving_fold_ratio'],
                    } for candidate in result['candidates']],
                    'test_used_for_selection': False,
                }
                for result in report['results']
            ]
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
