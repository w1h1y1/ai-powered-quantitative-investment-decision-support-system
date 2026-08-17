"""Run the isolated model-architecture / learning-objective research study."""

import json
import pickle
from pathlib import Path
from statistics import mean
from time import monotonic

from django.core.management.base import BaseCommand

from market.models import Security
from prediction.feature_service import build_prediction_feature_datasets
from prediction.model_architecture_diagnostics import (
    ARCHITECTURE_CANDIDATE_RULES,
    CLASSIFICATION_FAMILY_CONFIGS,
    CLASSIFICATION_OBJECTIVES,
    REGRESSION_FAMILY_CONFIGS,
    REGRESSION_OBJECTIVES,
    _classification_context_summary,
    _regression_context_summary,
    aggregate_model_results,
    classification_objective_experiments,
    evaluate_classification_families,
    evaluate_classification_independent_test,
    evaluate_regression_families,
    evaluate_regression_independent_test,
    regression_objective_experiments,
    regression_target_diagnostics,
    select_cross_context_candidate,
)
from prediction.services import PredictionDataError, _load_prediction_bars


DEFAULT_CONTEXTS = {'AAPL': (504, 756), 'NVDA': (504, 756), 'MSFT': (504, 756)}
CACHE_SCHEMA = 'model-architecture-development-v2-roc-auc'


def _classification_aggregate_rank(row):
    return (
        row['mean_macro_f1'] * 0.40 + row['mean_balanced_accuracy'] * 0.30
        + row['mean_roc_auc'] * 0.20 + row['mean_fold_pass_ratio'] * 0.10
        - max(row['mean_train_validation_gap'], 0.0) * 0.10
    )


def _regression_aggregate_rank(row):
    return (
        row['mean_mae_improvement'] * 0.50 + row['mean_rmse_improvement'] * 0.35
        + row['mean_improving_fold_ratio'] * 0.15
        - max(row['mean_train_validation_gap'], 0.0) * 0.10
    )


def _architecture_rows(symbol, lookback, classification, regression):
    classification_rows = [{
        'symbol': symbol, 'lookback': lookback, 'name': result['family'],
        'summary': _classification_context_summary(result), 'result': result,
    } for result in classification['families']]
    classification_rows.append({
        'symbol': symbol, 'lookback': lookback, 'name': 'Production Baseline',
        'summary': _classification_context_summary(classification['production_baseline']),
        'result': classification['production_baseline'],
    })
    regression_rows = [{
        'symbol': symbol, 'lookback': lookback, 'name': result['family'],
        'summary': _regression_context_summary(result), 'result': result,
    } for result in regression['families']]
    regression_rows.append({
        'symbol': symbol, 'lookback': lookback, 'name': 'Production Baseline',
        'summary': _regression_context_summary(regression['production_baseline']),
        'result': regression['production_baseline'],
    })
    return classification_rows, regression_rows


class Command(BaseCommand):
    help = 'Run Development-only model architecture and learning objective research.'

    def add_arguments(self, parser):
        parser.add_argument('--symbols', nargs='+')
        parser.add_argument('--lookbacks', nargs='+', type=int)
        parser.add_argument('--output', default='prediction_model_architecture_diagnostics.json')
        parser.add_argument('--development-cache-dir')
        parser.add_argument('--development-only', action='store_true')

    def handle(self, *args, **options):
        symbols = tuple(dict.fromkeys(value.upper() for value in options['symbols'])) if options['symbols'] else tuple(DEFAULT_CONTEXTS)
        lookback_filter = set(options['lookbacks']) if options['lookbacks'] else None
        contexts = {
            symbol: tuple(value for value in DEFAULT_CONTEXTS.get(symbol, (504, 756))
                          if lookback_filter is None or value in lookback_filter)
            for symbol in symbols
        }
        cache_dir = Path(options['development_cache_dir']).resolve() if options['development_cache_dir'] else None
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        report = {
            'configuration': {
                'contexts': contexts, 'classification_horizon': 1,
                'classification_purge_gap': 1, 'regression_horizon': 10,
                'regression_purge_gap': 10,
                'classification_model_families': CLASSIFICATION_FAMILY_CONFIGS,
                'regression_model_candidates': REGRESSION_FAMILY_CONFIGS,
                'classification_objectives': CLASSIFICATION_OBJECTIVES,
                'regression_objectives': REGRESSION_OBJECTIVES,
                'candidate_rules': ARCHITECTURE_CANDIDATE_RULES,
                'production_features_changed': False, 'production_targets_changed': False,
                'production_quality_gates_changed': False,
                'production_api_or_frontend_changed': False,
            },
            'architecture_classification': [], 'architecture_regression': [],
            'classification_aggregates': [], 'regression_aggregates': [],
            'classification_objective_results': [], 'regression_objective_results': [],
            'classification_objective_aggregates': [], 'regression_objective_aggregates': [],
            'regression_target_diagnostics': [], 'bias_variance_diagnostics': [],
            'classification_candidate_selection': None, 'regression_candidate_selection': None,
            'independent_test_results': {'classification': [], 'regression': []},
            'isolation_audit': {},
        }
        datasets = {}
        architecture_class_rows, architecture_reg_rows = [], []

        # Stage 1: fixed production objectives; architecture only.
        for symbol, lookbacks in contexts.items():
            if not lookbacks:
                continue
            security = (Security.objects.filter(symbol=symbol, is_active=True)
                        .order_by('-country', 'mic_code', 'exchange', 'id').first())
            if security is None:
                raise PredictionDataError(f'No active local Security exists for {symbol}.')
            longest_bars, market_metadata = _load_prediction_bars(security, max(lookbacks))
            for lookback in lookbacks:
                bars = tuple(longest_bars[-lookback:])
                bundle = build_prediction_feature_datasets(bars, 1, 10)
                datasets[(symbol, lookback)] = bundle
                cache_path = cache_dir / f'{symbol}_{lookback}.pickle' if cache_dir else None
                if cache_path and cache_path.exists():
                    with cache_path.open('rb') as stream:
                        cached = pickle.load(stream)
                    if cached.get('cache_schema') != CACHE_SCHEMA:
                        raise ValueError(f'Unsupported research cache schema: {cache_path}')
                    classification, regression = cached['classification'], cached['regression']
                    target_diagnostics = cached['target_diagnostics']
                    self.stderr.write(f'loaded checkpoint {symbol} lookback={lookback}')
                else:
                    started = monotonic()
                    classification = evaluate_classification_families(bundle['classification'])
                    self.stderr.write(f'class architecture {symbol} {lookback} in {monotonic()-started:.1f}s')
                    started = monotonic()
                    regression = evaluate_regression_families(bundle['regression'])
                    target_diagnostics = regression_target_diagnostics(bundle['regression'])
                    self.stderr.write(f'reg architecture {symbol} {lookback} in {monotonic()-started:.1f}s')
                    if cache_path:
                        with cache_path.open('wb') as stream:
                            pickle.dump({'cache_schema': CACHE_SCHEMA, 'classification': classification,
                                         'regression': regression, 'target_diagnostics': target_diagnostics}, stream)
                class_rows, reg_rows = _architecture_rows(symbol, lookback, classification, regression)
                architecture_class_rows.extend(class_rows)
                architecture_reg_rows.extend(reg_rows)
                report['architecture_classification'].append({
                    'symbol': symbol, 'lookback': lookback,
                    'market_date_range': {'first': bars[0].date.isoformat(), 'last': bars[-1].date.isoformat(),
                                          'source': market_metadata['source']},
                    'sample_count': bundle['classification'].sample_count,
                    'feature_count': len(bundle['classification'].feature_names),
                    'families': classification['families'],
                    'production_baseline': classification['production_baseline'],
                })
                report['architecture_regression'].append({
                    'symbol': symbol, 'lookback': lookback,
                    'sample_count': bundle['regression'].sample_count,
                    'feature_count': len(bundle['regression'].regression_feature_names),
                    'families': regression['families'],
                    'production_baseline': regression['production_baseline'],
                })
                report['regression_target_diagnostics'].append({
                    'symbol': symbol, 'lookback': lookback, **target_diagnostics,
                })

        report['classification_aggregates'] = aggregate_model_results(architecture_class_rows, 'classification')
        report['regression_aggregates'] = aggregate_model_results(architecture_reg_rows, 'regression')

        # Stage 2: freeze the most stable 1-2 Development families, then compare
        # only the small predeclared objective set on the same folds.
        classification_ranked = sorted(
            (row for row in report['classification_aggregates'] if row['name'] != 'Production Baseline'),
            key=_classification_aggregate_rank, reverse=True,
        )[:2]
        regression_ranked = sorted(
            (row for row in report['regression_aggregates'] if row['name'] != 'Production Baseline'),
            key=_regression_aggregate_rank, reverse=True,
        )[:2]
        frozen_class_families = [row['name'] for row in classification_ranked]
        frozen_reg_families = [row['name'] for row in regression_ranked]
        objective_class_rows = list(row for row in architecture_class_rows if row['name'] == 'Production Baseline')
        objective_reg_rows = list(row for row in architecture_reg_rows if row['name'] == 'Production Baseline')
        for (symbol, lookback), bundle in datasets.items():
            class_context = next(row for row in report['architecture_classification']
                                 if row['symbol'] == symbol and row['lookback'] == lookback)
            for family in frozen_class_families:
                frozen = next(row for row in class_context['families'] if row['family'] == family)
                for result in classification_objective_experiments(bundle['classification'], frozen):
                    name = f'{family} | {result["objective"]}'
                    item = {'symbol': symbol, 'lookback': lookback, 'name': name,
                            'summary': _classification_context_summary(result), 'result': result}
                    objective_class_rows.append(item)
                    report['classification_objective_results'].append(item)
            reg_context = next(row for row in report['architecture_regression']
                               if row['symbol'] == symbol and row['lookback'] == lookback)
            for family in frozen_reg_families:
                frozen = next(row for row in reg_context['families'] if row['family'] == family)
                for result in regression_objective_experiments(bundle['regression'], frozen):
                    name = f'{family} | {result["objective"]}'
                    item = {'symbol': symbol, 'lookback': lookback, 'name': name,
                            'summary': _regression_context_summary(result), 'result': result}
                    objective_reg_rows.append(item)
                    report['regression_objective_results'].append(item)

        report['classification_objective_aggregates'] = aggregate_model_results(objective_class_rows, 'classification')
        report['regression_objective_aggregates'] = aggregate_model_results(objective_reg_rows, 'regression')
        class_selection = select_cross_context_candidate(objective_class_rows, 'classification')
        reg_selection = select_cross_context_candidate(objective_reg_rows, 'regression')
        report['classification_candidate_selection'] = class_selection
        report['regression_candidate_selection'] = reg_selection

        # Final Test is untouched unless exactly one cross-context candidate has
        # already been frozen.  No Test result can feed back into this report's selection.
        if not options['development_only']:
            if class_selection['selected_candidate']:
                selected_name = class_selection['selected_candidate']
                for (symbol, lookback), bundle in datasets.items():
                    frozen = next(row['result'] for row in objective_class_rows
                                  if row['name'] == selected_name and row['symbol'] == symbol and row['lookback'] == lookback)
                    report['independent_test_results']['classification'].append({
                        'symbol': symbol, 'lookback': lookback, 'candidate': selected_name,
                        'result': evaluate_classification_independent_test(bundle['classification'], frozen),
                    })
            if reg_selection['selected_candidate']:
                selected_name = reg_selection['selected_candidate']
                for (symbol, lookback), bundle in datasets.items():
                    frozen = next(row['result'] for row in objective_reg_rows
                                  if row['name'] == selected_name and row['symbol'] == symbol and row['lookback'] == lookback)
                    report['independent_test_results']['regression'].append({
                        'symbol': symbol, 'lookback': lookback, 'candidate': selected_name,
                        'result': evaluate_regression_independent_test(bundle['regression'], frozen),
                    })

        # Bias/variance headlines are derived only from the Development folds.
        for row in architecture_class_rows:
            if row['name'] == 'Production Baseline':
                continue
            report['bias_variance_diagnostics'].append({
                'task': 'classification', 'symbol': row['symbol'], 'lookback': row['lookback'],
                'model': row['name'], 'train_validation_gap': row['result']['train_validation_gap'],
                'likely_overfitting': row['result']['train_validation_gap']['macro_f1'] > 0.15,
                'likely_underfitting': (row['result']['train']['balanced_accuracy'] < 0.56
                                        and row['result']['validation']['mean_balanced_accuracy'] < 0.54),
            })
        for row in architecture_reg_rows:
            if row['name'] == 'Production Baseline':
                continue
            report['bias_variance_diagnostics'].append({
                'task': 'regression', 'symbol': row['symbol'], 'lookback': row['lookback'],
                'model': row['name'], 'train_validation_gap': row['result']['train_validation_gap'],
                'likely_overfitting': row['result']['train_validation_gap']['r2'] > 0.50,
                'likely_underfitting': (row['result']['train']['r2'] < 0.10
                                        and row['result']['validation']['r2'] <= 0.0),
            })
        report['isolation_audit'] = {
            'all_splits_chronological': True, 'classification_purge_gap': 1,
            'regression_purge_gap': 10, 'scalers_fit_training_fold_only': True,
            'hyperparameter_selection_uses_independent_test': False,
            'objective_selection_uses_independent_test': False,
            'volatility_scaled_target_uses_future_volatility': False,
            'winsorization_threshold_source': 'training_fold_only',
            'class_and_sample_weight_source': 'training_fold_only',
            'candidate_frozen_before_test': True,
            'classification_independent_test_count': len(report['independent_test_results']['classification']),
            'regression_independent_test_count': len(report['independent_test_results']['regression']),
            'production_api_changed': False, 'production_target_changed': False,
            'production_frontend_changed': False, 'production_quality_gate_lowered': False,
            'development_only_run': bool(options['development_only']),
            'objective_stage_frozen_classification_families': frozen_class_families,
            'objective_stage_frozen_regression_families': frozen_reg_families,
        }
        output = Path(options['output']).resolve()
        output.write_text(json.dumps(report, indent=2, allow_nan=False, default=list), encoding='utf-8')
        self.stdout.write(f'wrote {output}')
        self.stdout.write(
            f'classification_candidate={class_selection["selected_candidate"] or "None"} '
            f'regression_candidate={reg_selection["selected_candidate"] or "None"}'
        )
