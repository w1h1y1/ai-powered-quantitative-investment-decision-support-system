"""Offline regime-shift and regime-normalized feature research.

Nothing in this module is imported by the production prediction service.  The
module reuses production targets, models, purged Walk-Forward definitions, and
quality gates while keeping A-E feature selection strictly pre-Test.
"""

from dataclasses import replace
from math import isfinite, sqrt
from statistics import mean, pstdev

import numpy as np
from scipy.stats import ks_2samp, wasserstein_distance

from prediction.feature_diagnostics import _rich_feature_rows
from prediction.feature_service import (
    FEATURE_NAMES,
    REGRESSION_FEATURE_NAMES,
    build_prediction_feature_dataset,
)
from prediction.ml_service import (
    _classification_metrics,
    _logistic_regression,
    _predictions_for_threshold,
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


REGIME_EXPERIMENT_LABELS = {
    'A': 'Current Production Features',
    'B': 'Current + Rolling Normalization',
    'C': 'B + Volatility Regime',
    'D': 'B + Trend Regime',
    'E': 'B + Volatility + Trend Regimes + Interactions',
}

# These thresholds are predeclared research rules applied to trailing-only
# percentiles. They are never fitted or adjusted using the independent Test.
VOLATILITY_REGIME_THRESHOLDS = {
    'low_upper_exclusive': 0.30,
    'high_lower_exclusive': 0.70,
    'source': 'predeclared_development_research_rule',
}
TREND_REGIME_THRESHOLDS = {
    'bull_minimum_positive_signals': 4,
    'bear_maximum_positive_signals': 1,
    'signal_count': 5,
    'source': 'predeclared_development_research_rule',
}

CLASSIFICATION_NORMALIZED_FEATURES = (
    'return_1d_z20',
    'return_5d_z60',
    'atr_ratio_z60',
    'volume_ratio_z60',
    'ma20_distance_z60',
    'momentum_20d_z60',
    'volatility_percentile_60d',
    'atr_percentile_60d',
    'volume_percentile_60d',
    'rsi_percentile_60d',
    'momentum_5d_percentile_60d',
    'macd_histogram_change_z60',
    'gap_atr_normalized',
    'intraday_range_atr_normalized',
)
REGRESSION_NORMALIZED_FEATURES = (
    'return_5d_z60',
    'momentum_20d_z60',
    'momentum_60d_z60',
    'atr_ratio_z60',
    'volume_ratio_z60',
    'ma20_distance_z60',
    'ma20_ma60_z60',
    'volatility_percentile_60d',
    'atr_percentile_60d',
    'volume_percentile_60d',
    'rsi_percentile_60d',
    'momentum_20d_percentile_60d',
    'distance_high20_vol_normalized',
)
VOLATILITY_REGIME_FEATURES = ('vol_regime_low', 'vol_regime_high')
TREND_REGIME_FEATURES = ('trend_regime_bull', 'trend_regime_bear')
CLASSIFICATION_INTERACTION_FEATURES = (
    'momentum_5d_per_volatility',
    'momentum_20d_per_volatility',
    'macd_histogram_change_per_volatility',
)
REGRESSION_INTERACTION_FEATURES = (
    'momentum_20d_per_volatility',
    'momentum_60d_per_volatility',
    'ma20_ma60_per_volatility',
    'distance_high20_vol_normalized',
)

CLASSIFICATION_REGIME_FEATURE_SETS = {
    'A': FEATURE_NAMES,
    'B': FEATURE_NAMES + CLASSIFICATION_NORMALIZED_FEATURES,
}
CLASSIFICATION_REGIME_FEATURE_SETS['C'] = (
    CLASSIFICATION_REGIME_FEATURE_SETS['B'] + VOLATILITY_REGIME_FEATURES
)
CLASSIFICATION_REGIME_FEATURE_SETS['D'] = (
    CLASSIFICATION_REGIME_FEATURE_SETS['B'] + TREND_REGIME_FEATURES
)
CLASSIFICATION_REGIME_FEATURE_SETS['E'] = tuple(dict.fromkeys(
    CLASSIFICATION_REGIME_FEATURE_SETS['B']
    + VOLATILITY_REGIME_FEATURES
    + TREND_REGIME_FEATURES
    + CLASSIFICATION_INTERACTION_FEATURES
))

REGRESSION_REGIME_FEATURE_SETS = {
    'A': REGRESSION_FEATURE_NAMES,
    'B': REGRESSION_FEATURE_NAMES + REGRESSION_NORMALIZED_FEATURES,
}
REGRESSION_REGIME_FEATURE_SETS['C'] = (
    REGRESSION_REGIME_FEATURE_SETS['B'] + VOLATILITY_REGIME_FEATURES
)
REGRESSION_REGIME_FEATURE_SETS['D'] = (
    REGRESSION_REGIME_FEATURE_SETS['B'] + TREND_REGIME_FEATURES
)
REGRESSION_REGIME_FEATURE_SETS['E'] = tuple(dict.fromkeys(
    REGRESSION_REGIME_FEATURE_SETS['B']
    + VOLATILITY_REGIME_FEATURES
    + TREND_REGIME_FEATURES
    + REGRESSION_INTERACTION_FEATURES
))

DRIFT_FEATURES = (
    'return_1d', 'return_5d', 'return_10d', 'return_20d',
    'volatility_5d', 'volatility_10d', 'volatility_20d', 'volatility_60d',
    'atr_close_ratio',
    'close_ma20_distance', 'close_ma60_distance', 'ma20_ma60_distance',
    'ma20_slope_5d', 'ma60_slope_5d',
    'momentum_5d', 'momentum_20d', 'momentum_60d',
    'volume_ma20_ratio', 'volume_ma60_ratio',
    'rsi', 'macd_histogram_close_ratio', 'macd_histogram_change_close_ratio',
)

# Research-only cross-context gates. They do not alter production quality gates.
REGIME_CANDIDATE_RULES = {
    'classification': {
        'minimum_improved_context_count': 4,
        'minimum_improved_symbol_count': 2,
        'minimum_mean_balanced_accuracy_delta': 0.005,
        'minimum_mean_macro_f1_delta': 0.005,
        'minimum_mean_roc_auc_delta': 0.0025,
        'minimum_mean_minimum_recall_delta': 0.0,
        'minimum_mean_baseline_improvement_delta': 0.0,
        'minimum_improved_fold_ratio': 0.55,
        'maximum_harmed_context_count': 1,
        'maximum_metric_decline_per_context': 0.03,
        'maximum_macro_f1_std_increase': 0.02,
    },
    'regression': {
        'minimum_improved_context_count': 4,
        'minimum_improved_symbol_count': 2,
        'minimum_mean_mae_improvement_delta': 0.005,
        'minimum_mean_rmse_improvement_delta': 0.005,
        'minimum_mean_improving_fold_ratio_delta': 0.0,
        'minimum_improved_fold_ratio': 0.55,
        'maximum_harmed_context_count': 1,
        'maximum_error_improvement_decline_per_context': 0.03,
        'maximum_fold_mae_std_increase': 0.002,
    },
}


def _safe_ratio(numerator, denominator):
    if numerator is None or denominator is None or abs(float(denominator)) <= 1e-15:
        return None
    return float(numerator) / float(denominator)


def trailing_zscore(values, index, window):
    """Calculate a z-score using exactly [t-window+1, t], never future rows."""
    if index < window - 1 or values[index] is None:
        return None
    trailing = values[index - window + 1:index + 1]
    if len(trailing) != window or any(value is None for value in trailing):
        return None
    trailing = np.asarray(trailing, dtype=float)
    standard_deviation = float(np.std(trailing))
    if standard_deviation <= 1e-15:
        return 0.0
    return float((float(values[index]) - float(np.mean(trailing))) / standard_deviation)


def trailing_percentile(values, index, window):
    """Empirical trailing percentile using only values at or before index t."""
    if index < window - 1 or values[index] is None:
        return None
    trailing = values[index - window + 1:index + 1]
    if len(trailing) != window or any(value is None for value in trailing):
        return None
    current = float(values[index])
    return float(sum(float(value) <= current for value in trailing) / window)


def volatility_regime(percentile):
    if percentile is None:
        return None
    if percentile < VOLATILITY_REGIME_THRESHOLDS['low_upper_exclusive']:
        return 'LOW_VOL'
    if percentile > VOLATILITY_REGIME_THRESHOLDS['high_lower_exclusive']:
        return 'HIGH_VOL'
    return 'NORMAL_VOL'


def trend_regime(row):
    names = (
        'price_ma20_ratio', 'price_ma60_ratio', 'ma20_ma60_ratio',
        'ma20_slope_5', 'ma60_slope_5',
    )
    if any(row.get(name) is None for name in names):
        return None
    positive_signals = sum(float(row[name]) > 0 for name in names)
    if positive_signals >= TREND_REGIME_THRESHOLDS['bull_minimum_positive_signals']:
        return 'BULL_TREND'
    if positive_signals <= TREND_REGIME_THRESHOLDS['bear_maximum_positive_signals']:
        return 'BEAR_TREND'
    return 'NEUTRAL_RANGE'


def build_regime_feature_rows(bars, horizon):
    """Build raw and normalized feature rows using point-in-time information only."""
    production = build_prediction_feature_dataset(bars, horizon)
    rich_rows = [dict(row) for row in _rich_feature_rows(bars, production)]
    raw_series = {
        'return_1d': [row.get('return_1') for row in rich_rows],
        'return_5d': [row.get('return_5') for row in rich_rows],
        'return_10d': [row.get('return_10') for row in rich_rows],
        'return_20d': [row.get('return_20') for row in rich_rows],
        'momentum_60d': [row.get('return_60') for row in rich_rows],
        'atr_ratio': [row.get('atr_price_ratio') for row in rich_rows],
        'volume_ratio': [
            row['volume_average_20_ratio'] + 1
            if row.get('volume_average_20_ratio') is not None else None
            for row in rich_rows
        ],
        'ma20_distance': [row.get('price_ma20_ratio') for row in rich_rows],
        'ma20_ma60': [row.get('ma20_ma60_ratio') for row in rich_rows],
        'volatility_20': [
            row['volatility_20'] / sqrt(252)
            if row.get('volatility_20') is not None else None
            for row in rich_rows
        ],
        'rsi': [row.get('rsi') for row in rich_rows],
        'macd_histogram_change': [
            row.get('macd_histogram_change_1') for row in rich_rows
        ],
    }
    for index, row in enumerate(rich_rows):
        volatility_20 = raw_series['volatility_20'][index]
        atr_ratio = raw_series['atr_ratio'][index]
        volume_ratio = raw_series['volume_ratio'][index]
        return_5 = raw_series['return_5d'][index]
        return_20 = raw_series['return_20d'][index]
        return_60 = raw_series['momentum_60d'][index]
        price_ma20 = row.get('price_ma20_ratio')
        ma20_ma60 = row.get('ma20_ma60_ratio')
        gap_return = row.get('gap_return')
        intraday_range = row.get('intraday_range')
        distance_high = row.get('distance_to_20_day_high')
        macd_change = row.get('macd_histogram_change_1')
        row.update({
            'return_1d_z20': trailing_zscore(raw_series['return_1d'], index, 20),
            'return_5d_z60': trailing_zscore(raw_series['return_5d'], index, 60),
            'atr_ratio_z60': trailing_zscore(raw_series['atr_ratio'], index, 60),
            'volume_ratio_z60': trailing_zscore(raw_series['volume_ratio'], index, 60),
            'ma20_distance_z60': trailing_zscore(raw_series['ma20_distance'], index, 60),
            'ma20_ma60_z60': trailing_zscore(raw_series['ma20_ma60'], index, 60),
            'momentum_20d_z60': trailing_zscore(raw_series['return_20d'], index, 60),
            'momentum_60d_z60': trailing_zscore(raw_series['momentum_60d'], index, 60),
            'volatility_percentile_60d': trailing_percentile(
                raw_series['volatility_20'], index, 60,
            ),
            'atr_percentile_60d': trailing_percentile(raw_series['atr_ratio'], index, 60),
            'volume_percentile_60d': trailing_percentile(
                raw_series['volume_ratio'], index, 60,
            ),
            'rsi_percentile_60d': trailing_percentile(raw_series['rsi'], index, 60),
            'momentum_5d_percentile_60d': trailing_percentile(
                raw_series['return_5d'], index, 60,
            ),
            'momentum_20d_percentile_60d': trailing_percentile(
                raw_series['return_20d'], index, 60,
            ),
            'macd_histogram_change_z60': trailing_zscore(
                raw_series['macd_histogram_change'], index, 60,
            ),
            'gap_atr_normalized': _safe_ratio(gap_return, atr_ratio),
            'intraday_range_atr_normalized': _safe_ratio(intraday_range, atr_ratio),
            'distance_high20_vol_normalized': _safe_ratio(distance_high, volatility_20),
            'momentum_5d_per_volatility': _safe_ratio(return_5, volatility_20),
            'momentum_20d_per_volatility': _safe_ratio(return_20, volatility_20),
            'momentum_60d_per_volatility': _safe_ratio(return_60, volatility_20),
            'ma20_ma60_per_volatility': _safe_ratio(ma20_ma60, volatility_20),
            'macd_histogram_change_per_volatility': _safe_ratio(
                macd_change, volatility_20,
            ),
        })
        vol_state = volatility_regime(row['volatility_percentile_60d'])
        trend_state = trend_regime(row)
        row.update({
            'volatility_regime': vol_state,
            'trend_regime': trend_state,
            'vol_regime_low': float(vol_state == 'LOW_VOL') if vol_state else None,
            'vol_regime_high': float(vol_state == 'HIGH_VOL') if vol_state else None,
            'trend_regime_bull': float(trend_state == 'BULL_TREND') if trend_state else None,
            'trend_regime_bear': float(trend_state == 'BEAR_TREND') if trend_state else None,
        })
        row.update({
            'return_1d': row.get('return_1'),
            'return_5d': row.get('return_5'),
            'return_10d': row.get('return_10'),
            'return_20d': row.get('return_20'),
            'volatility_5d': row.get('volatility_5'),
            'volatility_10d': row.get('volatility_10'),
            'volatility_20d': volatility_20,
            'volatility_60d': row.get('volatility_60'),
            'atr_close_ratio': atr_ratio,
            'close_ma20_distance': price_ma20,
            'close_ma60_distance': row.get('price_ma60_ratio'),
            'ma20_ma60_distance': ma20_ma60,
            'ma20_slope_5d': row.get('ma20_slope_5'),
            'ma60_slope_5d': row.get('ma60_slope_5'),
            'momentum_5d': return_5,
            'momentum_20d': return_20,
            'momentum_60d': return_60,
            'volume_ma20_ratio': volume_ratio,
            'volume_ma60_ratio': (
                row['volume_average_60_ratio'] + 1
                if row.get('volume_average_60_ratio') is not None else None
            ),
            'macd_histogram_close_ratio': row.get('macd_histogram_price_ratio'),
            'macd_histogram_change_close_ratio': macd_change,
        })
    return production, tuple(rich_rows)


def _complete(values):
    return all(value is not None and isfinite(float(value)) for value in values)


def experiment_feature_names(task, experiment):
    sets = (
        CLASSIFICATION_REGIME_FEATURE_SETS
        if task == 'classification'
        else REGRESSION_REGIME_FEATURE_SETS
    )
    return tuple(sets[experiment])


def build_regime_experiment_datasets(bars, horizon, task):
    """Return A-E datasets on one identical complete-case sample universe."""
    production, rows = build_regime_feature_rows(bars, horizon)
    feature_sets = (
        CLASSIFICATION_REGIME_FEATURE_SETS
        if task == 'classification'
        else REGRESSION_REGIME_FEATURE_SETS
    )
    all_names = tuple(dict.fromkeys(
        name for names in feature_sets.values() for name in names
    ))
    production_positions = {
        sample_index: position
        for position, sample_index in enumerate(production.sample_indices)
    }
    selected_indices = tuple(
        sample_index
        for sample_index in production.sample_indices
        if _complete(rows[sample_index].get(name) for name in all_names)
    )
    selected_positions = tuple(production_positions[index] for index in selected_indices)
    classification_labels = tuple(
        production.classification_labels[position] for position in selected_positions
    )
    regression_labels = tuple(
        production.regression_labels[position] for position in selected_positions
    )
    datasets = {}
    for experiment, names in feature_sets.items():
        matrix = tuple(
            tuple(float(rows[index][name]) for name in names)
            for index in selected_indices
        )
        if task == 'classification':
            datasets[experiment] = replace(
                production,
                feature_names=tuple(names),
                features=matrix,
                classification_labels=classification_labels,
                regression_labels=regression_labels,
                regression_features=tuple(
                    production.regression_features[position]
                    for position in selected_positions
                ),
                sample_indices=selected_indices,
                latest_features=(
                    tuple(float(rows[-1][name]) for name in names)
                    if _complete(rows[-1].get(name) for name in names) else None
                ),
                discarded_labeled_rows=len(bars) - horizon - len(selected_indices),
            )
        else:
            datasets[experiment] = replace(
                production,
                regression_feature_names=tuple(names),
                regression_features=matrix,
                classification_labels=classification_labels,
                regression_labels=regression_labels,
                features=tuple(
                    production.features[position] for position in selected_positions
                ),
                sample_indices=selected_indices,
                latest_regression_features=(
                    tuple(float(rows[-1][name]) for name in names)
                    if _complete(rows[-1].get(name) for name in names) else None
                ),
                discarded_labeled_rows=len(bars) - horizon - len(selected_indices),
            )
    return {
        'production_dataset': production,
        'rows': rows,
        'datasets': datasets,
        'common_sample_indices': selected_indices,
        'common_sample_count': len(selected_indices),
        'common_complete_case_scope': 'all_A_to_E_features',
    }


def _select_classifier(evaluations):
    eligible = [item for item in evaluations if item['threshold_eligible']]
    return max(
        eligible or evaluations,
        key=lambda item: (
            item['selection_score'],
            -item['metrics']['degenerate_fold_count'],
            item['metrics']['mean_macro_f1'],
            item['metrics']['mean_balanced_accuracy'],
            item['metrics']['worst_fold_minimum_class_recall'],
            item['model'] == 'Logistic Regression',
        ),
    )


def evaluate_classification_development(dataset):
    """Evaluate one feature set without reading any independent Test rows."""
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    evaluations = [
        {'model': 'Logistic Regression', 'params': None,
         **evaluate_classifier_walk_forward(_logistic_regression, folds)},
        {'model': 'Random Forest Classifier',
         **tune_random_forest_classifier(folds)},
    ]
    for evaluation in evaluations:
        evaluation['quality_gate'] = evaluate_classification_quality_gate(
            {**evaluation['metrics'], 'fold_metrics': evaluation['fold_metrics']},
            folds,
        )
    selected = _select_classifier(evaluations)
    return {
        'scope': 'development_purged_walk_forward_only',
        'selected_model': selected['model'],
        'selected_params': selected.get('params'),
        'selected_threshold': selected['threshold'],
        'metrics': selected['metrics'],
        'quality_gate': selected['quality_gate'],
        'folds': folds,
        'fold_metrics': selected['fold_metrics'],
        'threshold_stability': selected['threshold_stability'],
        'candidate_models': evaluations,
        'purge_gap': split['gap_size'],
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
        'split_boundaries': split['boundaries'],
    }


def evaluate_regression_development(dataset):
    """Tune regression models on purged Walk-Forward Validation only."""
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    tuning = tune_regression_models(folds)
    selected = tuning['selected']
    return {
        'scope': 'development_purged_walk_forward_only',
        'selected_model': selected['model'],
        'selected_family': selected['family'],
        'selected_params': selected['params'],
        'metrics': selected,
        'quality_gate': selected['quality_gate'],
        'folds': folds,
        'candidate_models': tuning['candidates'],
        'purge_gap': split['gap_size'],
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
        'split_boundaries': split['boundaries'],
    }


def _distribution(values):
    values = np.asarray(values, dtype=float)
    percentiles = np.quantile(values, (0.05, 0.25, 0.50, 0.75, 0.95))
    return {
        'sample_count': int(len(values)),
        'mean': float(np.mean(values)),
        'standard_deviation': float(np.std(values)),
        'median': float(percentiles[2]),
        'p05': float(percentiles[0]),
        'p25': float(percentiles[1]),
        'p75': float(percentiles[3]),
        'p95': float(percentiles[4]),
        'minimum': float(np.min(values)),
        'maximum': float(np.max(values)),
    }


def _population_stability_index(reference, comparison, bin_count=10):
    reference = np.asarray(reference, dtype=float)
    comparison = np.asarray(comparison, dtype=float)
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bin_count + 1)))
    if len(edges) < 3:
        return None
    edges[0] = -np.inf
    edges[-1] = np.inf
    reference_counts, _ = np.histogram(reference, bins=edges)
    comparison_counts, _ = np.histogram(comparison, bins=edges)
    reference_ratio = np.maximum(reference_counts / len(reference), 1e-6)
    comparison_ratio = np.maximum(comparison_counts / len(comparison), 1e-6)
    return float(np.sum(
        (comparison_ratio - reference_ratio)
        * np.log(comparison_ratio / reference_ratio)
    ))


def distribution_drift(reference, comparison):
    reference = np.asarray(reference, dtype=float)
    comparison = np.asarray(comparison, dtype=float)
    pooled_scale = sqrt((float(np.var(reference)) + float(np.var(comparison))) / 2)
    wasserstein = float(wasserstein_distance(reference, comparison))
    return {
        'psi': _population_stability_index(reference, comparison),
        'ks_statistic': float(ks_2samp(reference, comparison).statistic),
        'wasserstein_distance': wasserstein,
        'standardized_wasserstein_distance': (
            float(wasserstein / pooled_scale) if pooled_scale > 0 else None
        ),
        'standardized_mean_difference': (
            float((np.mean(comparison) - np.mean(reference)) / pooled_scale)
            if pooled_scale > 0 else None
        ),
    }


def _chronological_block_positions(dataset, include_test):
    split = build_purged_chronological_split(dataset)
    development_positions = np.array_split(np.arange(split['development_end']), 3)
    blocks = {
        name: tuple(int(value) for value in values)
        for name, values in zip(
            ('older_development', 'middle_development', 'recent_development'),
            development_positions,
        )
    }
    if include_test:
        blocks['independent_test'] = tuple(range(
            split['final_test_start'],
            split['final_test_start'] + split['test_samples'],
        ))
    return split, blocks


def regime_shift_report(bars, dataset, rows, *, include_test=False):
    """Quantify fixed chronological blocks; Test is optional and post-selection only."""
    split, block_positions = _chronological_block_positions(dataset, include_test)
    blocks = {}
    values_by_block = {}
    for block_name, positions in block_positions.items():
        sample_indices = tuple(dataset.sample_indices[position] for position in positions)
        block_values = {
            feature: tuple(float(rows[index][feature]) for index in sample_indices)
            for feature in DRIFT_FEATURES
        }
        values_by_block[block_name] = block_values
        blocks[block_name] = {
            'sample_count': len(sample_indices),
            'first_market_date': bars[sample_indices[0]].date.isoformat(),
            'last_market_date': bars[sample_indices[-1]].date.isoformat(),
            'features': {
                feature: _distribution(block_values[feature])
                for feature in DRIFT_FEATURES
            },
        }
    transitions = []
    ordered_names = list(blocks)
    for previous, current in zip(ordered_names, ordered_names[1:]):
        transitions.append({
            'from': previous,
            'to': current,
            'feature_drift': {
                feature: distribution_drift(
                    values_by_block[previous][feature],
                    values_by_block[current][feature],
                )
                for feature in DRIFT_FEATURES
            },
        })
    development_transitions = [
        transition for transition in transitions
        if transition['to'] != 'independent_test'
    ]
    top_development_drift = sorted(
        (
            {
                'feature': feature,
                'maximum_development_ks': max(
                    transition['feature_drift'][feature]['ks_statistic']
                    for transition in development_transitions
                ),
                'maximum_development_standardized_wasserstein': max(
                    transition['feature_drift'][feature][
                        'standardized_wasserstein_distance'
                    ] or 0.0
                    for transition in development_transitions
                ),
                'maximum_development_psi': max(
                    transition['feature_drift'][feature]['psi'] or 0.0
                    for transition in development_transitions
                ),
            }
            for feature in DRIFT_FEATURES
        ),
        key=lambda item: (
            item['maximum_development_ks'],
            item['maximum_development_standardized_wasserstein'],
        ),
        reverse=True,
    )
    return {
        'scope': (
            'development_and_post_selection_independent_test'
            if include_test else 'development_only'
        ),
        'block_definition': (
            'The pre-Test Development sample universe is divided into three fixed, '
            'equal-count chronological blocks. Purge rows are excluded from Test.'
        ),
        'blocks': blocks,
        'transitions': transitions,
        'top_development_drift_features': top_development_drift,
        'independent_test_accessed': bool(include_test),
        'independent_test_used_for_feature_selection': False,
        'purge_gap': split['gap_size'],
    }


def chronological_target_shift_report(bars, dataset, *, include_test=False):
    """Describe fixed chronological target blocks without using them for selection."""
    split, block_positions = _chronological_block_positions(dataset, include_test)
    blocks = {}
    values_by_block = {}
    for block_name, positions in block_positions.items():
        values = tuple(float(dataset.regression_labels[position]) for position in positions)
        sample_indices = tuple(dataset.sample_indices[position] for position in positions)
        values_by_block[block_name] = values
        blocks[block_name] = {
            'sample_count': len(values),
            'first_feature_date': bars[sample_indices[0]].date.isoformat(),
            'last_feature_date': bars[sample_indices[-1]].date.isoformat(),
            'future_return': _distribution(values),
            'up_count': int(sum(value > 0 for value in values)),
            'down_count': int(sum(value <= 0 for value in values)),
            'positive_return_ratio': float(sum(value > 0 for value in values) / len(values)),
        }
    transitions = []
    ordered_names = list(blocks)
    for previous, current in zip(ordered_names, ordered_names[1:]):
        transitions.append({
            'from': previous,
            'to': current,
            'future_return_drift': distribution_drift(
                values_by_block[previous], values_by_block[current],
            ),
            'positive_return_ratio_change': float(
                blocks[current]['positive_return_ratio']
                - blocks[previous]['positive_return_ratio']
            ),
        })
    return {
        'scope': (
            'development_and_post_selection_independent_test'
            if include_test else 'development_only'
        ),
        'horizon': dataset.horizon,
        'blocks': blocks,
        'transitions': transitions,
        'independent_test_accessed': bool(include_test),
        'independent_test_used_for_feature_selection': False,
        'purge_gap': split['gap_size'],
    }


def _target_summary(labels, task):
    values = np.asarray(labels, dtype=float)
    result = _distribution(values)
    if task == 'classification':
        result.update({
            'up_count': int(np.sum(values == 1)),
            'down_count': int(np.sum(values == 0)),
            'up_ratio': float(np.mean(values == 1)),
        })
    else:
        result['positive_return_ratio'] = float(np.mean(values > 0))
    return result


def regime_composition_report(dataset, rows, task):
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    labels = (
        dataset.classification_labels if task == 'classification'
        else dataset.regression_labels
    )
    sample_position_by_index = {
        sample_index: position
        for position, sample_index in enumerate(dataset.sample_indices)
    }

    def summarize(positions):
        result = {}
        for regime_key in ('volatility_regime', 'trend_regime'):
            names = sorted({rows[dataset.sample_indices[pos]][regime_key] for pos in positions})
            result[regime_key] = {}
            for name in names:
                regime_positions = tuple(
                    pos for pos in positions
                    if rows[dataset.sample_indices[pos]][regime_key] == name
                )
                target_values = tuple(labels[pos] for pos in regime_positions)
                result[regime_key][name] = {
                    'sample_count': len(regime_positions),
                    'sample_ratio': float(len(regime_positions) / len(positions))
                    if positions else 0.0,
                    'target': _target_summary(target_values, task),
                }
        return result

    development_positions = tuple(range(split['development_end']))
    fold_results = []
    for fold in folds:
        start = sample_position_by_index[
            fold['boundaries']['validation_first_feature_index']
        ]
        end = start + fold['validation_samples']
        fold_results.append({
            'fold': fold['fold'],
            'validation_samples': fold['validation_samples'],
            'regimes': summarize(tuple(range(start, end))),
        })
    return {
        'scope': 'development_walk_forward_only',
        'development': summarize(development_positions),
        'folds': fold_results,
        'independent_test_accessed': False,
    }


def _optional_mean(values):
    valid = [float(value) for value in values if value is not None]
    return float(mean(valid)) if valid else None


def _classification_summary(row):
    metrics = row['metrics']
    gate = row['quality_gate']
    return {
        'balanced_accuracy': metrics['mean_balanced_accuracy'],
        'macro_f1': metrics['mean_macro_f1'],
        'roc_auc': metrics['mean_roc_auc'],
        'minimum_class_recall': metrics['mean_minimum_class_recall'],
        'baseline_improvement': gate['observed']['accuracy_improvement_over_baseline'],
        'macro_f1_std': metrics['std_macro_f1'],
        'fold_metrics': row['fold_metrics'],
    }


def _regression_summary(row):
    metrics = row['metrics']
    return {
        'mae_improvement': metrics['mae_improvement_over_zero'],
        'rmse_improvement': metrics['rmse_improvement_over_zero'],
        'improving_fold_ratio': metrics['improving_fold_ratio'],
        'r2': metrics['model_metrics']['r2'],
        'fold_mae_std': metrics['fold_mae_std'],
        'fold_metrics': metrics['folds'],
    }


def select_regime_feature_candidate(development_results, task):
    """Select at most one B-E candidate without accepting Test-bearing input."""
    if task not in ('classification', 'regression'):
        raise ValueError('Task must be classification or regression.')
    if any(
        'independent_test' in row or row.get('independent_test_accessed') is True
        for row in development_results
    ):
        raise ValueError('Independent Test data cannot enter regime feature selection.')
    contexts = {(row['symbol'], row['lookback']) for row in development_results}
    baselines = {
        (row['symbol'], row['lookback']): row
        for row in development_results if row['experiment'] == 'A'
    }
    if set(baselines) != contexts:
        raise ValueError('Every context requires Experiment A baseline.')
    rules = REGIME_CANDIDATE_RULES[task]
    candidates = []
    for experiment in ('B', 'C', 'D', 'E'):
        rows = [row for row in development_results if row['experiment'] == experiment]
        comparisons = []
        for row in rows:
            baseline = baselines[(row['symbol'], row['lookback'])]
            current = (
                _classification_summary(row) if task == 'classification'
                else _regression_summary(row)
            )
            reference = (
                _classification_summary(baseline) if task == 'classification'
                else _regression_summary(baseline)
            )
            if task == 'classification':
                keys = (
                    'balanced_accuracy', 'macro_f1', 'roc_auc',
                    'minimum_class_recall', 'baseline_improvement', 'macro_f1_std',
                )
                deltas = {
                    key: float(current[key] - reference[key])
                    if current[key] is not None and reference[key] is not None else None
                    for key in keys
                }
                fold_improved = [
                    candidate_fold['balanced_accuracy'] > baseline_fold['balanced_accuracy']
                    and candidate_fold['macro_f1'] > baseline_fold['macro_f1']
                    and (
                        candidate_fold['roc_auc'] is not None
                        and baseline_fold['roc_auc'] is not None
                        and candidate_fold['roc_auc'] >= baseline_fold['roc_auc']
                    )
                    for candidate_fold, baseline_fold in zip(
                        current['fold_metrics'], reference['fold_metrics']
                    )
                ]
                harmed = any(
                    deltas[key] is None
                    or deltas[key] < -rules['maximum_metric_decline_per_context']
                    for key in ('balanced_accuracy', 'macro_f1', 'roc_auc')
                )
                context_improved = (
                    not harmed
                    and all(deltas[key] > 0 for key in (
                        'balanced_accuracy', 'macro_f1', 'roc_auc',
                    ))
                    and deltas['minimum_class_recall'] >= 0
                    and deltas['baseline_improvement'] >= 0
                )
            else:
                keys = (
                    'mae_improvement', 'rmse_improvement',
                    'improving_fold_ratio', 'r2', 'fold_mae_std',
                )
                deltas = {
                    key: float(current[key] - reference[key])
                    if current[key] is not None and reference[key] is not None else None
                    for key in keys
                }
                fold_improved = [
                    candidate_fold['mae_improvement_over_zero']
                    > baseline_fold['mae_improvement_over_zero']
                    and candidate_fold['rmse_improvement_over_zero']
                    > baseline_fold['rmse_improvement_over_zero']
                    for candidate_fold, baseline_fold in zip(
                        current['fold_metrics'], reference['fold_metrics']
                    )
                ]
                harmed = any(
                    deltas[key] is None
                    or deltas[key]
                    < -rules['maximum_error_improvement_decline_per_context']
                    for key in ('mae_improvement', 'rmse_improvement')
                )
                context_improved = (
                    not harmed
                    and deltas['mae_improvement'] > 0
                    and deltas['rmse_improvement'] > 0
                    and deltas['improving_fold_ratio'] >= 0
                )
            fold_improved_ratio = float(mean(fold_improved)) if fold_improved else 0.0
            context_improved = (
                context_improved
                and fold_improved_ratio >= rules['minimum_improved_fold_ratio']
            )
            comparisons.append({
                'symbol': row['symbol'],
                'lookback': row['lookback'],
                'deltas': deltas,
                'fold_improved_ratio': fold_improved_ratio,
                'context_improved': context_improved,
                'context_harmed': harmed,
            })
        mean_deltas = {
            key: _optional_mean(item['deltas'][key] for item in comparisons)
            for key in comparisons[0]['deltas']
        }
        improved_context_count = sum(item['context_improved'] for item in comparisons)
        improved_symbols = {item['symbol'] for item in comparisons if item['context_improved']}
        harmed_context_count = sum(item['context_harmed'] for item in comparisons)
        mean_fold_improved_ratio = float(mean(
            item['fold_improved_ratio'] for item in comparisons
        ))
        if task == 'classification':
            checks = {
                'contexts': improved_context_count >= rules['minimum_improved_context_count'],
                'symbols': len(improved_symbols) >= rules['minimum_improved_symbol_count'],
                'balanced_accuracy': mean_deltas['balanced_accuracy']
                >= rules['minimum_mean_balanced_accuracy_delta'],
                'macro_f1': mean_deltas['macro_f1']
                >= rules['minimum_mean_macro_f1_delta'],
                'roc_auc': mean_deltas['roc_auc'] >= rules['minimum_mean_roc_auc_delta'],
                'minimum_recall': mean_deltas['minimum_class_recall']
                >= rules['minimum_mean_minimum_recall_delta'],
                'baseline': mean_deltas['baseline_improvement']
                >= rules['minimum_mean_baseline_improvement_delta'],
                'folds': mean_fold_improved_ratio >= rules['minimum_improved_fold_ratio'],
                'stability': mean_deltas['macro_f1_std']
                <= rules['maximum_macro_f1_std_increase'],
                'limited_harm': harmed_context_count <= rules['maximum_harmed_context_count'],
            }
            score = float(
                0.30 * mean_deltas['balanced_accuracy']
                + 0.30 * mean_deltas['macro_f1']
                + 0.20 * mean_deltas['roc_auc']
                + 0.10 * mean_deltas['minimum_class_recall']
                + 0.10 * mean_deltas['baseline_improvement']
                + 0.05 * mean_fold_improved_ratio
                - 0.05 * max(0.0, mean_deltas['macro_f1_std'])
            )
        else:
            checks = {
                'contexts': improved_context_count >= rules['minimum_improved_context_count'],
                'symbols': len(improved_symbols) >= rules['minimum_improved_symbol_count'],
                'mae': mean_deltas['mae_improvement']
                >= rules['minimum_mean_mae_improvement_delta'],
                'rmse': mean_deltas['rmse_improvement']
                >= rules['minimum_mean_rmse_improvement_delta'],
                'improving_fold_ratio': mean_deltas['improving_fold_ratio']
                >= rules['minimum_mean_improving_fold_ratio_delta'],
                'folds': mean_fold_improved_ratio >= rules['minimum_improved_fold_ratio'],
                'stability': mean_deltas['fold_mae_std']
                <= rules['maximum_fold_mae_std_increase'],
                'limited_harm': harmed_context_count <= rules['maximum_harmed_context_count'],
            }
            score = float(
                0.40 * mean_deltas['mae_improvement']
                + 0.35 * mean_deltas['rmse_improvement']
                + 0.15 * mean_deltas['improving_fold_ratio']
                + 0.10 * mean_fold_improved_ratio
                - 0.05 * max(0.0, mean_deltas['fold_mae_std'])
            )
        candidates.append({
            'experiment': experiment,
            'label': REGIME_EXPERIMENT_LABELS[experiment],
            'eligible': all(checks.values()),
            'checks': checks,
            'mean_deltas_vs_A': mean_deltas,
            'mean_fold_improved_ratio': mean_fold_improved_ratio,
            'improved_context_count': int(improved_context_count),
            'improved_symbol_count': len(improved_symbols),
            'improved_symbols': sorted(improved_symbols),
            'harmed_context_count': int(harmed_context_count),
            'development_only_score': score,
            'contexts': comparisons,
        })
    eligible = [candidate for candidate in candidates if candidate['eligible']]
    selected = max(
        eligible,
        key=lambda candidate: (
            candidate['development_only_score'],
            -ord(candidate['experiment']),
        ),
    ) if eligible else None
    return {
        'task': task,
        'selected_experiment': selected['experiment'] if selected else None,
        'selected_candidate': selected,
        'candidates': candidates,
        'selection_source': 'development_purged_walk_forward_only',
        'independent_test_used': False,
        'rules': rules,
    }


def evaluate_classification_independent_test(dataset, development_result):
    """Evaluate one already-frozen classification feature/model/threshold choice."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a Development-only frozen classification result.')
    split = build_purged_chronological_split(dataset)
    model = (
        _logistic_regression()
        if development_result['selected_model'] == 'Logistic Regression'
        else _random_forest_classifier(development_result['selected_params'])
    )
    model.fit(
        dataset.features[:split['development_end']],
        dataset.classification_labels[:split['development_end']],
    )
    probabilities = model.predict_proba(split['x_test'])[
        :, list(model.classes_).index(1)
    ]
    predictions = _predictions_for_threshold(
        probabilities, development_result['selected_threshold'],
    )
    metrics = _classification_metrics(
        split['y_classification_test'], predictions, probabilities,
    )
    baseline = majority_class_baseline_accuracy(split['y_classification_test'])
    test_gate = evaluate_independent_test_quality_gate(metrics)
    final_gate = evaluate_final_classification_quality_gate(
        development_result['quality_gate'], test_gate,
    )
    return {
        'scope': 'final_untouched_independent_test',
        'metrics': {
            **metrics,
            'majority_baseline_accuracy': baseline,
            'accuracy_improvement_over_baseline': float(metrics['accuracy'] - baseline),
        },
        'quality_gate': test_gate,
        'final_quality_gate': final_gate,
        'test_used_for_model_selection': False,
        'test_used_for_threshold_selection': False,
        'test_used_for_feature_selection': False,
        'model_refit_after_test': False,
        'test_evaluation_count': 1,
        'purge_gap': split['gap_size'],
        'validation_test_purge_safe': split['boundaries']['validation_test_purge_safe'],
    }


def evaluate_regression_independent_test(dataset, development_result):
    """Evaluate one already-frozen regression feature/model choice."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a Development-only frozen regression result.')
    split = build_purged_chronological_split(dataset)
    candidate = {
        'model': development_result['selected_model'],
        'family': development_result['selected_family'],
        'params': development_result['selected_params'],
    }
    model = _regression_model(candidate)
    development_labels = dataset.regression_labels[:split['development_end']]
    model.fit(dataset.regression_features[:split['development_end']], development_labels)
    labels = np.asarray(split['y_regression_test'], dtype=float)
    predictions = np.asarray(model.predict(split['x_regression_test']), dtype=float)
    zeros = np.zeros(len(labels), dtype=float)
    development_mean = float(mean(development_labels))
    mean_predictions = np.full(len(labels), development_mean, dtype=float)
    test_evaluation = {
        'source': 'independent_test',
        'sample_count': len(labels),
        'model_metrics': _regression_metrics(labels, predictions),
        'zero_return_baseline': {
            'name': 'zero_future_return',
            **_regression_metrics(labels, zeros),
        },
        'historical_training_mean_baseline': {
            'name': 'development_training_mean_future_return',
            'training_mean_return': development_mean,
            **_regression_metrics(labels, mean_predictions),
        },
        'prediction_diagnostics': _regression_prediction_diagnostics(labels, predictions),
    }
    test_gate = evaluate_regression_independent_test_quality_gate(test_evaluation)
    final_gate = evaluate_final_regression_quality_gate(
        development_result['quality_gate'], test_gate,
    )
    return {
        'scope': 'final_untouched_independent_test',
        'metrics': test_evaluation,
        'quality_gate': test_gate,
        'final_quality_gate': final_gate,
        'test_used_for_model_selection': False,
        'test_used_for_feature_selection': False,
        'model_refit_after_test': False,
        'test_evaluation_count': 1,
        'purge_gap': split['gap_size'],
        'validation_test_purge_safe': split['boundaries']['validation_test_purge_safe'],
    }
