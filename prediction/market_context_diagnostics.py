"""Offline Market Context / Cross-Asset feature research.

The production prediction service never imports this module.  Stock labels and
production feature matrices are reused unchanged; SPY/QQQ rows are joined by
the literal market date and every rolling statistic is trailing-only.
"""

from dataclasses import replace
from math import isfinite
from statistics import mean, pstdev

import numpy as np
from scipy.stats import spearmanr
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline

from prediction.feature_service import (
    FEATURE_NAMES,
    REGRESSION_FEATURE_NAMES,
    build_prediction_feature_dataset,
)
from prediction.ml_service import (
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    RANDOM_STATE,
    _classification_metrics,
    _logistic_regression,
    _random_forest_classifier,
    _regression_metrics,
    _regression_model,
    _regression_prediction_diagnostics,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    evaluate_classification_quality_gate,
    evaluate_classifier_walk_forward,
    evaluate_final_classification_quality_gate,
    evaluate_final_regression_quality_gate,
    evaluate_independent_test_quality_gate,
    evaluate_regression_independent_test_quality_gate,
    evaluate_regression_quality_gate,
    majority_class_baseline_accuracy,
    tune_random_forest_classifier,
    tune_regression_models,
)


MARKET_CONTEXT_EXPERIMENTS = {
    'A': 'Current Production Features',
    'B': 'A + SPY Market Context',
    'C': 'A + QQQ Market Context',
    'D': 'A + SPY + QQQ Market Context',
    'E': 'D + Relative Strength / Market-Adjusted Return',
    'F': 'E + Trailing Correlation / Beta',
    'G': 'F + VIX (not run: no stable local VIX security/data contract)',
}


def _benchmark_feature_names(prefix):
    return (
        *(f'{prefix}_return_{period}d' for period in (1, 5, 10, 20, 60)),
        f'{prefix}_close_to_ma20', f'{prefix}_close_to_ma60',
        f'{prefix}_ma20_to_ma60', f'{prefix}_ma20_slope_5d',
        f'{prefix}_ma60_slope_5d',
        *(f'{prefix}_volatility_{period}d' for period in (5, 20, 60)),
    )


ALL_SPY_FEATURES = _benchmark_feature_names('spy')
ALL_QQQ_FEATURES = _benchmark_feature_names('qqq')
ALL_RELATIVE_STRENGTH_FEATURES = tuple(
    f'relative_strength_{benchmark}_{period}d'
    for benchmark in ('spy', 'qqq') for period in (1, 5, 20, 60)
)
ALL_CORRELATION_BETA_FEATURES = tuple(
    name
    for benchmark in ('spy', 'qqq')
    for name in (
        f'correlation_stock_{benchmark}_20d',
        f'correlation_stock_{benchmark}_60d',
        f'beta_stock_{benchmark}_60d',
    )
)


def _classification_market_names(prefix):
    return (
        f'{prefix}_return_1d', f'{prefix}_return_5d',
        f'{prefix}_close_to_ma20', f'{prefix}_close_to_ma60',
        f'{prefix}_ma20_to_ma60',
        f'{prefix}_volatility_5d', f'{prefix}_volatility_20d',
    )


def _regression_market_names(prefix):
    return (
        f'{prefix}_return_20d', f'{prefix}_return_60d',
        f'{prefix}_close_to_ma20', f'{prefix}_close_to_ma60',
        f'{prefix}_ma20_to_ma60', f'{prefix}_ma20_slope_5d',
        f'{prefix}_ma60_slope_5d', f'{prefix}_volatility_20d',
        f'{prefix}_volatility_60d',
    )


CLASSIFICATION_SPY_FEATURES = _classification_market_names('spy')
CLASSIFICATION_QQQ_FEATURES = _classification_market_names('qqq')
REGRESSION_SPY_FEATURES = _regression_market_names('spy')
REGRESSION_QQQ_FEATURES = _regression_market_names('qqq')
CLASSIFICATION_RELATIVE_STRENGTH_FEATURES = tuple(
    f'relative_strength_{benchmark}_{period}d'
    for benchmark in ('spy', 'qqq') for period in (1, 5, 20)
)
REGRESSION_RELATIVE_STRENGTH_FEATURES = tuple(
    f'relative_strength_{benchmark}_{period}d'
    for benchmark in ('spy', 'qqq') for period in (20, 60)
)

CLASSIFICATION_MARKET_FEATURE_SETS = {
    'A': FEATURE_NAMES,
    'B': FEATURE_NAMES + CLASSIFICATION_SPY_FEATURES,
    'C': FEATURE_NAMES + CLASSIFICATION_QQQ_FEATURES,
    'D': FEATURE_NAMES + CLASSIFICATION_SPY_FEATURES + CLASSIFICATION_QQQ_FEATURES,
}
CLASSIFICATION_MARKET_FEATURE_SETS['E'] = (
    CLASSIFICATION_MARKET_FEATURE_SETS['D']
    + CLASSIFICATION_RELATIVE_STRENGTH_FEATURES
)
CLASSIFICATION_MARKET_FEATURE_SETS['F'] = (
    CLASSIFICATION_MARKET_FEATURE_SETS['E'] + ALL_CORRELATION_BETA_FEATURES
)

REGRESSION_MARKET_FEATURE_SETS = {
    'A': REGRESSION_FEATURE_NAMES,
    'B': REGRESSION_FEATURE_NAMES + REGRESSION_SPY_FEATURES,
    'C': REGRESSION_FEATURE_NAMES + REGRESSION_QQQ_FEATURES,
    'D': REGRESSION_FEATURE_NAMES + REGRESSION_SPY_FEATURES + REGRESSION_QQQ_FEATURES,
}
REGRESSION_MARKET_FEATURE_SETS['E'] = (
    REGRESSION_MARKET_FEATURE_SETS['D']
    + REGRESSION_RELATIVE_STRENGTH_FEATURES
)
REGRESSION_MARKET_FEATURE_SETS['F'] = (
    REGRESSION_MARKET_FEATURE_SETS['E'] + ALL_CORRELATION_BETA_FEATURES
)

# Research-only selection gates. Production quality gates remain untouched.
MARKET_CONTEXT_CANDIDATE_RULES = {
    'classification': {
        'minimum_improved_context_count': 4,
        'minimum_improved_symbol_count': 2,
        'minimum_mean_balanced_accuracy_delta': 0.005,
        'minimum_mean_macro_f1_delta': 0.005,
        'minimum_mean_roc_auc_delta': -0.0025,
        'minimum_mean_minimum_recall_delta': 0.0,
        'minimum_mean_baseline_improvement_delta': 0.0,
        'minimum_mean_fold_pass_ratio_delta': 0.0,
        'maximum_mean_train_validation_gap_increase': 0.03,
        'maximum_harmed_context_count': 1,
        'maximum_metric_decline_per_context': 0.03,
    },
    'regression': {
        'minimum_improved_context_count': 4,
        'minimum_improved_symbol_count': 2,
        'minimum_mean_mae_improvement_delta': 0.005,
        'minimum_mean_rmse_improvement_delta': 0.005,
        'minimum_mean_improving_fold_ratio_delta': 0.0,
        'minimum_absolute_mean_mae_improvement': 0.0,
        'minimum_absolute_mean_rmse_improvement': 0.0,
        'maximum_mean_train_validation_gap_increase': 0.01,
        'maximum_harmed_context_count': 1,
        'maximum_error_decline_per_context': 0.03,
    },
}


def _complete(values):
    return all(value is not None and isfinite(float(value)) for value in values)


def _period_return(values, index, period):
    window = values[index - period:index + 1]
    if index < period or len(window) != period + 1 or not _complete(window):
        return None
    return float(values[index] / values[index - period] - 1)


def _moving_average(values, index, period):
    window = values[index - period + 1:index + 1]
    if len(window) != period or not _complete(window):
        return None
    return float(mean(float(value) for value in window))


def _ratio(value, reference):
    if value is None or reference is None or float(reference) == 0:
        return None
    return float(float(value) / float(reference) - 1)


def _daily_returns(values):
    results = [None]
    for previous, current in zip(values, values[1:]):
        results.append(
            float(float(current) / float(previous) - 1)
            if previous is not None and current is not None and float(previous) != 0
            else None
        )
    return tuple(results)


def _rolling_volatility(returns, index, period):
    window = returns[index - period + 1:index + 1]
    if len(window) != period or not _complete(window):
        return None
    return float(np.std(np.asarray(window, dtype=float)))


def _rolling_correlation(stock_returns, benchmark_returns, index, period):
    stock_window = stock_returns[index - period + 1:index + 1]
    benchmark_window = benchmark_returns[index - period + 1:index + 1]
    if (
        len(stock_window) != period or len(benchmark_window) != period
        or not _complete(stock_window) or not _complete(benchmark_window)
    ):
        return None
    stock_array = np.asarray(stock_window, dtype=float)
    benchmark_array = np.asarray(benchmark_window, dtype=float)
    if np.std(stock_array) <= 1e-15 or np.std(benchmark_array) <= 1e-15:
        return None
    return float(np.corrcoef(stock_array, benchmark_array)[0, 1])


def _rolling_beta(stock_returns, benchmark_returns, index, period):
    stock_window = stock_returns[index - period + 1:index + 1]
    benchmark_window = benchmark_returns[index - period + 1:index + 1]
    if (
        len(stock_window) != period or len(benchmark_window) != period
        or not _complete(stock_window) or not _complete(benchmark_window)
    ):
        return None
    stock_array = np.asarray(stock_window, dtype=float)
    benchmark_array = np.asarray(benchmark_window, dtype=float)
    benchmark_variance = float(np.var(benchmark_array))
    if benchmark_variance <= 1e-15:
        return None
    covariance = float(np.mean(
        (stock_array - np.mean(stock_array))
        * (benchmark_array - np.mean(benchmark_array))
    ))
    return float(covariance / benchmark_variance)


def _benchmark_features(prefix, closes, returns, index):
    ma20 = _moving_average(closes, index, 20)
    ma60 = _moving_average(closes, index, 60)
    previous_ma20 = _moving_average(closes, index - 5, 20) if index >= 5 else None
    previous_ma60 = _moving_average(closes, index - 5, 60) if index >= 5 else None
    row = {
        f'{prefix}_close_to_ma20': _ratio(closes[index], ma20),
        f'{prefix}_close_to_ma60': _ratio(closes[index], ma60),
        f'{prefix}_ma20_to_ma60': _ratio(ma20, ma60),
        f'{prefix}_ma20_slope_5d': _ratio(ma20, previous_ma20),
        f'{prefix}_ma60_slope_5d': _ratio(ma60, previous_ma60),
    }
    for period in (1, 5, 10, 20, 60):
        row[f'{prefix}_return_{period}d'] = _period_return(closes, index, period)
    for period in (5, 20, 60):
        row[f'{prefix}_volatility_{period}d'] = _rolling_volatility(
            returns, index, period,
        )
    return row


def build_date_aligned_market_rows(stock_bars, spy_bars, qqq_bars):
    """Join exact dates; a missing benchmark date remains missing, never filled."""
    stock_dates = [bar.date for bar in stock_bars]
    if len(stock_dates) != len(set(stock_dates)):
        raise ValueError('Stock bars contain duplicate dates.')
    spy_by_date = {bar.date: bar for bar in spy_bars}
    qqq_by_date = {bar.date: bar for bar in qqq_bars}
    spy_closes = tuple(
        float(spy_by_date[date].close) if date in spy_by_date else None
        for date in stock_dates
    )
    qqq_closes = tuple(
        float(qqq_by_date[date].close) if date in qqq_by_date else None
        for date in stock_dates
    )
    stock_closes = tuple(float(bar.close) for bar in stock_bars)
    stock_returns = _daily_returns(stock_closes)
    spy_returns = _daily_returns(spy_closes)
    qqq_returns = _daily_returns(qqq_closes)
    rows = []
    for index, date in enumerate(stock_dates):
        row = {'stock_date': date, 'spy_date': date if date in spy_by_date else None,
               'qqq_date': date if date in qqq_by_date else None}
        row.update(_benchmark_features('spy', spy_closes, spy_returns, index))
        row.update(_benchmark_features('qqq', qqq_closes, qqq_returns, index))
        for benchmark, benchmark_closes in (('spy', spy_closes), ('qqq', qqq_closes)):
            for period in (1, 5, 20, 60):
                stock_return = _period_return(stock_closes, index, period)
                benchmark_return = _period_return(benchmark_closes, index, period)
                row[f'relative_strength_{benchmark}_{period}d'] = (
                    float(stock_return - benchmark_return)
                    if stock_return is not None and benchmark_return is not None else None
                )
            benchmark_returns = spy_returns if benchmark == 'spy' else qqq_returns
            row[f'correlation_stock_{benchmark}_20d'] = _rolling_correlation(
                stock_returns, benchmark_returns, index, 20,
            )
            row[f'correlation_stock_{benchmark}_60d'] = _rolling_correlation(
                stock_returns, benchmark_returns, index, 60,
            )
            row[f'beta_stock_{benchmark}_60d'] = _rolling_beta(
                stock_returns, benchmark_returns, index, 60,
            )
        rows.append(row)
    missing_spy = [date.isoformat() for date in stock_dates if date not in spy_by_date]
    missing_qqq = [date.isoformat() for date in stock_dates if date not in qqq_by_date]
    return tuple(rows), {
        'alignment_method': 'exact_stock_trading_date_left_join',
        'missing_policy': (
            'No forward/backward fill. A missing same-date benchmark value makes all '
            'dependent trailing features unavailable; complete-case samples are dropped.'
        ),
        'stock_date_count': len(stock_dates),
        'spy_exact_date_count': len(stock_dates) - len(missing_spy),
        'qqq_exact_date_count': len(stock_dates) - len(missing_qqq),
        'missing_spy_on_stock_dates': missing_spy,
        'missing_qqq_on_stock_dates': missing_qqq,
        'future_fill_used': False,
        'row_index_alignment_used': False,
    }


def build_market_context_experiment_datasets(
    stock_bars, spy_bars, qqq_bars, horizon, task, *, include_independent_test=False,
):
    """Build fixed-boundary Development matrices, and optionally frozen Test.

    The final Test boundary is determined from the stock-only production dataset
    before benchmark availability is inspected.  Consequently, removing or
    changing Test-period benchmark rows cannot move Development folds.
    """
    production = build_prediction_feature_dataset(stock_bars, horizon)
    production_split = build_purged_chronological_split(production)
    market_rows, alignment = build_date_aligned_market_rows(stock_bars, spy_bars, qqq_bars)
    feature_sets = (
        CLASSIFICATION_MARKET_FEATURE_SETS
        if task == 'classification' else REGRESSION_MARKET_FEATURE_SETS
    )
    production_names = FEATURE_NAMES if task == 'classification' else REGRESSION_FEATURE_NAMES
    all_added_names = tuple(dict.fromkeys(
        name for names in feature_sets.values() for name in names
        if name not in production_names
    ))
    positions = {index: position for position, index in enumerate(production.sample_indices)}
    development_production_positions = tuple(range(production_split['development_end']))
    test_production_positions = tuple(range(
        production_split['final_test_start'],
        production_split['final_test_start'] + production_split['test_samples'],
    ))
    development_indices = tuple(
        production.sample_indices[position] for position in development_production_positions
    )
    frozen_test_indices = tuple(
        production.sample_indices[position] for position in test_production_positions
    )
    selected_indices = tuple(
        index for index in development_indices
        if _complete(market_rows[index].get(name) for name in all_added_names)
    )
    selected_positions = tuple(positions[index] for index in selected_indices)
    labels_classification = tuple(production.classification_labels[pos] for pos in selected_positions)
    labels_regression = tuple(production.regression_labels[pos] for pos in selected_positions)
    selected_test_indices = tuple(
        index for index in frozen_test_indices
        if include_independent_test
        and _complete(market_rows[index].get(name) for name in all_added_names)
    )
    selected_test_positions = tuple(positions[index] for index in selected_test_indices)
    datasets = {}
    independent_test_datasets = {}
    for experiment, names in feature_sets.items():
        added_names = tuple(name for name in names if name not in production_names)
        if task == 'classification':
            matrix = tuple(
                tuple(production.features[pos])
                + tuple(float(market_rows[index][name]) for name in added_names)
                for index, pos in zip(selected_indices, selected_positions)
            )
            latest = None
            if production.latest_features is not None and _complete(
                market_rows[-1].get(name) for name in added_names
            ):
                latest = tuple(production.latest_features) + tuple(
                    float(market_rows[-1][name]) for name in added_names
                )
            datasets[experiment] = replace(
                production, feature_names=tuple(names), features=matrix,
                classification_labels=labels_classification,
                regression_labels=labels_regression,
                regression_features=tuple(production.regression_features[pos] for pos in selected_positions),
                sample_indices=selected_indices, latest_features=latest,
                discarded_labeled_rows=len(stock_bars) - horizon - len(selected_indices),
            )
            if include_independent_test:
                test_matrix = tuple(
                    tuple(production.features[pos])
                    + tuple(float(market_rows[index][name]) for name in added_names)
                    for index, pos in zip(selected_test_indices, selected_test_positions)
                )
                independent_test_datasets[experiment] = replace(
                    production, feature_names=tuple(names), features=test_matrix,
                    classification_labels=tuple(
                        production.classification_labels[pos] for pos in selected_test_positions
                    ),
                    regression_labels=tuple(
                        production.regression_labels[pos] for pos in selected_test_positions
                    ),
                    regression_features=tuple(
                        production.regression_features[pos] for pos in selected_test_positions
                    ),
                    sample_indices=selected_test_indices, latest_features=None,
                    discarded_labeled_rows=0,
                )
        else:
            matrix = tuple(
                tuple(production.regression_features[pos])
                + tuple(float(market_rows[index][name]) for name in added_names)
                for index, pos in zip(selected_indices, selected_positions)
            )
            latest = None
            if production.latest_regression_features is not None and _complete(
                market_rows[-1].get(name) for name in added_names
            ):
                latest = tuple(production.latest_regression_features) + tuple(
                    float(market_rows[-1][name]) for name in added_names
                )
            datasets[experiment] = replace(
                production, regression_feature_names=tuple(names), regression_features=matrix,
                classification_labels=labels_classification,
                regression_labels=labels_regression,
                features=tuple(production.features[pos] for pos in selected_positions),
                sample_indices=selected_indices, latest_regression_features=latest,
                discarded_labeled_rows=len(stock_bars) - horizon - len(selected_indices),
            )
            if include_independent_test:
                test_matrix = tuple(
                    tuple(production.regression_features[pos])
                    + tuple(float(market_rows[index][name]) for name in added_names)
                    for index, pos in zip(selected_test_indices, selected_test_positions)
                )
                independent_test_datasets[experiment] = replace(
                    production, regression_feature_names=tuple(names),
                    regression_features=test_matrix,
                    classification_labels=tuple(
                        production.classification_labels[pos] for pos in selected_test_positions
                    ),
                    regression_labels=tuple(
                        production.regression_labels[pos] for pos in selected_test_positions
                    ),
                    features=tuple(production.features[pos] for pos in selected_test_positions),
                    sample_indices=selected_test_indices,
                    latest_regression_features=None, discarded_labeled_rows=0,
                )
    last_development_index = selected_indices[-1] if selected_indices else None
    first_test_index = selected_test_indices[0] if selected_test_indices else (
        frozen_test_indices[0] if frozen_test_indices else None
    )
    return {
        'production_dataset': production, 'datasets': datasets,
        'market_rows': market_rows, 'alignment': alignment,
        'common_sample_indices': selected_indices,
        'common_sample_count': len(selected_indices),
        'common_complete_case_scope': 'all_A_to_F_features',
        'task': task, 'horizon': horizon,
        'independent_test_datasets': independent_test_datasets,
        'independent_test_accessed': bool(include_independent_test),
        'fixed_partition': {
            'source': 'stock_only_production_dataset_before_benchmark_availability',
            'production_development_samples': production_split['development_samples'],
            'production_test_samples': production_split['test_samples'],
            'development_complete_case_samples': len(selected_indices),
            'test_complete_case_samples': len(selected_test_indices)
            if include_independent_test else None,
            'production_development_last_feature_index': (
                development_indices[-1] if development_indices else None
            ),
            'production_test_first_feature_index': (
                frozen_test_indices[0] if frozen_test_indices else None
            ),
            'development_last_feature_index': last_development_index,
            'test_first_feature_index': first_test_index if include_independent_test else None,
            'development_test_purge_safe': (
                last_development_index + horizon < first_test_index
                if last_development_index is not None and first_test_index is not None
                else None
            ),
            'test_benchmark_availability_used_for_development_split': False,
        },
    }


def _importance(model, x, y, task):
    fitted = model.named_steps['model'] if isinstance(model, Pipeline) else model
    if hasattr(fitted, 'coef_'):
        values = np.asarray(fitted.coef_, dtype=float)
        return values[0] if values.ndim > 1 else values, 'standardized_coefficient'
    if hasattr(fitted, 'feature_importances_'):
        return np.asarray(fitted.feature_importances_, dtype=float), 'impurity_importance'
    result = permutation_importance(
        model, x, y, n_repeats=2, random_state=RANDOM_STATE, n_jobs=1,
        scoring='balanced_accuracy' if task == 'classification' else 'neg_mean_absolute_error',
    )
    return np.asarray(result.importances_mean, dtype=float), 'validation_permutation_importance'


def _importance_stability(vectors, names, production_names, kind):
    vectors = np.asarray(vectors, dtype=float)
    absolute = np.abs(vectors)
    normalized = np.divide(
        absolute, absolute.sum(axis=1, keepdims=True),
        out=np.zeros_like(absolute), where=absolute.sum(axis=1, keepdims=True) > 0,
    )
    market_indices = [index for index, name in enumerate(names) if name not in production_names]
    correlations = []
    for left in range(len(vectors)):
        for right in range(left + 1, len(vectors)):
            value = spearmanr(absolute[left], absolute[right]).statistic
            if value is not None and isfinite(float(value)):
                correlations.append(float(value))
    mean_importance = np.mean(normalized, axis=0)
    market_order = sorted(market_indices, key=lambda index: mean_importance[index], reverse=True)
    return {
        'kind': kind,
        'mean_pairwise_rank_correlation': float(mean(correlations)) if correlations else None,
        'mean_market_feature_importance_share': float(np.mean(
            np.sum(normalized[:, market_indices], axis=1)
        )) if market_indices else 0.0,
        'top_market_features': [
            {'feature': names[index], 'mean_normalized_importance': float(mean_importance[index])}
            for index in market_order[:10]
        ],
    }


def _fold_pass(metrics, fold):
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    up = sum(fold['y_classification_train'])
    majority = 1 if up > len(fold['y_classification_train']) / 2 else 0
    baseline = float(mean(label == majority for label in fold['y_classification_validation']))
    passed = (
        metrics['actual_up_count'] > 0 and metrics['actual_down_count'] > 0
        and metrics['predicted_up_count'] > 0 and metrics['predicted_down_count'] > 0
        and metrics['balanced_accuracy'] >= thresholds['minimum_balanced_accuracy']
        and metrics['macro_f1'] >= thresholds['minimum_macro_f1']
        and metrics['accuracy'] - baseline
        >= thresholds['minimum_accuracy_improvement_over_baseline']
    )
    return bool(passed), baseline


def evaluate_classification_market_development(dataset):
    folds = build_purged_walk_forward_folds(
        dataset, {'development_samples': dataset.sample_count},
    )
    if not folds:
        raise ValueError('Insufficient fixed Development samples for classification folds.')
    evaluations = [
        {'model': 'Logistic Regression', 'params': None,
         **evaluate_classifier_walk_forward(_logistic_regression, folds)},
        {'model': 'Random Forest Classifier', **tune_random_forest_classifier(folds)},
    ]
    for evaluation in evaluations:
        evaluation['quality_gate'] = evaluate_classification_quality_gate(
            {**evaluation['metrics'], 'fold_metrics': evaluation['fold_metrics']},
            folds,
        )
    eligible = [evaluation for evaluation in evaluations if evaluation['threshold_eligible']]
    result = max(
        eligible or evaluations,
        key=lambda evaluation: (
            evaluation['selection_score'],
            -evaluation['metrics']['degenerate_fold_count'],
            evaluation['metrics']['mean_macro_f1'],
            evaluation['metrics']['mean_balanced_accuracy'],
            evaluation['metrics']['worst_fold_minimum_class_recall'],
            evaluation['model'] == 'Logistic Regression',
        ),
    )
    result = {
        'scope': 'fixed_development_purged_walk_forward_only',
        'selected_model': result['model'], 'selected_params': result.get('params'),
        'selected_threshold': result['threshold'], 'metrics': result['metrics'],
        'quality_gate': result['quality_gate'], 'folds': folds,
        'fold_metrics': result['fold_metrics'],
        'threshold_stability': result['threshold_stability'],
        'candidate_models': evaluations, 'purge_gap': dataset.horizon,
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
    }
    model_factory = (
        _logistic_regression if result['selected_model'] == 'Logistic Regression'
        else lambda: _random_forest_classifier(result['selected_params'])
    )
    diagnostics, vectors, kind = [], [], None
    for fold, validation_metrics in zip(result['folds'], result['fold_metrics']):
        model = model_factory()
        model.fit(fold['x_train'], fold['y_classification_train'])
        train_probabilities = model.predict_proba(fold['x_train'])[:, list(model.classes_).index(1)]
        train_predictions = (train_probabilities >= result['selected_threshold']).astype(int)
        train_metrics = _classification_metrics(
            fold['y_classification_train'], train_predictions, train_probabilities,
        )
        passed, baseline = _fold_pass(validation_metrics, fold)
        vector, kind = _importance(
            model, fold['x_validation'], fold['y_classification_validation'], 'classification',
        )
        vectors.append(vector)
        diagnostics.append({
            'fold': fold['fold'], 'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'], 'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'], 'train': train_metrics,
            'validation': validation_metrics, 'majority_baseline_accuracy': baseline,
            'baseline_improvement': validation_metrics['accuracy'] - baseline,
            'fold_passed': passed,
        })
    metrics = result['metrics']
    train = {
        key: float(mean(row['train'][key] for row in diagnostics))
        for key in ('accuracy', 'balanced_accuracy', 'macro_f1', 'roc_auc')
    }
    result['train_metrics'] = train
    result['train_validation_gap'] = {
        'balanced_accuracy': train['balanced_accuracy'] - metrics['mean_balanced_accuracy'],
        'macro_f1': train['macro_f1'] - metrics['mean_macro_f1'],
        'roc_auc': train['roc_auc'] - metrics['mean_roc_auc'],
    }
    result['fold_pass_ratio'] = float(mean(row['fold_passed'] for row in diagnostics))
    result['fold_diagnostics'] = diagnostics
    result['feature_importance_stability'] = _importance_stability(
        vectors, dataset.feature_names, FEATURE_NAMES, kind,
    )
    return result


def evaluate_regression_market_development(dataset):
    folds = build_purged_walk_forward_folds(
        dataset, {'development_samples': dataset.sample_count},
    )
    if not folds:
        raise ValueError('Insufficient fixed Development samples for regression folds.')
    tuning = tune_regression_models(folds)
    selected = tuning['selected']
    result = {
        'scope': 'fixed_development_purged_walk_forward_only',
        'selected_model': selected['model'], 'selected_family': selected['family'],
        'selected_params': selected['params'], 'metrics': selected,
        'quality_gate': selected['quality_gate'], 'folds': folds,
        'candidate_models': tuning['candidates'], 'purge_gap': dataset.horizon,
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
    }
    candidate = {'model': result['selected_model'], 'family': result['selected_family'],
                 'params': result['selected_params']}
    diagnostics, vectors, kind = [], [], None
    for fold, validation_metrics in zip(result['folds'], result['metrics']['folds']):
        model = _regression_model(candidate)
        model.fit(fold['x_regression_train'], fold['y_regression_train'])
        predictions = np.asarray(model.predict(fold['x_regression_train']), dtype=float)
        train_metrics = _regression_metrics(fold['y_regression_train'], predictions)
        vector, kind = _importance(
            model, fold['x_regression_validation'], fold['y_regression_validation'], 'regression',
        )
        vectors.append(vector)
        diagnostics.append({
            'fold': fold['fold'], 'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'], 'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'], 'train': train_metrics,
            'validation': validation_metrics,
        })
    validation = result['metrics']['model_metrics']
    train = {key: float(mean(row['train'][key] for row in diagnostics))
             for key in ('mae', 'rmse', 'r2')}
    result['train_metrics'] = train
    result['train_validation_gap'] = {
        'mae': validation['mae'] - train['mae'],
        'rmse': validation['rmse'] - train['rmse'],
        'r2': train['r2'] - validation['r2'],
    }
    result['fold_diagnostics'] = diagnostics
    result['feature_importance_stability'] = _importance_stability(
        vectors, dataset.regression_feature_names, REGRESSION_FEATURE_NAMES, kind,
    )
    return result


def classification_summary(result):
    metrics, gate = result['metrics'], result['quality_gate']
    return {
        'accuracy': metrics['accuracy'],
        'balanced_accuracy': metrics['mean_balanced_accuracy'],
        'macro_f1': metrics['mean_macro_f1'], 'roc_auc': metrics['mean_roc_auc'],
        'minimum_class_recall': metrics['mean_minimum_class_recall'],
        'majority_baseline_accuracy': gate['observed']['baseline_accuracy'],
        'baseline_improvement': gate['observed']['accuracy_improvement_over_baseline'],
        'fold_pass_ratio': result['fold_pass_ratio'],
        'macro_f1_std': metrics['std_macro_f1'],
        'train_validation_gap': result['train_validation_gap']['macro_f1'],
        'fold_metrics': result['fold_metrics'],
    }


def regression_summary(result):
    metrics = result['metrics']
    return {
        'mae': metrics['model_metrics']['mae'], 'rmse': metrics['model_metrics']['rmse'],
        'r2': metrics['model_metrics']['r2'],
        'zero_return_baseline_mae': metrics['zero_return_baseline']['mae'],
        'zero_return_baseline_rmse': metrics['zero_return_baseline']['rmse'],
        'mae_improvement': metrics['mae_improvement_over_zero'],
        'rmse_improvement': metrics['rmse_improvement_over_zero'],
        'improving_fold_count': metrics['improving_fold_count'],
        'improving_fold_ratio': metrics['improving_fold_ratio'],
        'fold_mae_std': metrics['fold_mae_std'],
        'train_validation_gap': result['train_validation_gap']['mae'],
        'fold_metrics': metrics['folds'],
    }


def aggregate_market_context_results(results, task):
    aggregates = []
    for experiment in ('A', 'B', 'C', 'D', 'E', 'F'):
        rows = [row['summary'] for row in results if row['experiment'] == experiment]
        if task == 'classification':
            aggregates.append({
                'experiment': experiment, 'label': MARKET_CONTEXT_EXPERIMENTS[experiment],
                'context_count': len(rows),
                **{f'mean_{key}': float(mean(row[key] for row in rows)) for key in (
                    'accuracy', 'balanced_accuracy', 'macro_f1', 'roc_auc',
                    'minimum_class_recall', 'majority_baseline_accuracy',
                    'baseline_improvement', 'fold_pass_ratio', 'train_validation_gap',
                )},
                'between_context_macro_f1_std': float(pstdev(row['macro_f1'] for row in rows)),
            })
        else:
            aggregates.append({
                'experiment': experiment, 'label': MARKET_CONTEXT_EXPERIMENTS[experiment],
                'context_count': len(rows),
                **{f'mean_{key}': float(mean(row[key] for row in rows)) for key in (
                    'mae', 'rmse', 'r2', 'zero_return_baseline_mae',
                    'zero_return_baseline_rmse', 'mae_improvement', 'rmse_improvement',
                    'improving_fold_ratio', 'train_validation_gap',
                )},
            })
    return aggregates


def select_market_context_candidate(results, task):
    if any(row.get('independent_test_accessed') is True or 'independent_test' in row for row in results):
        raise ValueError('Independent Test data cannot enter Market Context selection.')
    rules = MARKET_CONTEXT_CANDIDATE_RULES[task]
    keys = [(row['experiment'], row['symbol'], row['lookback']) for row in results]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate experiment/context rows are not allowed.')
    baselines = {(row['symbol'], row['lookback']): row for row in results if row['experiment'] == 'A'}
    contexts = {(row['symbol'], row['lookback']) for row in results}
    if set(baselines) != contexts:
        raise ValueError('Every context requires Experiment A.')
    for experiment in ('B', 'C', 'D', 'E', 'F'):
        experiment_contexts = {
            (row['symbol'], row['lookback'])
            for row in results if row['experiment'] == experiment
        }
        if experiment_contexts != contexts:
            raise ValueError(f'Experiment {experiment} does not cover identical contexts.')
    for row in results:
        baseline = baselines[(row['symbol'], row['lookback'])]
        if row['experiment'] == 'A':
            continue
        baseline_folds = baseline['result']['folds']
        candidate_folds = row['result']['folds']
        baseline_signature = tuple(
            (fold['fold'], fold['training_samples'], fold['validation_samples'],
             fold['gap_size'], fold['boundaries']['validation_first_feature_index'],
             fold['boundaries']['validation_last_feature_index'])
            for fold in baseline_folds
        )
        candidate_signature = tuple(
            (fold['fold'], fold['training_samples'], fold['validation_samples'],
             fold['gap_size'], fold['boundaries']['validation_first_feature_index'],
             fold['boundaries']['validation_last_feature_index'])
            for fold in candidate_folds
        )
        if candidate_signature != baseline_signature:
            raise ValueError('A-F must use identical Walk-Forward fold boundaries.')
    candidates = []
    for experiment in ('B', 'C', 'D', 'E', 'F'):
        comparisons = []
        for row in (item for item in results if item['experiment'] == experiment):
            baseline = baselines[(row['symbol'], row['lookback'])]['summary']
            current = row['summary']
            if task == 'classification':
                keys = ('balanced_accuracy', 'macro_f1', 'roc_auc', 'minimum_class_recall',
                        'baseline_improvement', 'fold_pass_ratio', 'train_validation_gap')
                deltas = {key: float(current[key] - baseline[key]) for key in keys}
                fold_improved = [
                    candidate['balanced_accuracy'] > reference['balanced_accuracy']
                    and candidate['macro_f1'] > reference['macro_f1']
                    and candidate['roc_auc'] is not None and reference['roc_auc'] is not None
                    and candidate['roc_auc'] >= reference['roc_auc']
                    for candidate, reference in zip(current['fold_metrics'], baseline['fold_metrics'])
                ]
                harmed = any(deltas[key] < -rules['maximum_metric_decline_per_context']
                             for key in ('balanced_accuracy', 'macro_f1', 'roc_auc'))
                improved = (not harmed and deltas['balanced_accuracy'] > 0
                            and deltas['macro_f1'] > 0 and deltas['roc_auc'] >= 0
                            and deltas['minimum_class_recall'] >= 0
                            and deltas['baseline_improvement'] >= 0)
            else:
                keys = ('mae_improvement', 'rmse_improvement', 'improving_fold_ratio',
                        'r2', 'fold_mae_std', 'train_validation_gap')
                deltas = {key: float(current[key] - baseline[key]) for key in keys}
                fold_improved = [
                    candidate['mae_improvement_over_zero'] > reference['mae_improvement_over_zero']
                    and candidate['rmse_improvement_over_zero'] > reference['rmse_improvement_over_zero']
                    for candidate, reference in zip(current['fold_metrics'], baseline['fold_metrics'])
                ]
                harmed = any(deltas[key] < -rules['maximum_error_decline_per_context']
                             for key in ('mae_improvement', 'rmse_improvement'))
                improved = (not harmed and deltas['mae_improvement'] > 0
                            and deltas['rmse_improvement'] > 0
                            and deltas['improving_fold_ratio'] >= 0)
            comparisons.append({
                'symbol': row['symbol'], 'lookback': row['lookback'], 'deltas': deltas,
                'fold_improved_ratio': float(mean(fold_improved)),
                'context_improved': bool(improved), 'context_harmed': bool(harmed),
                'candidate_absolute': {
                    key: value for key, value in current.items()
                    if key != 'fold_metrics'
                },
            })
        mean_deltas = {key: float(mean(item['deltas'][key] for item in comparisons))
                       for key in comparisons[0]['deltas']}
        improved = [item for item in comparisons if item['context_improved']]
        harmed_count = sum(item['context_harmed'] for item in comparisons)
        if task == 'classification':
            checks = {
                'contexts': len(improved) >= rules['minimum_improved_context_count'],
                'symbols': len({item['symbol'] for item in improved}) >= rules['minimum_improved_symbol_count'],
                'balanced_accuracy': mean_deltas['balanced_accuracy'] >= rules['minimum_mean_balanced_accuracy_delta'],
                'macro_f1': mean_deltas['macro_f1'] >= rules['minimum_mean_macro_f1_delta'],
                'roc_auc': mean_deltas['roc_auc'] >= rules['minimum_mean_roc_auc_delta'],
                'minimum_recall': mean_deltas['minimum_class_recall'] >= rules['minimum_mean_minimum_recall_delta'],
                'baseline': mean_deltas['baseline_improvement'] >= rules['minimum_mean_baseline_improvement_delta'],
                'fold_pass': mean_deltas['fold_pass_ratio'] >= rules['minimum_mean_fold_pass_ratio_delta'],
                'gap': mean_deltas['train_validation_gap'] <= rules['maximum_mean_train_validation_gap_increase'],
                'limited_harm': harmed_count <= rules['maximum_harmed_context_count'],
            }
            score = (mean_deltas['balanced_accuracy'] * 0.25 + mean_deltas['macro_f1'] * 0.25
                     + mean_deltas['roc_auc'] * 0.20 + mean_deltas['minimum_class_recall'] * 0.10
                     + mean_deltas['baseline_improvement'] * 0.10
                     + mean_deltas['fold_pass_ratio'] * 0.10
                     - max(mean_deltas['train_validation_gap'], 0) * 0.10)
        else:
            absolute_mae = float(mean(item['candidate_absolute']['mae_improvement'] for item in comparisons))
            absolute_rmse = float(mean(item['candidate_absolute']['rmse_improvement'] for item in comparisons))
            checks = {
                'contexts': len(improved) >= rules['minimum_improved_context_count'],
                'symbols': len({item['symbol'] for item in improved}) >= rules['minimum_improved_symbol_count'],
                'mae_delta': mean_deltas['mae_improvement'] >= rules['minimum_mean_mae_improvement_delta'],
                'rmse_delta': mean_deltas['rmse_improvement'] >= rules['minimum_mean_rmse_improvement_delta'],
                'fold_ratio': mean_deltas['improving_fold_ratio'] >= rules['minimum_mean_improving_fold_ratio_delta'],
                'absolute_mae': absolute_mae >= rules['minimum_absolute_mean_mae_improvement'],
                'absolute_rmse': absolute_rmse >= rules['minimum_absolute_mean_rmse_improvement'],
                'gap': mean_deltas['train_validation_gap'] <= rules['maximum_mean_train_validation_gap_increase'],
                'limited_harm': harmed_count <= rules['maximum_harmed_context_count'],
            }
            score = (mean_deltas['mae_improvement'] * 0.40 + mean_deltas['rmse_improvement'] * 0.35
                     + mean_deltas['improving_fold_ratio'] * 0.20
                     - max(mean_deltas['train_validation_gap'], 0) * 0.05)
        candidates.append({
            'experiment': experiment, 'label': MARKET_CONTEXT_EXPERIMENTS[experiment],
            'eligible': all(checks.values()), 'checks': checks,
            'mean_deltas_vs_A': mean_deltas,
            'improved_context_count': len(improved),
            'improved_symbols': sorted({item['symbol'] for item in improved}),
            'harmed_context_count': int(harmed_count),
            'development_only_score': float(score), 'contexts': comparisons,
        })
    eligible = [candidate for candidate in candidates if candidate['eligible']]
    selected = max(eligible, key=lambda item: (item['development_only_score'], -ord(item['experiment']))) if eligible else None
    return {
        'task': task, 'selected_experiment': selected['experiment'] if selected else None,
        'selected_candidate': selected, 'candidates': candidates, 'rules': rules,
        'selection_source': 'development_purged_walk_forward_only',
        'independent_test_used': False,
    }


def evaluate_classification_independent_test(
    development_dataset, independent_test_dataset, development_result,
):
    """Evaluate exactly one frozen candidate on its untouched fixed Test rows."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a Development-only frozen classification result.')
    model = (
        _logistic_regression()
        if development_result['selected_model'] == 'Logistic Regression'
        else _random_forest_classifier(development_result['selected_params'])
    )
    model.fit(development_dataset.features, development_dataset.classification_labels)
    probabilities = model.predict_proba(independent_test_dataset.features)[
        :, list(model.classes_).index(1)
    ]
    predictions = (
        np.asarray(probabilities, dtype=float)
        >= float(development_result['selected_threshold'])
    ).astype(int)
    metrics = _classification_metrics(
        independent_test_dataset.classification_labels, predictions, probabilities,
    )
    baseline = majority_class_baseline_accuracy(
        independent_test_dataset.classification_labels,
    )
    test_gate = evaluate_independent_test_quality_gate(metrics)
    final_gate = evaluate_final_classification_quality_gate(
        development_result['quality_gate'], test_gate,
    )
    return {
        'scope': 'final_untouched_fixed_independent_test',
        'metrics': {
            **metrics, 'majority_baseline_accuracy': baseline,
            'accuracy_improvement_over_baseline': metrics['accuracy'] - baseline,
        },
        'quality_gate': test_gate, 'final_quality_gate': final_gate,
        'test_used_for_model_selection': False,
        'test_used_for_threshold_selection': False,
        'test_used_for_feature_selection': False,
        'model_refit_after_test': False, 'test_evaluation_count': 1,
        'purge_gap': development_dataset.horizon,
        'development_test_purge_safe': (
            development_dataset.sample_indices[-1] + development_dataset.horizon
            < independent_test_dataset.sample_indices[0]
        ),
    }


def evaluate_regression_independent_test(
    development_dataset, independent_test_dataset, development_result,
):
    """Evaluate exactly one frozen regression candidate on fixed Test rows."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a Development-only frozen regression result.')
    candidate = {
        'model': development_result['selected_model'],
        'family': development_result['selected_family'],
        'params': development_result['selected_params'],
    }
    model = _regression_model(candidate)
    model.fit(
        development_dataset.regression_features,
        development_dataset.regression_labels,
    )
    labels = np.asarray(independent_test_dataset.regression_labels, dtype=float)
    predictions = np.asarray(
        model.predict(independent_test_dataset.regression_features), dtype=float,
    )
    zero_predictions = np.zeros(len(labels), dtype=float)
    development_mean = float(mean(development_dataset.regression_labels))
    mean_predictions = np.full(len(labels), development_mean, dtype=float)
    test_evaluation = {
        'source': 'independent_test', 'sample_count': len(labels),
        'model_metrics': _regression_metrics(labels, predictions),
        'zero_return_baseline': {
            'name': 'zero_future_return',
            **_regression_metrics(labels, zero_predictions),
        },
        'historical_training_mean_baseline': {
            'name': 'development_training_mean_future_return',
            'training_mean_return': development_mean,
            **_regression_metrics(labels, mean_predictions),
        },
        'prediction_diagnostics': _regression_prediction_diagnostics(
            labels, predictions,
        ),
    }
    test_gate = evaluate_regression_independent_test_quality_gate(test_evaluation)
    final_gate = evaluate_final_regression_quality_gate(
        development_result['quality_gate'], test_gate,
    )
    return {
        'scope': 'final_untouched_fixed_independent_test',
        'metrics': test_evaluation, 'quality_gate': test_gate,
        'final_quality_gate': final_gate,
        'test_used_for_model_selection': False,
        'test_used_for_feature_selection': False,
        'model_refit_after_test': False, 'test_evaluation_count': 1,
        'purge_gap': development_dataset.horizon,
        'development_test_purge_safe': (
            development_dataset.sample_indices[-1] + development_dataset.horizon
            < independent_test_dataset.sample_indices[0]
        ),
    }


__all__ = [
    'MARKET_CONTEXT_EXPERIMENTS', 'CLASSIFICATION_MARKET_FEATURE_SETS',
    'REGRESSION_MARKET_FEATURE_SETS', 'ALL_SPY_FEATURES', 'ALL_QQQ_FEATURES',
    'ALL_RELATIVE_STRENGTH_FEATURES', 'ALL_CORRELATION_BETA_FEATURES',
    'build_date_aligned_market_rows', 'build_market_context_experiment_datasets',
    'evaluate_classification_market_development', 'evaluate_regression_market_development',
    'classification_summary', 'regression_summary', 'aggregate_market_context_results',
    'select_market_context_candidate', 'evaluate_classification_independent_test',
    'evaluate_regression_independent_test',
]
