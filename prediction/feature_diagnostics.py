from dataclasses import replace
from math import isfinite, sqrt
from statistics import mean, median, pstdev

import numpy as np

from backtest.services import (
    calculate_atr,
    calculate_macd,
    calculate_rsi,
    calculate_simple_moving_average,
)
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
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    evaluate_classification_quality_gate,
    evaluate_classifier_walk_forward,
    evaluate_final_classification_quality_gate,
    evaluate_independent_test_quality_gate,
    generate_regression_machine_learning_prediction,
    majority_class_baseline_accuracy,
    tune_random_forest_classifier,
)


FEATURE_EXPERIMENT_LABELS = {
    'A': 'Production baseline',
    'B': 'Scale-normalized core',
    'C': 'B + multi-period momentum',
    'D': 'C + MACD/RSI changes',
    'E': 'D + volatility/volume/trend strength',
}

CLASSIFICATION_FEATURE_SETS = {
    'A': FEATURE_NAMES,
    'B': (
        'daily_return',
        'price_ma5_ratio', 'price_ma10_ratio', 'price_ma20_ratio', 'price_ma60_ratio',
        'ma5_ma20_ratio', 'ma10_ma20_ratio', 'ma20_ma60_ratio',
        'rsi',
        'macd_price_ratio', 'macd_signal_price_ratio', 'macd_histogram_price_ratio',
        'atr_price_ratio',
        'volume_change', 'volume_average_20_ratio',
        'volatility_20',
    ),
}
CLASSIFICATION_FEATURE_SETS['C'] = CLASSIFICATION_FEATURE_SETS['B'] + (
    'return_2', 'return_3', 'return_5', 'return_10', 'return_20', 'return_60',
)
CLASSIFICATION_FEATURE_SETS['D'] = CLASSIFICATION_FEATURE_SETS['C'] + (
    'rsi_change_1', 'rsi_change_3',
    'macd_change_1', 'macd_histogram_change_1',
)
CLASSIFICATION_FEATURE_SETS['E'] = CLASSIFICATION_FEATURE_SETS['D'] + (
    'volatility_5', 'volatility_10', 'volatility_60',
    'volume_change_5', 'volume_average_60_ratio',
    'gap_return', 'intraday_range',
    'ma5_slope_5', 'ma20_slope_5', 'ma60_slope_5',
    'price_above_ma20', 'price_above_ma60',
    'distance_to_20_day_high', 'distance_from_20_day_low',
    'distance_to_60_day_high', 'distance_from_60_day_low',
)

REGRESSION_FEATURE_SETS = {
    'A': REGRESSION_FEATURE_NAMES,
    'B': REGRESSION_FEATURE_NAMES + (
        'ma5_ma20_ratio', 'ma10_ma20_ratio', 'ma20_ma60_ratio',
    ),
}
REGRESSION_FEATURE_SETS['C'] = REGRESSION_FEATURE_SETS['B'] + (
    'return_2', 'return_60',
)
REGRESSION_FEATURE_SETS['D'] = REGRESSION_FEATURE_SETS['C'] + (
    'rsi_change_1', 'rsi_change_3',
    'macd_change_1', 'macd_histogram_change_1',
)
REGRESSION_FEATURE_SETS['E'] = REGRESSION_FEATURE_SETS['D'] + (
    'volatility_60', 'volume_change_5', 'volume_average_60_ratio',
    'gap_return', 'intraday_range',
    'ma60_slope_5', 'price_above_ma20', 'price_above_ma60',
    'distance_to_60_day_high', 'distance_from_60_day_low',
)

REGIME_FEATURES = (
    'daily_return',
    'volatility_20',
    'atr_price_ratio',
    'rsi',
    'volume_average_20_ratio',
    'price_ma20_ratio',
)


def _ratio(value, reference, *, minus_one=True):
    if value is None or reference is None or float(reference) == 0:
        return None
    result = float(value) / float(reference)
    return result - 1.0 if minus_one else result


def _period_return(closes, index, period):
    if index < period or closes[index - period] == 0:
        return None
    return closes[index] / closes[index - period] - 1.0


def _rolling_std(values, index, period):
    if index < period:
        return None
    window = values[index - period + 1:index + 1]
    if len(window) != period or any(value is None for value in window):
        return None
    return float(pstdev(window))


def _rolling_mean(values, index, period):
    if index < period - 1:
        return None
    window = values[index - period + 1:index + 1]
    if len(window) != period or any(value is None for value in window):
        return None
    return float(mean(window))


def _rolling_extreme(values, index, period, operation):
    if index < period - 1:
        return None
    window = values[index - period + 1:index + 1]
    if len(window) != period or any(value is None for value in window):
        return None
    return float(operation(window))


def _change(values, index, period, scale=1.0):
    if index < period or values[index] is None or values[index - period] is None:
        return None
    return (float(values[index]) - float(values[index - period])) / scale


def _rich_feature_rows(bars, production_dataset):
    closes = tuple(float(bar.close) for bar in bars)
    volumes = tuple(float(bar.volume) for bar in bars)
    daily_returns = tuple(
        None if index == 0 else _period_return(closes, index, 1)
        for index in range(len(bars))
    )
    ma5 = calculate_simple_moving_average(bars, 5)
    ma10 = calculate_simple_moving_average(bars, 10)
    ma20 = calculate_simple_moving_average(bars, 20)
    ma60 = calculate_simple_moving_average(bars, 60)
    rsi = calculate_rsi(bars, 14)
    atr = calculate_atr(bars, 14)
    macd, macd_signal, macd_histogram = calculate_macd(bars)
    production_rows = {
        sample_index: {
            **dict(zip(FEATURE_NAMES, feature_row)),
            **dict(zip(REGRESSION_FEATURE_NAMES, regression_row)),
        }
        for sample_index, feature_row, regression_row in zip(
            production_dataset.sample_indices,
            production_dataset.features,
            production_dataset.regression_features,
        )
    }
    # Labeled rows stop `horizon` observations before the latest market date,
    # while inference needs the current point-in-time row. Preserve the exact
    # production latest-feature calculations for that unlabeled final bar.
    if production_dataset.latest_features is not None:
        production_rows.setdefault(len(bars) - 1, {}).update(dict(zip(
            FEATURE_NAMES,
            production_dataset.latest_features,
        )))
    if production_dataset.latest_regression_features is not None:
        production_rows.setdefault(len(bars) - 1, {}).update(dict(zip(
            REGRESSION_FEATURE_NAMES,
            production_dataset.latest_regression_features,
        )))

    rows = []
    for index, bar in enumerate(bars):
        average_volume_20 = _rolling_mean(volumes, index, 20)
        average_volume_60 = _rolling_mean(volumes, index, 60)
        high_20 = _rolling_extreme(closes, index, 20, max)
        low_20 = _rolling_extreme(closes, index, 20, min)
        high_60 = _rolling_extreme(closes, index, 60, max)
        low_60 = _rolling_extreme(closes, index, 60, min)
        row = {
            'daily_return': daily_returns[index],
            'return_1': daily_returns[index],
            'return_2': _period_return(closes, index, 2),
            'return_3': _period_return(closes, index, 3),
            'return_5': _period_return(closes, index, 5),
            'return_10': _period_return(closes, index, 10),
            'return_20': _period_return(closes, index, 20),
            'return_60': _period_return(closes, index, 60),
            'ma5': ma5[index],
            'ma10': ma10[index],
            'ma20': ma20[index],
            'ma60': ma60[index],
            'price_ma5_ratio': _ratio(bar.close, ma5[index]),
            'price_ma10_ratio': _ratio(bar.close, ma10[index]),
            'price_ma20_ratio': _ratio(bar.close, ma20[index]),
            'price_ma60_ratio': _ratio(bar.close, ma60[index]),
            'ma5_ma20_ratio': _ratio(ma5[index], ma20[index]),
            'ma10_ma20_ratio': _ratio(ma10[index], ma20[index]),
            'ma20_ma60_ratio': _ratio(ma20[index], ma60[index]),
            'rsi': rsi[index],
            'macd': macd[index],
            'macd_signal': macd_signal[index],
            'macd_histogram': macd_histogram[index],
            'atr': atr[index],
            'atr_price_ratio': _ratio(atr[index], bar.close, minus_one=False),
            'macd_price_ratio': _ratio(macd[index], bar.close, minus_one=False),
            'macd_signal_price_ratio': _ratio(macd_signal[index], bar.close, minus_one=False),
            'macd_histogram_price_ratio': _ratio(macd_histogram[index], bar.close, minus_one=False),
            'macd_change_1': (
                _change(macd, index, 1, scale=float(bar.close))
                if float(bar.close) != 0 else None
            ),
            'macd_histogram_change_1': (
                _change(macd_histogram, index, 1, scale=float(bar.close))
                if float(bar.close) != 0 else None
            ),
            'rsi_change_1': _change(rsi, index, 1, scale=100.0),
            'rsi_change_3': _change(rsi, index, 3, scale=100.0),
            'volatility_5': _rolling_std(daily_returns, index, 5),
            'volatility_10': _rolling_std(daily_returns, index, 10),
            'volatility_20': (
                _rolling_std(daily_returns, index, 20) * sqrt(252)
                if _rolling_std(daily_returns, index, 20) is not None else None
            ),
            'volatility_60': _rolling_std(daily_returns, index, 60),
            'volume': float(bar.volume),
            'volume_change': _period_return(volumes, index, 1),
            'volume_change_1': _period_return(volumes, index, 1),
            'volume_change_5': _period_return(volumes, index, 5),
            'volume_average_20_ratio': _ratio(bar.volume, average_volume_20),
            'volume_average_60_ratio': _ratio(bar.volume, average_volume_60),
            'gap_return': (
                _ratio(bar.open, bars[index - 1].close)
                if index else None
            ),
            'intraday_range': _ratio(bar.high - bar.low, bar.close, minus_one=False),
            'ma5_slope_5': _ratio(ma5[index], ma5[index - 5]) if index >= 5 else None,
            'ma10_slope_5': _ratio(ma10[index], ma10[index - 5]) if index >= 5 else None,
            'ma20_slope_5': _ratio(ma20[index], ma20[index - 5]) if index >= 5 else None,
            'ma60_slope_5': _ratio(ma60[index], ma60[index - 5]) if index >= 5 else None,
            'price_above_ma20': (
                float(bar.close > ma20[index]) if ma20[index] is not None else None
            ),
            'price_above_ma60': (
                float(bar.close > ma60[index]) if ma60[index] is not None else None
            ),
            'distance_to_20_day_high': _ratio(bar.close, high_20),
            'distance_from_20_day_low': _ratio(bar.close, low_20),
            'distance_to_60_day_high': _ratio(bar.close, high_60),
            'distance_from_60_day_low': _ratio(bar.close, low_60),
        }
        row.update(production_rows.get(index, {}))
        rows.append(row)
    return tuple(rows)


def _is_complete(values):
    return all(value is not None and isfinite(float(value)) for value in values)


def experiment_feature_names(task, experiment):
    feature_sets = (
        CLASSIFICATION_FEATURE_SETS
        if task == 'classification'
        else REGRESSION_FEATURE_SETS
    )
    return tuple(feature_sets[experiment])


def build_experiment_dataset(bars, horizon, task, experiment, noise_band=0.0):
    """Build a point-in-time dataset on rows shared by every A-E experiment."""
    if noise_band:
        raise ValueError(
            'Noise-band filtering must use the dedicated target_noise_diagnostics '
            'two-phase workflow so Test remains untouched during band selection.'
        )
    production = build_prediction_feature_dataset(bars, horizon)
    rows = _rich_feature_rows(bars, production)
    feature_sets = (
        CLASSIFICATION_FEATURE_SETS
        if task == 'classification'
        else REGRESSION_FEATURE_SETS
    )
    all_names = tuple(dict.fromkeys(
        name
        for names in feature_sets.values()
        for name in names
    ))
    selected_names = tuple(feature_sets[experiment])
    base_positions = {index: position for position, index in enumerate(production.sample_indices)}
    selected_positions = []
    selected_indices = []
    selected_features = []
    selected_classification_labels = []
    selected_regression_labels = []
    selected_other_features = []
    for sample_index in production.sample_indices:
        row = rows[sample_index]
        if not _is_complete(row.get(name) for name in all_names):
            continue
        position = base_positions[sample_index]
        future_return = production.regression_labels[position]
        selected_positions.append(position)
        selected_indices.append(sample_index)
        selected_features.append(tuple(float(row[name]) for name in selected_names))
        selected_classification_labels.append(production.classification_labels[position])
        selected_regression_labels.append(future_return)
        selected_other_features.append(production.regression_features[position])

    latest_row = rows[-1]
    latest_selected = (
        tuple(float(latest_row[name]) for name in selected_names)
        if _is_complete(latest_row.get(name) for name in selected_names)
        else None
    )
    if task == 'classification':
        return replace(
            production,
            feature_names=selected_names,
            features=tuple(selected_features),
            classification_labels=tuple(selected_classification_labels),
            regression_labels=tuple(selected_regression_labels),
            regression_features=tuple(selected_other_features),
            sample_indices=tuple(selected_indices),
            latest_features=latest_selected,
            discarded_labeled_rows=(len(bars) - horizon - len(selected_indices)),
        )
    return replace(
        production,
        regression_feature_names=selected_names,
        regression_features=tuple(selected_features),
        classification_labels=tuple(selected_classification_labels),
        regression_labels=tuple(selected_regression_labels),
        features=tuple(production.features[position] for position in selected_positions),
        sample_indices=tuple(selected_indices),
        latest_regression_features=latest_selected,
        discarded_labeled_rows=(len(bars) - horizon - len(selected_indices)),
    )


def target_distribution(dataset):
    returns = np.asarray(dataset.regression_labels, dtype=float)
    return {
        'sample_count': int(len(returns)),
        'up_count': int(np.sum(returns > 0)),
        'down_count': int(np.sum(returns <= 0)),
        'mean': float(np.mean(returns)),
        'median': float(np.median(returns)),
        'standard_deviation': float(np.std(returns)),
        'q25': float(np.quantile(returns, 0.25)),
        'q75': float(np.quantile(returns, 0.75)),
        'within_noise_band': {
            '0.001': float(np.mean(np.abs(returns) <= 0.001)),
            '0.0025': float(np.mean(np.abs(returns) <= 0.0025)),
            '0.005': float(np.mean(np.abs(returns) <= 0.005)),
        },
    }


def target_alignment_example(bars, dataset):
    position = 0
    feature_index = dataset.sample_indices[position]
    target_index = feature_index + dataset.horizon
    current_close = float(bars[feature_index].close)
    future_close = float(bars[target_index].close)
    return {
        'feature_date': bars[feature_index].date.isoformat(),
        'current_close': current_close,
        'target_date': bars[target_index].date.isoformat(),
        'future_close': future_close,
        'calculated_target': float(future_close / current_close - 1.0),
        'stored_target': float(dataset.regression_labels[position]),
        'feature_index': feature_index,
        'target_index': target_index,
    }


def evaluate_classification_dataset(dataset):
    """Mirror production classification evaluation without running regression."""
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    logistic = {'model': 'Logistic Regression', 'params': None, **evaluate_classifier_walk_forward(
        _logistic_regression,
        folds,
    )}
    random_forest = {
        'model': 'Random Forest Classifier',
        **tune_random_forest_classifier(folds),
    }
    evaluations = [logistic, random_forest]
    eligible = [evaluation for evaluation in evaluations if evaluation['threshold_eligible']]
    selected = max(
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
    for evaluation in evaluations:
        evaluation['walk_forward_quality_gate'] = evaluate_classification_quality_gate(
            {**evaluation['metrics'], 'fold_metrics': evaluation['fold_metrics']},
            folds,
        )

    model = (
        _logistic_regression()
        if selected['model'] == 'Logistic Regression'
        else _random_forest_classifier(selected['params'])
    )
    development_end = split['development_end']
    model.fit(
        dataset.features[:development_end],
        dataset.classification_labels[:development_end],
    )
    test_probabilities = model.predict_proba(split['x_test'])[:, list(model.classes_).index(1)]
    test_predictions = _predictions_for_threshold(test_probabilities, selected['threshold'])
    test_metrics = _classification_metrics(
        split['y_classification_test'],
        test_predictions,
        test_probabilities,
    )
    test_gate = evaluate_independent_test_quality_gate(test_metrics)
    final_gate = evaluate_final_classification_quality_gate(
        selected['walk_forward_quality_gate'],
        test_gate,
    )
    baseline = majority_class_baseline_accuracy(split['y_classification_test'])
    return {
        'selected_model': selected['model'],
        'selected_params': selected['params'],
        'selected_threshold': selected['threshold'],
        'threshold_stability': selected['threshold_stability'],
        'walk_forward_metrics': selected['metrics'],
        'walk_forward_quality_gate': selected['walk_forward_quality_gate'],
        'independent_test_metrics': {
            **test_metrics,
            'majority_class_baseline_accuracy': float(baseline),
            'accuracy_improvement_over_baseline': float(test_metrics['accuracy'] - baseline),
        },
        'independent_test_quality_gate': test_gate,
        'final_quality_gate': final_gate,
        'split': split,
        'folds': folds,
        'test_used_for_selection': False,
    }


def _safe_correlation(first, second):
    if len(first) < 2 or np.std(first) == 0 or np.std(second) == 0:
        return None
    value = float(np.corrcoef(first, second)[0, 1])
    return value if isfinite(value) else None


def feature_quality_report(dataset, task, bars=None):
    split = build_purged_chronological_split(dataset)
    end = split['development_end']
    matrix = np.asarray(
        dataset.features[:end] if task == 'classification' else dataset.regression_features[:end],
        dtype=float,
    )
    labels = np.asarray(
        dataset.classification_labels[:end]
        if task == 'classification'
        else dataset.regression_labels[:end],
        dtype=float,
    )
    names = dataset.feature_names if task == 'classification' else dataset.regression_feature_names
    raw_missing_ratios = {}
    if bars is not None:
        production = build_prediction_feature_dataset(bars, dataset.horizon)
        raw_rows = _rich_feature_rows(bars, production)
        labeled_rows = raw_rows[:max(len(bars) - dataset.horizon, 0)]
        raw_missing_ratios = {
            name: (
                sum(
                    row.get(name) is None
                    or not isfinite(float(row[name]))
                    for row in labeled_rows
                ) / len(labeled_rows)
                if labeled_rows else 1.0
            )
            for name in names
        }
    features = []
    for column, name in enumerate(names):
        values = matrix[:, column]
        feature_mean = float(np.mean(values))
        feature_std = float(np.std(values))
        q25, q75 = np.quantile(values, (0.25, 0.75))
        iqr = float(q75 - q25)
        outlier_ratio = (
            float(np.mean((values < q25 - 3 * iqr) | (values > q75 + 3 * iqr)))
            if iqr > 0 else 0.0
        )
        target_correlation = _safe_correlation(values, labels)
        up_values = values[labels == 1] if task == 'classification' else np.asarray(())
        down_values = values[labels == 0] if task == 'classification' else np.asarray(())
        pooled_std = sqrt((float(np.var(up_values)) + float(np.var(down_values))) / 2) if (
            len(up_values) and len(down_values)
        ) else 0.0
        group_difference = (
            float((np.mean(up_values) - np.mean(down_values)) / pooled_std)
            if pooled_std > 0 else None
        )
        features.append({
            'feature': name,
            'raw_pre_warmup_missing_ratio': raw_missing_ratios.get(name),
            'model_matrix_missing_ratio': 0.0,
            'mean': feature_mean,
            'std': feature_std,
            'min': float(np.min(values)),
            'max': float(np.max(values)),
            'constant': feature_std == 0.0,
            'near_constant': feature_std <= max(1e-12, abs(feature_mean) * 1e-6),
            'outlier_ratio': outlier_ratio,
            'target_correlation': target_correlation,
            'classification_group_difference': group_difference,
        })

    correlations = np.corrcoef(matrix, rowvar=False)
    highly_correlated_pairs = []
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            correlation = float(correlations[left, right])
            if isfinite(correlation) and abs(correlation) >= 0.95:
                highly_correlated_pairs.append({
                    'left': names[left],
                    'right': names[right],
                    'correlation': correlation,
                })
    return {
        'source': 'development_data_only',
        'missing_ratio_scope': (
            'Raw ratios include indicator warm-up rows; model-matrix ratios are '
            'measured after the existing complete-case warm-up filter.'
        ),
        'sample_count': int(len(matrix)),
        'features': features,
        'highly_correlated_pairs': highly_correlated_pairs,
    }


def regime_sensitivity_report(bars, dataset):
    split = build_purged_chronological_split(dataset)
    development_end = split['development_end']
    test_start = development_end + dataset.horizon
    recent_development_count = min(
        development_end,
        max(1, 504 - split['test_samples']),
    )
    early_end = development_end - recent_development_count
    if early_end < 30:
        return {'available': False, 'reason': 'Fewer than 30 earlier-history samples are available.'}

    matrix = np.asarray(dataset.features, dtype=float)
    name_index = {name: index for index, name in enumerate(dataset.feature_names)}
    segments = {
        'earlier_history': matrix[:early_end],
        'recent_development': matrix[early_end:development_end],
        'independent_test': matrix[test_start:],
    }
    feature_drift = {}
    for name in REGIME_FEATURES:
        column = name_index[name]
        summaries = {}
        for segment_name, values in segments.items():
            column_values = values[:, column]
            summaries[segment_name] = {
                'sample_count': int(len(column_values)),
                'mean': float(np.mean(column_values)),
                'std': float(np.std(column_values)),
            }
        early = segments['earlier_history'][:, column]
        recent = segments['recent_development'][:, column]
        test = segments['independent_test'][:, column]
        early_recent_scale = sqrt((float(np.var(early)) + float(np.var(recent))) / 2)
        recent_test_scale = sqrt((float(np.var(recent)) + float(np.var(test))) / 2)
        feature_drift[name] = {
            **summaries,
            'earlier_to_recent_standardized_mean_difference': (
                float((np.mean(recent) - np.mean(early)) / early_recent_scale)
                if early_recent_scale > 0 else None
            ),
            'recent_to_test_standardized_mean_difference': (
                float((np.mean(test) - np.mean(recent)) / recent_test_scale)
                if recent_test_scale > 0 else None
            ),
        }

    targets = np.asarray(dataset.regression_labels, dtype=float)
    target_segments = {
        'earlier_history': targets[:early_end],
        'recent_development': targets[early_end:development_end],
        'independent_test': targets[test_start:],
    }
    return {
        'available': True,
        'source': 'chronological_feature_rows',
        'feature_drift': feature_drift,
        'target_drift': {
            name: {
                'sample_count': int(len(values)),
                'mean': float(np.mean(values)),
                'std': float(np.std(values)),
                'positive_ratio': float(np.mean(values > 0)),
            }
            for name, values in target_segments.items()
        },
    }


def regression_experiment_result(dataset, current_price):
    result = generate_regression_machine_learning_prediction(dataset, current_price)
    metrics = result['model_metrics']
    if metrics.get('status') == 'insufficient_data':
        return {
            'status': 'insufficient_data',
            'unavailable_reason': metrics.get('unavailable_reason'),
            'selected_model': None,
            'selected_params': None,
            'walk_forward_metrics': {},
            'walk_forward_quality_gate': {},
            'independent_test_metrics': metrics,
            'independent_test_quality_gate': {},
            'final_quality_gate': {},
            'split': result['split'],
            'folds': result['folds'],
            'test_used_for_selection': False,
        }
    walk_forward = metrics.get('walk_forward_quality_metrics') or {}
    walk_forward_gate = result.get('walk_forward_quality_gate') or {}
    test_gate = result.get('independent_test_quality_gate') or {}
    return {
        'selected_model': result.get('selected_candidate_model'),
        'selected_params': result.get('selected_candidate_params'),
        'walk_forward_metrics': walk_forward,
        'walk_forward_quality_gate': walk_forward_gate,
        'independent_test_metrics': metrics,
        'independent_test_quality_gate': test_gate,
        'final_quality_gate': result.get('final_quality_gate'),
        'split': result['split'],
        'folds': result['folds'],
        'test_used_for_selection': False,
    }
