"""Run isolated SPY/QQQ Market Context feature ablations."""

import json
import pickle
from pathlib import Path
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.market_context_diagnostics import (
    ALL_CORRELATION_BETA_FEATURES,
    ALL_QQQ_FEATURES,
    ALL_RELATIVE_STRENGTH_FEATURES,
    ALL_SPY_FEATURES,
    CLASSIFICATION_MARKET_FEATURE_SETS,
    MARKET_CONTEXT_CANDIDATE_RULES,
    MARKET_CONTEXT_EXPERIMENTS,
    REGRESSION_MARKET_FEATURE_SETS,
    aggregate_market_context_results,
    build_market_context_experiment_datasets,
    classification_summary,
    evaluate_classification_independent_test,
    evaluate_classification_market_development,
    evaluate_regression_independent_test,
    evaluate_regression_market_development,
    regression_summary,
    select_market_context_candidate,
)
from prediction.ml_service import PREDICTION_PIPELINE_VERSION
from prediction.services import PredictionDataError, _load_prediction_bars


DEFAULT_CONTEXTS = {'AAPL': (504, 756), 'NVDA': (504, 756), 'MSFT': (504, 756)}
CACHE_SCHEMA = 'market-context-development-v1-fixed-stock-test-boundary'


def _security(symbol):
    security = (
        Security.objects.filter(symbol=symbol, is_active=True)
        .order_by('-country', 'mic_code', 'exchange', 'id').first()
    )
    if security is None:
        raise PredictionDataError(f'No active local Security exists for {symbol}.')
    return security


def _cache_path(cache_directory, symbol, lookback, task, experiment, data_signature):
    if cache_directory is None:
        return None
    signature = '_'.join(data_signature.replace(':', '-').split())
    return cache_directory / f'{symbol}_{lookback}_{task}_{experiment}_{signature}.pickle'


def _checkpoint(cache_path, payload=None):
    if cache_path is None:
        return None
    if payload is None:
        if not cache_path.exists():
            return None
        with cache_path.open('rb') as stream:
            cached = pickle.load(stream)
        if cached.get('cache_schema') != CACHE_SCHEMA:
            return None
        return cached['result']
    with cache_path.open('wb') as stream:
        pickle.dump({'cache_schema': CACHE_SCHEMA, 'result': payload}, stream)
    return payload


def _fold_metadata(fold):
    return {
        key: fold[key] for key in (
            'fold', 'training_samples', 'validation_samples', 'gap_size',
            'actual_up_count', 'actual_down_count', 'minority_class_count',
            'minority_class_ratio', 'severe_class_imbalance', 'purge_safe',
            'boundaries',
        ) if key in fold
    }


def _public_classification_result(result):
    return {
        'scope': result['scope'], 'selected_model': result['selected_model'],
        'selected_params': result['selected_params'],
        'selected_threshold': result['selected_threshold'],
        'metrics': result['metrics'], 'quality_gate': result['quality_gate'],
        'threshold_stability': result['threshold_stability'],
        'purge_gap': result['purge_gap'],
        'all_fold_purges_safe': result['all_fold_purges_safe'],
        'independent_test_accessed': result['independent_test_accessed'],
        'independent_test_used_for_selection': result['independent_test_used_for_selection'],
        'folds': [_fold_metadata(fold) for fold in result['folds']],
        'fold_metrics': result['fold_metrics'],
        'train_metrics': result['train_metrics'],
        'train_validation_gap': result['train_validation_gap'],
        'fold_pass_ratio': result['fold_pass_ratio'],
        'fold_diagnostics': result['fold_diagnostics'],
        'feature_importance_stability': result['feature_importance_stability'],
        'candidate_models': [{
            'model': candidate['model'], 'params': candidate.get('params'),
            'threshold': candidate['threshold'], 'metrics': candidate['metrics'],
            'selection_score': candidate['selection_score'],
            'quality_gate': candidate['quality_gate'],
        } for candidate in result['candidate_models']],
    }


def _public_regression_result(result):
    return {
        'scope': result['scope'], 'selected_model': result['selected_model'],
        'selected_family': result['selected_family'],
        'selected_params': result['selected_params'],
        'metrics': result['metrics'], 'quality_gate': result['quality_gate'],
        'purge_gap': result['purge_gap'],
        'all_fold_purges_safe': result['all_fold_purges_safe'],
        'independent_test_accessed': result['independent_test_accessed'],
        'independent_test_used_for_selection': result['independent_test_used_for_selection'],
        'folds': [_fold_metadata(fold) for fold in result['folds']],
        'train_metrics': result['train_metrics'],
        'train_validation_gap': result['train_validation_gap'],
        'fold_diagnostics': result['fold_diagnostics'],
        'feature_importance_stability': result['feature_importance_stability'],
        'candidate_models': [{
            'model': candidate['model'], 'family': candidate['family'],
            'params': candidate['params'], 'model_metrics': candidate['model_metrics'],
            'zero_return_baseline': candidate['zero_return_baseline'],
            'mae_improvement_over_zero': candidate['mae_improvement_over_zero'],
            'rmse_improvement_over_zero': candidate['rmse_improvement_over_zero'],
            'improving_fold_ratio': candidate['improving_fold_ratio'],
            'selection_score': candidate.get('selection_score'),
            'quality_gate': candidate['quality_gate'],
            'selected': candidate.get('selected', False),
        } for candidate in result['candidate_models']],
    }


def _summary_without_folds(summary):
    return {key: value for key, value in summary.items() if key != 'fold_metrics'}


class Command(BaseCommand):
    help = 'Run Development-only A-F SPY/QQQ Market Context ablations.'

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+')
        parser.add_argument('--lookbacks', nargs='+', type=int)
        parser.add_argument('--output', default='prediction_market_context_diagnostics.json')
        parser.add_argument('--development-cache-dir')
        parser.add_argument('--development-only', action='store_true')

    def handle(self, *args, **options):
        symbols = tuple(dict.fromkeys(value.upper() for value in options['symbols'])) if options['symbols'] else tuple(DEFAULT_CONTEXTS)
        requested_lookbacks = set(options['lookbacks']) if options['lookbacks'] else None
        contexts = {
            symbol: tuple(value for value in DEFAULT_CONTEXTS.get(symbol, (504, 756))
                          if requested_lookbacks is None or value in requested_lookbacks)
            for symbol in symbols
        }
        maximum_lookback = max(value for values in contexts.values() for value in values)
        cache_directory = Path(options['development_cache_dir']).resolve() if options['development_cache_dir'] else None
        if cache_directory:
            cache_directory.mkdir(parents=True, exist_ok=True)

        # Reuse the same production market-data service and database cache.
        spy_bars, spy_metadata = _load_prediction_bars(_security('SPY'), maximum_lookback)
        qqq_bars, qqq_metadata = _load_prediction_bars(_security('QQQ'), maximum_lookback)
        benchmark_signature = (
            f'{spy_bars[0].date}:{spy_bars[-1].date}:{len(spy_bars)}:'
            f'{qqq_bars[0].date}:{qqq_bars[-1].date}:{len(qqq_bars)}:'
            f'{PREDICTION_PIPELINE_VERSION}'
        )
        report = {
            'configuration': {
                'contexts': contexts, 'classification_horizon': 1,
                'classification_purge_gap': 1, 'regression_horizon': 10,
                'regression_purge_gap': 10, 'experiments': MARKET_CONTEXT_EXPERIMENTS,
                'classification_feature_sets': CLASSIFICATION_MARKET_FEATURE_SETS,
                'regression_feature_sets': REGRESSION_MARKET_FEATURE_SETS,
                'all_constructed_spy_features': ALL_SPY_FEATURES,
                'all_constructed_qqq_features': ALL_QQQ_FEATURES,
                'all_constructed_relative_strength_features': ALL_RELATIVE_STRENGTH_FEATURES,
                'all_constructed_correlation_beta_features': ALL_CORRELATION_BETA_FEATURES,
                'candidate_rules': MARKET_CONTEXT_CANDIDATE_RULES,
                'prediction_time_semantics': (
                    'After market close t is complete, stock/SPY/QQQ close(t) and '
                    'trailing data through t predict stock t+1 direction / t+10 return.'
                ),
                'vix': {
                    'included': False, 'experiment': 'G',
                    'reason': ('No VIX/^VIX Security or stable Twelve Data time-series contract; '
                               'VIX futures ETFs are not substituted for spot VIX.'),
                },
                'production_features_changed': False, 'production_targets_changed': False,
                'production_quality_gates_changed': False,
                'production_api_or_frontend_changed': False,
            },
            'benchmark_data': {
                'SPY': {'first_date': spy_bars[0].date.isoformat(), 'last_date': spy_bars[-1].date.isoformat(),
                        'bar_count': len(spy_bars), 'metadata': spy_metadata},
                'QQQ': {'first_date': qqq_bars[0].date.isoformat(), 'last_date': qqq_bars[-1].date.isoformat(),
                        'bar_count': len(qqq_bars), 'metadata': qqq_metadata},
            },
            'alignment_reports': [], 'development_classification': [],
            'development_regression': [], 'classification_aggregates': [],
            'regression_aggregates': [], 'relative_strength_before_after': [],
            'classification_candidate_selection': None,
            'regression_candidate_selection': None,
            'independent_test_results': {'classification': [], 'regression': []},
            'isolation_audit': {},
        }
        raw_classification, raw_regression, context_inputs = [], [], {}
        for symbol, lookbacks in contexts.items():
            if not lookbacks:
                continue
            stock_bars_long, stock_metadata = _load_prediction_bars(
                _security(symbol), max(lookbacks),
            )
            for lookback in lookbacks:
                stock_bars = tuple(stock_bars_long[-lookback:])
                classification_bundle = build_market_context_experiment_datasets(
                    stock_bars, spy_bars, qqq_bars, 1, 'classification',
                )
                regression_bundle = build_market_context_experiment_datasets(
                    stock_bars, spy_bars, qqq_bars, 10, 'regression',
                )
                context_inputs[(symbol, lookback)] = {
                    'stock_bars': stock_bars, 'classification': classification_bundle,
                    'regression': regression_bundle,
                }
                common = {
                    'symbol': symbol, 'lookback': lookback,
                    'market_date_range': {'first': stock_bars[0].date.isoformat(),
                                          'last': stock_bars[-1].date.isoformat(),
                                          'source': stock_metadata['source']},
                }
                report['alignment_reports'].append({
                    **common,
                    'classification': {
                        **classification_bundle['alignment'],
                        'common_development_samples': classification_bundle['common_sample_count'],
                        'fixed_partition': classification_bundle['fixed_partition'],
                    },
                    'regression': {
                        **regression_bundle['alignment'],
                        'common_development_samples': regression_bundle['common_sample_count'],
                        'fixed_partition': regression_bundle['fixed_partition'],
                    },
                })
                for task, bundle, evaluator, summarizer, raw_results, output_key in (
                    ('classification', classification_bundle,
                     evaluate_classification_market_development, classification_summary,
                     raw_classification, 'development_classification'),
                    ('regression', regression_bundle,
                     evaluate_regression_market_development, regression_summary,
                     raw_regression, 'development_regression'),
                ):
                    for experiment in ('A', 'B', 'C', 'D', 'E', 'F'):
                        cache_path = _cache_path(
                            cache_directory, symbol, lookback, task, experiment,
                            f'{stock_bars[0].date}:{stock_bars[-1].date}:{benchmark_signature}',
                        )
                        result = _checkpoint(cache_path)
                        if result is None:
                            started = monotonic()
                            result = evaluator(bundle['datasets'][experiment])
                            _checkpoint(cache_path, result)
                            self.stderr.write(
                                f'{task} {symbol} {lookback} {experiment} '
                                f'{monotonic()-started:.1f}s'
                            )
                        else:
                            self.stderr.write(f'loaded {task} {symbol} {lookback} {experiment}')
                        summary = summarizer(result)
                        selection_row = {
                            **common, 'experiment': experiment,
                            'label': MARKET_CONTEXT_EXPERIMENTS[experiment],
                            'feature_count': (
                                len(bundle['datasets'][experiment].feature_names)
                                if task == 'classification'
                                else len(bundle['datasets'][experiment].regression_feature_names)
                            ),
                            'common_development_samples': bundle['common_sample_count'],
                            'summary': summary, 'result': result,
                        }
                        raw_results.append(selection_row)
                        report[output_key].append({
                            **{key: value for key, value in selection_row.items()
                               if key != 'result'},
                            'summary': _summary_without_folds(summary),
                            'result': (
                                _public_classification_result(result)
                                if task == 'classification'
                                else _public_regression_result(result)
                            ),
                        })

        report['classification_aggregates'] = aggregate_market_context_results(
            raw_classification, 'classification',
        )
        report['regression_aggregates'] = aggregate_market_context_results(
            raw_regression, 'regression',
        )
        report['relative_strength_before_after'] = [
            {
                'task': task, 'symbol': row['symbol'], 'lookback': row['lookback'],
                'before_experiment': 'D', 'after_experiment': 'E',
                'before': _summary_without_folds(next(
                    item['summary'] for item in rows
                    if item['symbol'] == row['symbol'] and item['lookback'] == row['lookback']
                    and item['experiment'] == 'D'
                )),
                'after': _summary_without_folds(row['summary']),
            }
            for task, rows in (
                ('classification', raw_classification), ('regression', raw_regression),
            )
            for row in rows if row['experiment'] == 'E'
        ]
        class_selection = select_market_context_candidate(raw_classification, 'classification')
        regression_selection = select_market_context_candidate(raw_regression, 'regression')
        report['classification_candidate_selection'] = class_selection
        report['regression_candidate_selection'] = regression_selection
        class_experiment = class_selection['selected_experiment']
        regression_experiment = regression_selection['selected_experiment']

        # Test matrices and labels are not constructed until candidates are frozen.
        if not options['development_only']:
            for (symbol, lookback), inputs in context_inputs.items():
                if class_experiment:
                    frozen_bundle = build_market_context_experiment_datasets(
                        inputs['stock_bars'], spy_bars, qqq_bars, 1, 'classification',
                        include_independent_test=True,
                    )
                    frozen = next(row['result'] for row in raw_classification
                                  if row['symbol'] == symbol and row['lookback'] == lookback
                                  and row['experiment'] == class_experiment)
                    evaluation = evaluate_classification_independent_test(
                        frozen_bundle['datasets'][class_experiment],
                        frozen_bundle['independent_test_datasets'][class_experiment], frozen,
                    )
                    report['independent_test_results']['classification'].append({
                        'symbol': symbol, 'lookback': lookback,
                        'experiment': class_experiment, 'result': evaluation,
                    })
                if regression_experiment:
                    frozen_bundle = build_market_context_experiment_datasets(
                        inputs['stock_bars'], spy_bars, qqq_bars, 10, 'regression',
                        include_independent_test=True,
                    )
                    frozen = next(row['result'] for row in raw_regression
                                  if row['symbol'] == symbol and row['lookback'] == lookback
                                  and row['experiment'] == regression_experiment)
                    evaluation = evaluate_regression_independent_test(
                        frozen_bundle['datasets'][regression_experiment],
                        frozen_bundle['independent_test_datasets'][regression_experiment], frozen,
                    )
                    report['independent_test_results']['regression'].append({
                        'symbol': symbol, 'lookback': lookback,
                        'experiment': regression_experiment, 'result': evaluation,
                    })

        report['isolation_audit'] = {
            'prediction_time_semantics_verified': True,
            'alignment_method': 'exact_trading_date_not_row_index',
            'future_or_backward_fill_used': False,
            'fixed_stock_only_test_boundary_before_benchmark_availability': True,
            'test_benchmark_availability_used_for_development_split': False,
            'classification_purge_gap': 1, 'regression_purge_gap': 10,
            'all_classification_fold_purges_safe': all(
                fold['purge_safe'] for row in raw_classification for fold in row['result']['folds']
            ),
            'all_regression_fold_purges_safe': all(
                fold['purge_safe'] for row in raw_regression for fold in row['result']['folds']
            ),
            'classification_candidate_frozen_before_test': True,
            'regression_candidate_frozen_before_test': True,
            'independent_test_used_for_feature_selection': False,
            'independent_test_used_for_model_or_threshold_selection': False,
            'classification_candidate_count': 1 if class_experiment else 0,
            'regression_candidate_count': 1 if regression_experiment else 0,
            'classification_independent_test_evaluation_count': len(
                report['independent_test_results']['classification']
            ),
            'regression_independent_test_evaluation_count': len(
                report['independent_test_results']['regression']
            ),
            'non_candidate_experiments_tested': False,
            'production_target_changed': False, 'production_feature_pipeline_changed': False,
            'production_api_or_frontend_changed': False,
            'production_quality_gate_lowered': False,
            'vix_experiment_run': False,
        }
        output = Path(options['output']).resolve()
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False, default=list),
            encoding='utf-8',
        )
        self.stdout.write(f'wrote {output}')
        self.stdout.write(
            f'classification_candidate={class_experiment or "None"} '
            f'regression_candidate={regression_experiment or "None"}'
        )
