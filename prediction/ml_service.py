from concurrent.futures import ThreadPoolExecutor
from math import isfinite, sqrt
from statistics import mean, median, pstdev

import numpy as np
from django.conf import settings
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import ElasticNet, HuberRegressor, LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


TRAINING_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
TEST_FRACTION = 0.15
MINIMUM_TRAINING_SAMPLES = 100
MINIMUM_VALIDATION_SAMPLES = 20
MINIMUM_TEST_SAMPLES = 20
RANDOM_STATE = 42
PREDICTION_PIPELINE_VERSION = 'purged-walk-forward-v6-independent-horizons-1'
# Central deployment-quality thresholds. Purged Walk-Forward results control
# candidate selection; the untouched independent Test is used only by the final
# publication gate and never feeds back into fitting, thresholds, or selection.
PREDICTION_QUALITY_GATE_THRESHOLDS = {
    'minimum_oos_samples': 50,
    'minimum_balanced_accuracy': 0.52,
    'minimum_macro_f1': 0.45,
    'minimum_accuracy_improvement_over_baseline': 0.01,
    # The independent Test remains untouched until the model and threshold are
    # locked. These thresholds only decide whether that frozen forecast may be
    # published; they never feed back into selection or fitting.
    'minimum_independent_test_samples': MINIMUM_TEST_SAMPLES,
    'minimum_independent_test_class_recall': 0.20,
    # Distribution skew is evaluated relative to the actual Test distribution,
    # not against a fixed UP/DOWN prediction ratio. It is applied only when the
    # actual minority class is materially represented.
    'minimum_actual_minority_ratio_for_distribution_check': 0.20,
    'minimum_predicted_to_actual_minority_ratio': 0.25,
    'minimum_regression_mae_improvement': 0.01,
    'minimum_regression_rmse_improvement': 0.01,
    # Regression must improve in a majority of chronological folds, so one
    # unusually favorable window cannot make an otherwise weak model publishable.
    'minimum_regression_improving_fold_ratio': 0.60,
    'minimum_regression_independent_test_samples': MINIMUM_TEST_SAMPLES,
    # Sanity limits reject effectively constant or implausibly unstable return
    # estimates. They do not make a weak model pass the baseline requirements.
    'minimum_regression_prediction_std': 1e-8,
    'maximum_regression_prediction_to_actual_std_ratio': 3.0,
    'maximum_absolute_predicted_return': 0.50,
}
WALK_FORWARD_CONFIGURATIONS = (
    {'fold_count': 7, 'validation_samples': 50},
    {'fold_count': 5, 'validation_samples': 40},
    {'fold_count': 2, 'validation_samples': 25},
)
SEVERE_CLASS_IMBALANCE_MINORITY_COUNT = 3
SEVERE_CLASS_IMBALANCE_MINORITY_RATIO = 0.10
THRESHOLD_STABILITY_STABLE_STD = 0.05
THRESHOLD_STABILITY_STABLE_RANGE = 0.15
THRESHOLD_STABILITY_MODERATE_STD = 0.10
THRESHOLD_STABILITY_MODERATE_RANGE = 0.30
RANDOM_FOREST_CLASSIFIER_BASELINE_PARAMS = {
    'n_estimators': 200,
    'max_depth': 6,
    'min_samples_split': 2,
    'min_samples_leaf': 3,
    'max_features': 'sqrt',
}
RANDOM_FOREST_CLASSIFIER_PARAM_GRID = (
    RANDOM_FOREST_CLASSIFIER_BASELINE_PARAMS,
    {
        'n_estimators': 200,
        'max_depth': 4,
        'min_samples_split': 6,
        'min_samples_leaf': 4,
        'max_features': 'sqrt',
    },
    {
        'n_estimators': 300,
        'max_depth': 4,
        'min_samples_split': 8,
        'min_samples_leaf': 5,
        'max_features': 'sqrt',
    },
    {
        'n_estimators': 200,
        'max_depth': 3,
        'min_samples_split': 10,
        'min_samples_leaf': 6,
        'max_features': 'sqrt',
    },
    {
        'n_estimators': 300,
        'max_depth': 5,
        'min_samples_split': 6,
        'min_samples_leaf': 4,
        'max_features': 'sqrt',
    },
    {
        'n_estimators': 200,
        'max_depth': 4,
        'min_samples_split': 8,
        'min_samples_leaf': 4,
        'max_features': 0.5,
    },
    {
        'n_estimators': 300,
        'max_depth': 3,
        'min_samples_split': 10,
        'min_samples_leaf': 6,
        'max_features': 0.5,
    },
    {
        'n_estimators': 150,
        'max_depth': 5,
        'min_samples_split': 4,
        'min_samples_leaf': 3,
        'max_features': 0.5,
    },
)

# Small, deterministic regression search space. Every candidate is evaluated on
# the same purged Walk-Forward folds; the independent Test is never referenced
# by this list, model fitting, or model selection.
REGRESSION_MODEL_CANDIDATES = (
    {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 0.1}},
    {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 1.0}},
    {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 10.0}},
    {
        'model': 'Elastic Net',
        'family': 'elastic_net',
        'params': {'alpha': 0.005, 'l1_ratio': 0.1},
    },
    {
        'model': 'Elastic Net',
        'family': 'elastic_net',
        'params': {'alpha': 0.01, 'l1_ratio': 0.5},
    },
    {
        'model': 'Huber Regressor',
        'family': 'huber',
        'params': {'epsilon': 1.35, 'alpha': 0.0001},
    },
    {
        'model': 'Huber Regressor',
        'family': 'huber',
        'params': {'epsilon': 1.50, 'alpha': 0.0001},
    },
    {
        'model': 'Random Forest Regressor',
        'family': 'random_forest',
        'params': {
            'n_estimators': 200,
            'max_depth': 8,
            'min_samples_leaf': 3,
            'max_features': 1.0,
        },
    },
    {
        'model': 'Random Forest Regressor',
        'family': 'random_forest',
        'params': {
            'n_estimators': 200,
            'max_depth': 4,
            'min_samples_leaf': 5,
            'max_features': 0.7,
        },
    },
    {
        'model': 'Histogram Gradient Boosting Regressor',
        'family': 'hist_gradient_boosting',
        'params': {
            'learning_rate': 0.05,
            'max_iter': 100,
            'max_leaf_nodes': 7,
            'l2_regularization': 0.1,
        },
    },
    {
        'model': 'Histogram Gradient Boosting Regressor',
        'family': 'hist_gradient_boosting',
        'params': {
            'learning_rate': 0.03,
            'max_iter': 150,
            'max_leaf_nodes': 7,
            'l2_regularization': 1.0,
        },
    },
)


def _logistic_regression():
    return Pipeline([
        ('scaler', StandardScaler()),
        ('model', LogisticRegression(
            class_weight='balanced',
            max_iter=2000,
            solver='lbfgs',
        )),
    ])


def _random_forest_classifier(params=None):
    classifier_params = {
        **RANDOM_FOREST_CLASSIFIER_BASELINE_PARAMS,
        **(params or {}),
    }
    return RandomForestClassifier(
        **classifier_params,
        class_weight='balanced_subsample',
        random_state=RANDOM_STATE,
        n_jobs=1,
    )


def _random_forest_regressor(params=None):
    regressor_params = {
        'n_estimators': 200,
        'max_depth': 8,
        'min_samples_leaf': 3,
        'max_features': 1.0,
        **(params or {}),
    }
    return RandomForestRegressor(
        **regressor_params,
        random_state=RANDOM_STATE,
        n_jobs=1,
    )


def _regression_model(candidate):
    family = candidate['family']
    params = candidate['params']
    if family == 'ridge':
        return Pipeline([
            ('scaler', StandardScaler()),
            ('model', Ridge(**params)),
        ])
    if family == 'elastic_net':
        return Pipeline([
            ('scaler', StandardScaler()),
            ('model', ElasticNet(
                **params,
                max_iter=10_000,
                selection='cyclic',
                tol=1e-3,
            )),
        ])
    if family == 'huber':
        return Pipeline([
            ('scaler', StandardScaler()),
            ('model', HuberRegressor(**params, max_iter=1_000)),
        ])
    if family == 'random_forest':
        return _random_forest_regressor(params)
    if family == 'hist_gradient_boosting':
        return HistGradientBoostingRegressor(
            **params,
            random_state=RANDOM_STATE,
        )
    raise ValueError(f'Unsupported regression model family: {family}')


CLASSIFICATION_MODELS = (
    ('Logistic Regression', _logistic_regression),
    ('Random Forest Classifier', _random_forest_classifier),
)


def _positive_probability(model, features):
    class_values = list(model.classes_)
    return float(model.predict_proba(features)[0][class_values.index(1)])


def _classification_metrics(labels, predictions, probabilities):
    roc_auc = None
    if len(set(labels)) == 2:
        roc_auc = float(roc_auc_score(labels, probabilities))
    up_recall = float(recall_score(
        labels,
        predictions,
        pos_label=1,
        zero_division=0,
    ))
    down_recall = float(recall_score(
        labels,
        predictions,
        pos_label=0,
        zero_division=0,
    ))
    predicted_up_count = sum(prediction == 1 for prediction in predictions)
    predicted_down_count = len(predictions) - predicted_up_count
    actual_up_count = sum(label == 1 for label in labels)
    actual_down_count = len(labels) - actual_up_count
    return {
        'accuracy': float(accuracy_score(labels, predictions)),
        'balanced_accuracy': _balanced_accuracy(labels, predictions),
        'precision': float(precision_score(labels, predictions, zero_division=0)),
        'recall': up_recall,
        'f1': float(f1_score(labels, predictions, zero_division=0)),
        'macro_f1': float(f1_score(
            labels,
            predictions,
            labels=[0, 1],
            average='macro',
            zero_division=0,
        )),
        'up_recall': up_recall,
        'down_recall': down_recall,
        'specificity': down_recall,
        'minimum_class_recall': float(min(up_recall, down_recall)),
        'actual_up_count': int(actual_up_count),
        'actual_down_count': int(actual_down_count),
        'predicted_up_count': int(predicted_up_count),
        'predicted_down_count': int(predicted_down_count),
        'degenerate_threshold': up_recall == 0 or down_recall == 0,
        'roc_auc': roc_auc,
    }


def _balanced_accuracy(labels, predictions):
    recalls = []
    for class_value in (0, 1):
        class_positions = [
            index
            for index, label in enumerate(labels)
            if label == class_value
        ]
        if class_positions:
            correct = sum(predictions[index] == class_value for index in class_positions)
            recalls.append(correct / len(class_positions))
    return float(sum(recalls) / len(recalls)) if recalls else 0.0


def _predictions_for_threshold(probabilities, threshold):
    return [1 if probability > threshold else 0 for probability in probabilities]


def majority_class_baseline_accuracy(labels):
    class_1_count = sum(label == 1 for label in labels)
    class_0_count = len(labels) - class_1_count
    return float(max(class_0_count, class_1_count) / len(labels)) if labels else 0.0


def _validation_threshold_candidates(probabilities):
    unique_probabilities = sorted({float(probability) for probability in probabilities})
    if not unique_probabilities:
        return (0.5,)

    candidates = {
        unique_probabilities[0] / 2,
        (unique_probabilities[-1] + 1) / 2,
        0.5,
    }
    candidates.update(
        (lower + upper) / 2
        for lower, upper in zip(unique_probabilities, unique_probabilities[1:])
    )
    return tuple(sorted(candidates))


def _roc_auc_for_probabilities(labels, probabilities):
    if len(set(labels)) != 2:
        return None
    return float(roc_auc_score(labels, probabilities))


def _safe_vector_divide(numerator, denominator):
    return np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator, dtype=float),
        where=denominator != 0,
    )


def _classification_metrics_for_thresholds(
    labels,
    probabilities,
    thresholds,
    *,
    roc_auc_value=None,
):
    label_values = np.asarray(labels, dtype=np.int8)
    probability_values = np.asarray(probabilities, dtype=float)
    threshold_values = np.asarray(thresholds, dtype=float)
    predictions = probability_values[np.newaxis, :] > threshold_values[:, np.newaxis]
    actual_up = label_values == 1
    actual_down = ~actual_up

    tp = np.sum(predictions & actual_up, axis=1)
    fp = np.sum(predictions & actual_down, axis=1)
    tn = np.sum((~predictions) & actual_down, axis=1)
    fn = np.sum((~predictions) & actual_up, axis=1)

    up_recall = _safe_vector_divide(tp, tp + fn)
    down_recall = _safe_vector_divide(tn, tn + fp)
    precision = _safe_vector_divide(tp, tp + fp)
    positive_f1 = _safe_vector_divide(2 * tp, (2 * tp) + fp + fn)
    negative_f1 = _safe_vector_divide(2 * tn, (2 * tn) + fp + fn)
    accuracy = _safe_vector_divide(tp + tn, tp + fp + tn + fn)
    balanced_accuracy = (up_recall + down_recall) / 2
    macro_f1 = (positive_f1 + negative_f1) / 2
    predicted_up = tp + fp
    predicted_down = tn + fn
    actual_up_count = int(np.sum(actual_up))
    actual_down_count = int(np.sum(actual_down))

    return [
        {
            'accuracy': float(accuracy[index]),
            'balanced_accuracy': float(balanced_accuracy[index]),
            'precision': float(precision[index]),
            'recall': float(up_recall[index]),
            'f1': float(positive_f1[index]),
            'macro_f1': float(macro_f1[index]),
            'up_recall': float(up_recall[index]),
            'down_recall': float(down_recall[index]),
            'specificity': float(down_recall[index]),
            'minimum_class_recall': float(min(up_recall[index], down_recall[index])),
            'actual_up_count': actual_up_count,
            'actual_down_count': actual_down_count,
            'predicted_up_count': int(predicted_up[index]),
            'predicted_down_count': int(predicted_down[index]),
            'degenerate_threshold': bool(up_recall[index] == 0 or down_recall[index] == 0),
            'roc_auc': roc_auc_value,
        }
        for index in range(len(threshold_values))
    ]


def select_validation_threshold(labels, probabilities, *, roc_auc_value=None):
    """Select a classifier threshold from validation labels and probabilities only."""
    thresholds = _validation_threshold_candidates(probabilities)
    if roc_auc_value is None:
        roc_auc_value = _roc_auc_for_probabilities(labels, probabilities)
    threshold_metrics = _classification_metrics_for_thresholds(
        labels,
        probabilities,
        thresholds,
        roc_auc_value=roc_auc_value,
    )
    candidates = [
        {
            'threshold': float(threshold),
            'metrics': metrics,
        }
        for threshold, metrics in zip(thresholds, threshold_metrics)
    ]

    eligible_candidates = [
        candidate
        for candidate in candidates
        if not candidate['metrics']['degenerate_threshold']
    ]
    candidate_pool = eligible_candidates or candidates
    selected = max(
        candidate_pool,
        key=lambda candidate: (
            candidate['metrics']['macro_f1'],
            candidate['metrics']['balanced_accuracy'],
            candidate['metrics']['minimum_class_recall'],
            -abs(candidate['threshold'] - 0.5),
            -candidate['threshold'],
        ),
    )
    return {
        **selected,
        'threshold_eligible': bool(eligible_candidates),
    }


def _mean_metric(fold_metrics, key, fallback=0.0):
    values = [metrics[key] for metrics in fold_metrics if metrics.get(key) is not None]
    return float(mean(values)) if values else fallback


def _aggregate_fold_metrics(fold_metrics):
    macro_f1_values = [metrics['macro_f1'] for metrics in fold_metrics]
    balanced_accuracy_values = [metrics['balanced_accuracy'] for metrics in fold_metrics]
    minimum_recall_values = [metrics['minimum_class_recall'] for metrics in fold_metrics]
    roc_auc_values = [metrics['roc_auc'] for metrics in fold_metrics if metrics['roc_auc'] is not None]
    degenerate_fold_count = sum(metrics['degenerate_threshold'] for metrics in fold_metrics)
    return {
        'accuracy': _mean_metric(fold_metrics, 'accuracy'),
        'balanced_accuracy': float(mean(balanced_accuracy_values)),
        'precision': _mean_metric(fold_metrics, 'precision'),
        'recall': _mean_metric(fold_metrics, 'recall'),
        'f1': _mean_metric(fold_metrics, 'f1'),
        'macro_f1': float(mean(macro_f1_values)),
        'up_recall': _mean_metric(fold_metrics, 'up_recall'),
        'down_recall': _mean_metric(fold_metrics, 'down_recall'),
        'specificity': _mean_metric(fold_metrics, 'specificity'),
        'minimum_class_recall': float(mean(minimum_recall_values)),
        'roc_auc': float(mean(roc_auc_values)) if roc_auc_values else None,
        'actual_up_count': int(sum(metrics['actual_up_count'] for metrics in fold_metrics)),
        'actual_down_count': int(sum(metrics['actual_down_count'] for metrics in fold_metrics)),
        'predicted_up_count': int(sum(metrics['predicted_up_count'] for metrics in fold_metrics)),
        'predicted_down_count': int(sum(metrics['predicted_down_count'] for metrics in fold_metrics)),
        'degenerate_threshold': degenerate_fold_count > 0,
        'degenerate_fold_count': int(degenerate_fold_count),
        'degenerate_fold_fraction': float(degenerate_fold_count / len(fold_metrics)),
        'fold_count': len(fold_metrics),
        'mean_macro_f1': float(mean(macro_f1_values)),
        'median_macro_f1': float(median(macro_f1_values)),
        'std_macro_f1': float(pstdev(macro_f1_values)),
        'worst_fold_macro_f1': float(min(macro_f1_values)),
        'mean_balanced_accuracy': float(mean(balanced_accuracy_values)),
        'median_balanced_accuracy': float(median(balanced_accuracy_values)),
        'std_balanced_accuracy': float(pstdev(balanced_accuracy_values)),
        'worst_fold_balanced_accuracy': float(min(balanced_accuracy_values)),
        'mean_roc_auc': float(mean(roc_auc_values)) if roc_auc_values else None,
        'median_roc_auc': float(median(roc_auc_values)) if roc_auc_values else None,
        'std_roc_auc': float(pstdev(roc_auc_values)) if roc_auc_values else None,
        'worst_fold_roc_auc': float(min(roc_auc_values)) if roc_auc_values else None,
        'mean_minimum_class_recall': float(mean(minimum_recall_values)),
        'worst_fold_minimum_class_recall': float(min(minimum_recall_values)),
    }


def _stable_metric(aggregate_metrics, metric_name):
    return float(
        (aggregate_metrics[f'median_{metric_name}'] * 0.50)
        + (aggregate_metrics[f'mean_{metric_name}'] * 0.30)
        + (aggregate_metrics[f'worst_fold_{metric_name}'] * 0.20)
    )


def _threshold_stability(thresholds):
    threshold_values = [float(threshold) for threshold in thresholds]
    threshold_std = float(pstdev(threshold_values)) if threshold_values else 0.0
    threshold_range = (
        float(max(threshold_values) - min(threshold_values))
        if threshold_values
        else 0.0
    )
    if len(threshold_values) < 2:
        status = 'insufficient_folds'
    elif (
        threshold_std <= THRESHOLD_STABILITY_STABLE_STD
        and threshold_range <= THRESHOLD_STABILITY_STABLE_RANGE
    ):
        status = 'stable'
    elif (
        threshold_std <= THRESHOLD_STABILITY_MODERATE_STD
        and threshold_range <= THRESHOLD_STABILITY_MODERATE_RANGE
    ):
        status = 'moderate'
    else:
        status = 'unstable'
    return {
        'status': status,
        'fold_thresholds': threshold_values,
        'mean': float(mean(threshold_values)) if threshold_values else None,
        'median': float(median(threshold_values)) if threshold_values else None,
        'standard_deviation': threshold_std,
        'range': threshold_range,
        'rule': (
            'Stable when standard deviation <= 0.05 and range <= 0.15; '
            'moderate when standard deviation <= 0.10 and range <= 0.30; otherwise unstable.'
        ),
    }


def _walk_forward_selection_score(metrics, threshold_stability):
    mean_auc = metrics['mean_roc_auc'] if metrics['mean_roc_auc'] is not None else 0.5
    return float(
        (metrics['mean_macro_f1'] * 0.40)
        + (metrics['mean_balanced_accuracy'] * 0.25)
        + (mean_auc * 0.20)
        + (metrics['worst_fold_minimum_class_recall'] * 0.15)
        - (metrics['std_macro_f1'] * 0.10)
        - (threshold_stability['standard_deviation'] * 0.05)
        - (metrics['degenerate_fold_fraction'] * 0.10)
    )


def select_walk_forward_threshold(fold_predictions):
    """Select one threshold from purged walk-forward Validation predictions only."""
    per_fold_thresholds = [
        select_validation_threshold(
            fold['labels'],
            fold['probabilities'],
            roc_auc_value=fold['roc_auc'],
        )
        for fold in fold_predictions
    ]
    candidates = {value / 100 for value in range(1, 100)}
    candidates.update(result['threshold'] for result in per_fold_thresholds)
    sorted_candidates = tuple(sorted(candidates))
    metrics_by_fold_and_threshold = [
        _classification_metrics_for_thresholds(
            fold['labels'],
            fold['probabilities'],
            sorted_candidates,
            roc_auc_value=fold['roc_auc'],
        )
        for fold in fold_predictions
    ]

    candidate_evaluations = []
    for threshold_index, threshold in enumerate(sorted_candidates):
        metrics_by_fold = [
            fold_metrics[threshold_index]
            for fold_metrics in metrics_by_fold_and_threshold
        ]
        aggregate_metrics = _aggregate_fold_metrics(metrics_by_fold)
        candidate_evaluations.append({
            'threshold': float(threshold),
            'metrics': aggregate_metrics,
            'metrics_by_fold': metrics_by_fold,
            'stable_macro_f1': _stable_metric(aggregate_metrics, 'macro_f1'),
            'stable_balanced_accuracy': _stable_metric(aggregate_metrics, 'balanced_accuracy'),
        })

    minimum_degenerate_folds = min(
        candidate['metrics']['degenerate_fold_count']
        for candidate in candidate_evaluations
    )
    candidate_pool = [
        candidate
        for candidate in candidate_evaluations
        if candidate['metrics']['degenerate_fold_count'] == minimum_degenerate_folds
    ]
    fold_threshold_values = [result['threshold'] for result in per_fold_thresholds]
    stability = _threshold_stability(fold_threshold_values)
    selected = max(
        candidate_pool,
        key=lambda candidate: (
            candidate['stable_macro_f1'],
            candidate['stable_balanced_accuracy'],
            candidate['metrics']['worst_fold_minimum_class_recall'],
            -candidate['metrics']['std_macro_f1'],
            -abs(candidate['threshold'] - stability['median']),
            -abs(candidate['threshold'] - 0.5),
            -candidate['threshold'],
        ),
    )

    serialized_folds = []
    for fold, fold_threshold, fold_metrics in zip(
        fold_predictions,
        per_fold_thresholds,
        selected['metrics_by_fold'],
    ):
        serialized_folds.append({
            'fold': fold['fold']['fold'],
            'training_samples': fold['fold']['training_samples'],
            'validation_samples': fold['fold']['validation_samples'],
            'gap_size': fold['fold']['gap_size'],
            'purge_safe': fold['fold']['purge_safe'],
            'severe_class_imbalance': fold['fold']['severe_class_imbalance'],
            'optimal_threshold': fold_threshold['threshold'],
            'optimal_threshold_eligible': fold_threshold['threshold_eligible'],
            'selected_threshold': selected['threshold'],
            **fold_metrics,
        })

    return {
        'threshold': selected['threshold'],
        'threshold_eligible': minimum_degenerate_folds < len(fold_predictions),
        'non_degenerate_all_folds': minimum_degenerate_folds == 0,
        'metrics': selected['metrics'],
        'fold_metrics': serialized_folds,
        'threshold_stability': stability,
    }


def _fit_classifier_fold(model_factory, fold):
    model = model_factory()
    model.fit(fold['x_train'], fold['y_classification_train'])
    probabilities = model.predict_proba(fold['x_validation'])[:, list(model.classes_).index(1)]
    labels = fold['y_classification_validation']
    return {
        'fold': fold,
        'labels': labels,
        'probabilities': probabilities,
        'roc_auc': _roc_auc_for_probabilities(labels, probabilities),
    }


def _evaluate_fold_predictions(fold_predictions):
    threshold_result = select_walk_forward_threshold(fold_predictions)
    return {
        **threshold_result,
        'selection_score': _walk_forward_selection_score(
            threshold_result['metrics'],
            threshold_result['threshold_stability'],
        ),
    }


def evaluate_classifier_walk_forward(model_factory, folds):
    fold_predictions = [
        _fit_classifier_fold(model_factory, fold)
        for fold in folds
    ]
    return _evaluate_fold_predictions(fold_predictions)


def _fit_random_forest_fold_task(task):
    candidate_index, fold_index, params, fold = task
    fold_prediction = _fit_classifier_fold(
        lambda: _random_forest_classifier(params),
        fold,
    )
    return candidate_index, fold_index, fold_prediction


def _random_forest_worker_count(task_count):
    configured_workers = max(
        int(getattr(settings, 'PREDICTION_RF_MAX_WORKERS', 4)),
        1,
    )
    return min(configured_workers, task_count)


def tune_random_forest_classifier(folds):
    """Tune Random Forest parameters and threshold using walk-forward folds only."""
    tasks = [
        (candidate_index, fold_index, params, fold)
        for candidate_index, params in enumerate(RANDOM_FOREST_CLASSIFIER_PARAM_GRID)
        for fold_index, fold in enumerate(folds)
    ]
    worker_count = _random_forest_worker_count(len(tasks))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        task_results = list(executor.map(_fit_random_forest_fold_task, tasks))

    predictions_by_candidate = [
        []
        for _params in RANDOM_FOREST_CLASSIFIER_PARAM_GRID
    ]
    for candidate_index, fold_index, fold_prediction in task_results:
        predictions_by_candidate[candidate_index].append((fold_index, fold_prediction))

    evaluations = []
    for candidate_index, params in enumerate(RANDOM_FOREST_CLASSIFIER_PARAM_GRID):
        ordered_fold_predictions = [
            fold_prediction
            for _fold_index, fold_prediction in sorted(
                predictions_by_candidate[candidate_index],
                key=lambda item: item[0],
            )
        ]
        evaluation = _evaluate_fold_predictions(
            ordered_fold_predictions,
        )
        evaluations.append({
            **evaluation,
            'params': dict(params),
            'candidate_index': candidate_index,
            'parallel_strategy': 'candidate_fold_threads',
            'parallel_workers': worker_count,
            'random_forest_n_jobs': 1,
        })

    eligible_evaluations = [
        evaluation
        for evaluation in evaluations
        if evaluation['threshold_eligible']
    ]
    evaluation_pool = eligible_evaluations or evaluations
    return max(
        evaluation_pool,
        key=lambda evaluation: (
            evaluation['selection_score'],
            -evaluation['metrics']['degenerate_fold_count'],
            evaluation['metrics']['mean_macro_f1'],
            evaluation['metrics']['mean_balanced_accuracy'],
            evaluation['metrics']['worst_fold_minimum_class_recall'],
            -evaluation['candidate_index'],
        ),
    )


def _confidence(probability_increase, test_metrics):
    probability_strength = abs(probability_increase - 0.5) * 2
    auc_component = (
        test_metrics['roc_auc']
        if test_metrics['roc_auc'] is not None
        else test_metrics['accuracy']
    )
    test_quality = (test_metrics['accuracy'] + test_metrics['f1'] + auc_component) / 3
    score = (probability_strength * 0.55) + (test_quality * 0.45)
    if score >= 0.70 and test_quality >= 0.60:
        label = 'High'
    elif score >= 0.45 and test_quality >= 0.50:
        label = 'Medium'
    else:
        label = 'Low'
    return label, {
        'score': float(score),
        'probability_strength': float(probability_strength),
        'test_quality': float(test_quality),
        'performance_source': 'independent_test',
        'rule': 'High: score >= 0.70 and test quality >= 0.60; Medium: score >= 0.45 and test quality >= 0.50; otherwise Low.',
    }


def build_purged_chronological_split(dataset):
    """Return chronological Train/Validation/Test slices separated by horizon-sized gaps."""
    sample_count = dataset.sample_count
    gap_size = dataset.horizon
    partitionable_samples = max(sample_count - (gap_size * 2), 0)
    training_samples = int(partitionable_samples * TRAINING_FRACTION)
    validation_samples = int(partitionable_samples * VALIDATION_FRACTION)
    test_samples = partitionable_samples - training_samples - validation_samples

    training_end = training_samples
    validation_start = training_end + gap_size
    validation_end = validation_start + validation_samples
    test_start = validation_end + gap_size
    test_end = test_start + test_samples

    split = {
        'x_train': dataset.features[:training_end],
        'x_validation': dataset.features[validation_start:validation_end],
        'x_test': dataset.features[test_start:test_end],
        'x_regression_train': dataset.regression_features[:training_end],
        'x_regression_validation': dataset.regression_features[validation_start:validation_end],
        'x_regression_test': dataset.regression_features[test_start:test_end],
        'y_classification_train': dataset.classification_labels[:training_end],
        'y_classification_validation': dataset.classification_labels[validation_start:validation_end],
        'y_classification_test': dataset.classification_labels[test_start:test_end],
        'y_regression_train': dataset.regression_labels[:training_end],
        'y_regression_validation': dataset.regression_labels[validation_start:validation_end],
        'y_regression_test': dataset.regression_labels[test_start:test_end],
        'training_samples': training_samples,
        'validation_samples': validation_samples,
        'test_samples': test_samples,
        'development_end': validation_end,
        'development_samples': validation_end,
        'final_test_start': test_start,
        'gap_size': gap_size,
        'first_gap_samples': len(dataset.features[training_end:validation_start]),
        'second_gap_samples': len(dataset.features[validation_end:test_start]),
        'purged_samples': sample_count - training_samples - validation_samples - test_samples,
    }

    train_last_index = dataset.sample_indices[training_end - 1] if training_samples else None
    validation_first_index = dataset.sample_indices[validation_start] if validation_samples else None
    validation_last_index = dataset.sample_indices[validation_end - 1] if validation_samples else None
    test_first_index = dataset.sample_indices[test_start] if test_samples else None
    train_label_endpoint = train_last_index + dataset.horizon if train_last_index is not None else None
    validation_label_endpoint = (
        validation_last_index + dataset.horizon
        if validation_last_index is not None
        else None
    )
    train_validation_safe = (
        train_label_endpoint is None
        or validation_first_index is None
        or train_label_endpoint < validation_first_index
    )
    validation_test_safe = (
        validation_label_endpoint is None
        or test_first_index is None
        or validation_label_endpoint < test_first_index
    )
    if not train_validation_safe or not validation_test_safe:
        raise RuntimeError('Chronological split purge invariant failed.')

    split['boundaries'] = {
        'train_last_feature_index': train_last_index,
        'train_last_label_endpoint_index': train_label_endpoint,
        'validation_first_feature_index': validation_first_index,
        'validation_last_feature_index': validation_last_index,
        'validation_last_label_endpoint_index': validation_label_endpoint,
        'test_first_feature_index': test_first_index,
        'train_validation_purge_safe': train_validation_safe,
        'validation_test_purge_safe': validation_test_safe,
    }
    return split


def _walk_forward_configuration(development_samples, gap_size):
    for configuration in WALK_FORWARD_CONFIGURATIONS:
        initial_training_samples = (
            development_samples
            - gap_size
            - (configuration['fold_count'] * configuration['validation_samples'])
        )
        if initial_training_samples >= MINIMUM_TRAINING_SAMPLES:
            return {
                **configuration,
                'initial_training_samples': initial_training_samples,
            }
    return None


def build_purged_walk_forward_folds(dataset, split):
    """Build expanding chronological folds entirely before the independent Test."""
    development_samples = split['development_samples']
    gap_size = dataset.horizon
    configuration = _walk_forward_configuration(development_samples, gap_size)
    if configuration is None:
        return ()

    fold_count = configuration['fold_count']
    validation_samples = configuration['validation_samples']
    folds = []
    for fold_index in range(fold_count):
        validation_start = (
            development_samples
            - ((fold_count - fold_index) * validation_samples)
        )
        training_end = validation_start - gap_size
        validation_end = validation_start + validation_samples

        train_last_index = dataset.sample_indices[training_end - 1]
        validation_first_index = dataset.sample_indices[validation_start]
        train_label_endpoint = train_last_index + dataset.horizon
        purge_safe = train_label_endpoint < validation_first_index
        if not purge_safe:
            raise RuntimeError('Walk-forward fold purge invariant failed.')

        validation_labels = dataset.classification_labels[validation_start:validation_end]
        actual_up_count = sum(label == 1 for label in validation_labels)
        actual_down_count = len(validation_labels) - actual_up_count
        minority_count = min(actual_up_count, actual_down_count)
        minority_ratio = minority_count / len(validation_labels)
        folds.append({
            'fold': fold_index + 1,
            'x_train': dataset.features[:training_end],
            'x_validation': dataset.features[validation_start:validation_end],
            'x_regression_train': dataset.regression_features[:training_end],
            'x_regression_validation': dataset.regression_features[validation_start:validation_end],
            'y_classification_train': dataset.classification_labels[:training_end],
            'y_classification_validation': validation_labels,
            'y_regression_train': dataset.regression_labels[:training_end],
            'y_regression_validation': dataset.regression_labels[validation_start:validation_end],
            'training_samples': training_end,
            'validation_samples': validation_samples,
            'gap_size': gap_size,
            'actual_up_count': int(actual_up_count),
            'actual_down_count': int(actual_down_count),
            'minority_class_count': int(minority_count),
            'minority_class_ratio': float(minority_ratio),
            'severe_class_imbalance': (
                minority_count < SEVERE_CLASS_IMBALANCE_MINORITY_COUNT
                or minority_ratio < SEVERE_CLASS_IMBALANCE_MINORITY_RATIO
            ),
            'purge_safe': purge_safe,
            'boundaries': {
                'train_last_feature_index': train_last_index,
                'train_last_label_endpoint_index': train_label_endpoint,
                'validation_first_feature_index': validation_first_index,
                'validation_last_feature_index': dataset.sample_indices[validation_end - 1],
            },
        })
    return tuple(folds)


def _serialize_walk_forward_fold(fold):
    return {
        'fold': fold['fold'],
        'training_samples': fold['training_samples'],
        'validation_samples': fold['validation_samples'],
        'gap_size': fold['gap_size'],
        'actual_up_count': fold['actual_up_count'],
        'actual_down_count': fold['actual_down_count'],
        'minority_class_count': fold['minority_class_count'],
        'minority_class_ratio': fold['minority_class_ratio'],
        'severe_class_imbalance': fold['severe_class_imbalance'],
        'purge_safe': fold['purge_safe'],
        'boundaries': fold['boundaries'],
    }


def _walk_forward_reliability(evaluation, folds):
    issues = []
    severe_imbalance_folds = [
        fold['fold']
        for fold in folds
        if fold['severe_class_imbalance']
    ]
    if len(folds) < 3:
        issues.append('limited_walk_forward_folds')
    if severe_imbalance_folds:
        issues.append('severe_validation_class_imbalance')
    if evaluation['metrics']['degenerate_fold_count']:
        issues.append('degenerate_validation_fold_prediction')
    if evaluation['threshold_stability']['status'] == 'unstable':
        issues.append('unstable_fold_thresholds')
    elif evaluation['threshold_stability']['status'] == 'moderate':
        issues.append('moderate_fold_threshold_dispersion')
    if evaluation['metrics']['worst_fold_minimum_class_recall'] < 0.30:
        issues.append('low_worst_fold_class_recall')

    if (
        severe_imbalance_folds
        or evaluation['metrics']['degenerate_fold_count']
        or evaluation['threshold_stability']['status'] == 'unstable'
        or evaluation['metrics']['worst_fold_minimum_class_recall'] < 0.10
    ):
        level = 'Low'
    elif issues or evaluation['metrics']['worst_fold_minimum_class_recall'] < 0.30:
        level = 'Limited'
    else:
        level = 'Stable'
    return {
        'level': level,
        'reliable': level == 'Stable',
        'source': 'purged_walk_forward_validation',
        'issues': issues,
        'severe_class_imbalance_folds': severe_imbalance_folds,
        'degenerate_fold_count': evaluation['metrics']['degenerate_fold_count'],
        'worst_fold_minimum_class_recall': evaluation['metrics']['worst_fold_minimum_class_recall'],
        'threshold_stability': evaluation['threshold_stability']['status'],
        'rule': (
            'Low when severe class imbalance, degenerate folds, unstable thresholds, or '
            'worst-fold minimum class recall below 0.10 is observed; Limited for fewer '
            'than three folds or worst-fold minimum class recall below 0.30; otherwise Stable.'
        ),
    }


def _ml_metadata(
    dataset,
    split,
    folds=(),
    random_forest_params=None,
    reliability=None,
    regression_dataset=None,
    regression_split=None,
    regression_folds=(),
):
    regression_dataset = regression_dataset or dataset
    regression_split = regression_split or split
    return {
        'feature_names': list(dataset.feature_names),
        'regression_feature_names': list(regression_dataset.regression_feature_names),
        'classification_forecast_horizon': dataset.horizon,
        'regression_forecast_horizon': regression_dataset.horizon,
        'classification_purge_gap': split['gap_size'],
        'regression_purge_gap': regression_split['gap_size'],
        'usable_labeled_samples': dataset.sample_count,
        'classification_usable_labeled_samples': dataset.sample_count,
        'regression_usable_labeled_samples': regression_dataset.sample_count,
        'discarded_labeled_rows': dataset.discarded_labeled_rows,
        'classification_discarded_labeled_rows': dataset.discarded_labeled_rows,
        'regression_discarded_labeled_rows': regression_dataset.discarded_labeled_rows,
        'training_samples': split['development_samples'],
        'validation_samples': sum(fold['validation_samples'] for fold in folds),
        'test_samples': split['test_samples'],
        'development_samples': split['development_samples'],
        'gap_size': split['gap_size'],
        'first_gap_samples': split['first_gap_samples'],
        'second_gap_samples': split['second_gap_samples'],
        'purged_samples': split['purged_samples'],
        'training_fraction': TRAINING_FRACTION,
        'validation_fraction': VALIDATION_FRACTION,
        'test_fraction': TEST_FRACTION,
        'minimum_training_samples': MINIMUM_TRAINING_SAMPLES,
        'minimum_validation_samples': MINIMUM_VALIDATION_SAMPLES,
        'minimum_test_samples': MINIMUM_TEST_SAMPLES,
        'boundaries': split['boundaries'],
        'walk_forward_fold_count': len(folds),
        'walk_forward_folds': [
            _serialize_walk_forward_fold(fold)
            for fold in folds
        ],
        'walk_forward_validation_samples_total': sum(
            fold['validation_samples']
            for fold in folds
        ),
        'walk_forward_type': 'expanding',
        'walk_forward_shuffle': False,
        'fold_scaler_fit_scope': 'fold_training_only',
        'final_classifier_fit_scope': 'development_data_only',
        'regression_candidate_selection_scope': 'purged_walk_forward_validation_only',
        'regression_fold_preprocessing_fit_scope': 'each_fold_training_only',
        'final_regressor_fit_scope': 'development_data_only_before_independent_test',
        'final_test_untouched': True,
        'independent_test_role': 'final_evaluation_and_publication_gate_only',
        'independent_test_used_for_model_selection': False,
        'independent_test_used_for_hyperparameter_tuning': False,
        'independent_test_used_for_threshold_selection': False,
        'classifier_refit_after_independent_test': False,
        'regressor_refit_after_independent_test': False,
        'independent_test_used_for_regression_model_selection': False,
        'independent_test_used_for_regression_hyperparameter_tuning': False,
        'threshold_source': 'purged_walk_forward_validation',
        'model_selection_source': 'purged_walk_forward_validation',
        'walk_forward_selection_formula': (
            '0.40 mean Macro F1 + 0.25 mean Balanced Accuracy + 0.20 mean ROC-AUC '
            '+ 0.15 worst-fold minimum class recall - 0.10 Macro F1 standard deviation '
            '- 0.05 threshold standard deviation - 0.10 degenerate-fold fraction.'
        ),
        'reliability': reliability,
        'regression_evaluation_split': {
            'training_samples': regression_split['training_samples'],
            'validation_samples': regression_split['validation_samples'],
            'test_samples': regression_split['test_samples'],
            'walk_forward_fold_count': len(regression_folds),
            'gap_size': regression_split['gap_size'],
            'boundaries': regression_split['boundaries'],
        },
        'classification_label': (
            f'1 when close[t + {dataset.horizon}] / close[t] - 1 > 0, otherwise 0'
        ),
        'regression_label': (
            f'close[t + {regression_dataset.horizon}] / close[t] - 1'
        ),
        'regression_target_price_basis': (
            'Stored provider close values; no separate split/dividend adjustment is applied '
            'inside the Prediction feature service.'
        ),
        'random_forest_params': (
            {
                **random_forest_params,
                'class_weight': 'balanced_subsample',
                'random_state': RANDOM_STATE,
                'n_jobs': 1,
            }
            if random_forest_params is not None
            else None
        ),
        'random_forest_candidate_count': len(RANDOM_FOREST_CLASSIFIER_PARAM_GRID),
        'random_forest_parallel_strategy': 'candidate_fold_threads',
        'random_forest_parallel_workers': (
            _random_forest_worker_count(len(RANDOM_FOREST_CLASSIFIER_PARAM_GRID) * len(folds))
            if folds
            else 0
        ),
        'random_forest_nested_parallelism': False,
        'hyperparameter_source': (
            'purged_walk_forward_validation'
            if random_forest_params is not None
            else None
        ),
    }


def _unavailable_result(
    reason,
    dataset,
    split,
    folds=(),
    regression_dataset=None,
    regression_split=None,
    regression_folds=(),
):
    regression_dataset = regression_dataset or dataset
    regression_split = regression_split or split
    return {
        'classification_forecast_horizon': dataset.horizon,
        'regression_forecast_horizon': regression_dataset.horizon,
        'classification_purge_gap': split['gap_size'],
        'regression_purge_gap': regression_split['gap_size'],
        'classification_prediction': {
            'forecast_horizon': dataset.horizon,
            'purge_gap': split['gap_size'],
            'available': False,
        },
        'regression_prediction': {
            'forecast_horizon': regression_dataset.horizon,
            'purge_gap': regression_split['gap_size'],
            'available': False,
        },
        'prediction_available': False,
        'prediction_unavailable_reason': reason,
        'predicted_direction': None,
        'probability_increase': None,
        'expected_return': None,
        'predicted_price': None,
        'confidence': None,
        'selected_model': None,
        'selected_threshold': None,
        'selected_candidate_model': None,
        'selected_candidate_threshold': None,
        'selected_regression_candidate_model': None,
        'selected_regression_candidate_params': None,
        'regression_prediction_available': False,
        'regression_prediction_unavailable_reason': reason,
        'regression_model': None,
        'prediction_quality_gate': None,
        'walk_forward_quality_gate': None,
        'independent_test_quality_gate': None,
        'final_classification_quality_gate': None,
        'regression_walk_forward_quality_gate': None,
        'regression_independent_test_quality_gate': None,
        'final_regression_quality_gate': None,
        'model_metrics': None,
        'model_comparison': [],
        'confidence_details': None,
        'ml_reliability': None,
        'ml_metadata': _ml_metadata(
            dataset,
            split,
            folds=folds,
            regression_dataset=regression_dataset,
            regression_split=regression_split,
            regression_folds=regression_folds,
        ),
    }


def _regression_metrics(labels, predictions):
    regression_r2 = float(r2_score(labels, predictions)) if len(labels) > 1 else None
    return {
        'mae': float(mean_absolute_error(labels, predictions)),
        'rmse': float(sqrt(mean_squared_error(labels, predictions))),
        'r2': regression_r2 if regression_r2 is not None and isfinite(regression_r2) else None,
    }


def calculate_predicted_price(current_price, expected_return):
    if current_price is None or expected_return is None:
        return None
    current_price = float(current_price)
    expected_return = float(expected_return)
    if not isfinite(current_price) or not isfinite(expected_return):
        return None
    return float(current_price * (1 + expected_return))


def _walk_forward_majority_baseline(folds):
    correct_predictions = 0
    sample_count = 0
    fold_diagnostics = []
    for fold in folds:
        training_labels = fold['y_classification_train']
        validation_labels = fold['y_classification_validation']
        training_up_count = sum(label == 1 for label in training_labels)
        training_down_count = len(training_labels) - training_up_count
        majority_class = 1 if training_up_count > training_down_count else 0
        fold_correct = sum(label == majority_class for label in validation_labels)
        correct_predictions += fold_correct
        sample_count += len(validation_labels)
        fold_diagnostics.append({
            'fold': fold['fold'],
            'training_majority_class': 'UP' if majority_class == 1 else 'DOWN',
            'validation_samples': len(validation_labels),
            'accuracy': float(fold_correct / len(validation_labels)) if validation_labels else 0.0,
        })
    return {
        'name': 'training_majority_class',
        'accuracy': float(correct_predictions / sample_count) if sample_count else 0.0,
        'sample_count': sample_count,
        'folds': fold_diagnostics,
    }


def evaluate_classification_quality_gate(metrics, folds):
    """Evaluate deployability using only purged walk-forward Validation outputs."""
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    baseline = _walk_forward_majority_baseline(folds)
    actual_up_count = int(metrics.get('actual_up_count', 0))
    actual_down_count = int(metrics.get('actual_down_count', 0))
    predicted_up_count = int(metrics.get('predicted_up_count', 0))
    predicted_down_count = int(metrics.get('predicted_down_count', 0))
    sample_count = actual_up_count + actual_down_count
    balanced_accuracy = float(metrics.get('balanced_accuracy', 0.0))
    macro_f1 = float(metrics.get('macro_f1', 0.0))
    model_accuracy = float(metrics.get('accuracy', 0.0))
    baseline_margin = model_accuracy - baseline['accuracy']
    fold_metrics = metrics.get('fold_metrics', ())
    single_class_actual_folds = [
        fold['fold']
        for fold in fold_metrics
        if fold.get('actual_up_count', 0) == 0 or fold.get('actual_down_count', 0) == 0
    ]
    single_class_prediction_folds = [
        fold['fold']
        for fold in fold_metrics
        if fold.get('predicted_up_count', 0) == 0 or fold.get('predicted_down_count', 0) == 0
    ]
    reasons = []
    reason_codes = []

    def reject(code, message):
        reason_codes.append(code)
        reasons.append(message)

    if sample_count < thresholds['minimum_oos_samples']:
        reject(
            'insufficient_oos_samples',
            f'Only {sample_count} walk-forward out-of-sample predictions are available; '
            f'at least {thresholds["minimum_oos_samples"]} are required.',
        )
    if actual_up_count == 0 or actual_down_count == 0 or single_class_actual_folds:
        reject(
            'single_class_actual_labels',
            'One or more walk-forward out-of-sample windows contain only one actual class.',
        )
    if predicted_up_count == 0 or predicted_down_count == 0 or single_class_prediction_folds:
        reject(
            'single_class_predictions',
            'One or more walk-forward out-of-sample windows predict only one class.',
        )
    if balanced_accuracy < thresholds['minimum_balanced_accuracy']:
        reject(
            'balanced_accuracy_below_minimum',
            f'Walk-forward balanced accuracy {balanced_accuracy:.3f} is below the '
            f'{thresholds["minimum_balanced_accuracy"]:.3f} minimum.',
        )
    if macro_f1 < thresholds['minimum_macro_f1']:
        reject(
            'macro_f1_below_minimum',
            f'Walk-forward Macro F1 {macro_f1:.3f} is below the '
            f'{thresholds["minimum_macro_f1"]:.3f} minimum.',
        )
    if baseline_margin < thresholds['minimum_accuracy_improvement_over_baseline']:
        reject(
            'did_not_beat_majority_baseline',
            f'Model accuracy {model_accuracy:.3f} did not exceed the training-majority '
            f'baseline {baseline["accuracy"]:.3f} by at least '
            f'{thresholds["minimum_accuracy_improvement_over_baseline"]:.3f}.',
        )

    return {
        'passed': not reasons,
        'source': 'purged_walk_forward_validation',
        'reason_codes': reason_codes,
        'reasons': reasons,
        'thresholds': {
            'minimum_oos_samples': thresholds['minimum_oos_samples'],
            'minimum_balanced_accuracy': thresholds['minimum_balanced_accuracy'],
            'minimum_macro_f1': thresholds['minimum_macro_f1'],
            'minimum_accuracy_improvement_over_baseline': (
                thresholds['minimum_accuracy_improvement_over_baseline']
            ),
        },
        'observed': {
            'oos_samples': sample_count,
            'actual_up_count': actual_up_count,
            'actual_down_count': actual_down_count,
            'predicted_up_count': predicted_up_count,
            'predicted_down_count': predicted_down_count,
            'balanced_accuracy': balanced_accuracy,
            'macro_f1': macro_f1,
            'accuracy': model_accuracy,
            'baseline_accuracy': baseline['accuracy'],
            'accuracy_improvement_over_baseline': float(baseline_margin),
            'single_class_actual_folds': single_class_actual_folds,
            'single_class_prediction_folds': single_class_prediction_folds,
        },
        'baseline': baseline,
    }


def evaluate_independent_test_quality_gate(metrics):
    """Gate a frozen classifier using independent Test predictions only."""
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    actual_up_count = int(metrics.get('actual_up_count', 0))
    actual_down_count = int(metrics.get('actual_down_count', 0))
    predicted_up_count = int(metrics.get('predicted_up_count', 0))
    predicted_down_count = int(metrics.get('predicted_down_count', 0))
    sample_count = actual_up_count + actual_down_count
    actual_minority_count = min(actual_up_count, actual_down_count)
    predicted_minority_count = min(predicted_up_count, predicted_down_count)
    actual_minority_ratio = actual_minority_count / sample_count if sample_count else 0.0
    predicted_minority_ratio = predicted_minority_count / sample_count if sample_count else 0.0
    predicted_to_actual_minority_ratio = (
        predicted_minority_ratio / actual_minority_ratio
        if actual_minority_ratio > 0
        else 0.0
    )
    balanced_accuracy = float(metrics.get('balanced_accuracy', 0.0))
    macro_f1 = float(metrics.get('macro_f1', 0.0))
    minimum_class_recall = float(metrics.get('minimum_class_recall', 0.0))
    model_accuracy = float(metrics.get('accuracy', 0.0))
    baseline_accuracy = (
        max(actual_up_count, actual_down_count) / sample_count
        if sample_count
        else 0.0
    )
    baseline_margin = model_accuracy - baseline_accuracy
    distribution_check_applied = (
        actual_minority_ratio
        >= thresholds['minimum_actual_minority_ratio_for_distribution_check']
    )
    extreme_prediction_skew = (
        distribution_check_applied
        and predicted_to_actual_minority_ratio
        < thresholds['minimum_predicted_to_actual_minority_ratio']
    )
    reasons = []
    reason_codes = []

    def reject(code, message):
        reason_codes.append(code)
        reasons.append(message)

    if sample_count < thresholds['minimum_independent_test_samples']:
        reject(
            'insufficient_test_samples',
            f'Only {sample_count} independent Test predictions are available; at least '
            f'{thresholds["minimum_independent_test_samples"]} are required.',
        )
    if actual_up_count == 0 or actual_down_count == 0:
        reject(
            'single_class_actual_labels',
            'Independent Test actual labels contain only one class.',
        )
    if predicted_up_count == 0 or predicted_down_count == 0:
        reject(
            'single_class_predictions',
            'Independent Test predictions contain only one class.',
        )
    if balanced_accuracy < thresholds['minimum_balanced_accuracy']:
        reject(
            'balanced_accuracy_below_minimum',
            f'Independent Test balanced accuracy {balanced_accuracy:.3f} is below the '
            f'{thresholds["minimum_balanced_accuracy"]:.3f} minimum.',
        )
    if macro_f1 < thresholds['minimum_macro_f1']:
        reject(
            'macro_f1_below_minimum',
            f'Independent Test Macro F1 {macro_f1:.3f} is below the '
            f'{thresholds["minimum_macro_f1"]:.3f} minimum.',
        )
    if minimum_class_recall < thresholds['minimum_independent_test_class_recall']:
        reject(
            'minimum_class_recall_below_minimum',
            f'Independent Test minimum class recall {minimum_class_recall:.3f} is below the '
            f'{thresholds["minimum_independent_test_class_recall"]:.3f} minimum.',
        )
    if baseline_margin < thresholds['minimum_accuracy_improvement_over_baseline']:
        reject(
            'did_not_beat_majority_baseline',
            f'Independent Test accuracy {model_accuracy:.3f} did not exceed the majority-class '
            f'baseline {baseline_accuracy:.3f} by at least '
            f'{thresholds["minimum_accuracy_improvement_over_baseline"]:.3f}.',
        )
    if extreme_prediction_skew:
        reject(
            'prediction_distribution_extreme_skew',
            f'Independent Test predicted minority ratio {predicted_minority_ratio:.3f} is '
            f'disproportionately small relative to the actual minority ratio '
            f'{actual_minority_ratio:.3f}.',
        )

    return {
        'passed': not reasons,
        'source': 'independent_test_publication_gate',
        'role': 'publication_only',
        'reason_codes': reason_codes,
        'reasons': reasons,
        'thresholds': {
            'minimum_test_samples': thresholds['minimum_independent_test_samples'],
            'minimum_balanced_accuracy': thresholds['minimum_balanced_accuracy'],
            'minimum_macro_f1': thresholds['minimum_macro_f1'],
            'minimum_class_recall': thresholds['minimum_independent_test_class_recall'],
            'minimum_accuracy_improvement_over_baseline': (
                thresholds['minimum_accuracy_improvement_over_baseline']
            ),
            'minimum_actual_minority_ratio_for_distribution_check': (
                thresholds['minimum_actual_minority_ratio_for_distribution_check']
            ),
            'minimum_predicted_to_actual_minority_ratio': (
                thresholds['minimum_predicted_to_actual_minority_ratio']
            ),
        },
        'observed': {
            'test_samples': sample_count,
            'actual_up_count': actual_up_count,
            'actual_down_count': actual_down_count,
            'predicted_up_count': predicted_up_count,
            'predicted_down_count': predicted_down_count,
            'balanced_accuracy': balanced_accuracy,
            'macro_f1': macro_f1,
            'minimum_class_recall': minimum_class_recall,
            'accuracy': model_accuracy,
            'baseline_accuracy': float(baseline_accuracy),
            'accuracy_improvement_over_baseline': float(baseline_margin),
            'actual_minority_ratio': float(actual_minority_ratio),
            'predicted_minority_ratio': float(predicted_minority_ratio),
            'predicted_to_actual_minority_ratio': float(predicted_to_actual_minority_ratio),
            'distribution_check_applied': distribution_check_applied,
        },
        'baseline': {
            'name': 'independent_test_majority_class',
            'accuracy': float(baseline_accuracy),
        },
    }


def evaluate_final_classification_quality_gate(
    walk_forward_quality_gate,
    independent_test_quality_gate,
):
    failed_stages = []
    reasons = []
    reason_codes = []
    for stage, quality_gate in (
        ('walk_forward', walk_forward_quality_gate),
        ('independent_test', independent_test_quality_gate),
    ):
        if quality_gate['passed']:
            continue
        failed_stages.append(stage)
        stage_label = stage.replace('_', ' ').title()
        reasons.extend(
            reason
            if reason.lower().startswith(stage_label.lower())
            else f'{stage_label}: {reason}'
            for reason in quality_gate['reasons']
        )
        reason_codes.extend(
            f'{stage}:{code}'
            for code in quality_gate['reason_codes']
        )
    return {
        'passed': not failed_stages,
        'source': 'walk_forward_and_independent_test',
        'failed_stages': failed_stages,
        'reason_codes': reason_codes,
        'reasons': reasons,
        'walk_forward_passed': walk_forward_quality_gate['passed'],
        'independent_test_passed': independent_test_quality_gate['passed'],
        'rule': (
            'A formal classification forecast is published only when both the purged '
            'walk-forward gate and the untouched independent Test publication gate pass.'
        ),
    }


def _relative_error_improvement(baseline_error, model_error):
    return (
        float((baseline_error - model_error) / baseline_error)
        if baseline_error > 0
        else 0.0
    )


def _regression_prediction_diagnostics(labels, predictions):
    labels_array = np.asarray(labels, dtype=float)
    predictions_array = np.asarray(predictions, dtype=float)
    actual_std = float(np.std(labels_array)) if len(labels_array) else 0.0
    prediction_std = float(np.std(predictions_array)) if len(predictions_array) else 0.0
    correlation = None
    if actual_std > 0 and prediction_std > 0:
        correlation_value = float(np.corrcoef(labels_array, predictions_array)[0, 1])
        correlation = correlation_value if isfinite(correlation_value) else None
    return {
        'actual': {
            'mean': float(np.mean(labels_array)),
            'median': float(np.median(labels_array)),
            'std': actual_std,
            'min': float(np.min(labels_array)),
            'max': float(np.max(labels_array)),
        },
        'predicted': {
            'mean': float(np.mean(predictions_array)),
            'median': float(np.median(predictions_array)),
            'std': prediction_std,
            'min': float(np.min(predictions_array)),
            'max': float(np.max(predictions_array)),
        },
        'correlation': correlation,
        'direction_accuracy': float(np.mean(
            (labels_array > 0) == (predictions_array > 0)
        )),
        'maximum_absolute_prediction': float(np.max(np.abs(predictions_array))),
        'prediction_to_actual_std_ratio': (
            float(prediction_std / actual_std)
            if actual_std > 0
            else None
        ),
    }


def evaluate_regression_candidate_walk_forward(candidate, folds):
    """Evaluate one fixed candidate using only purged Walk-Forward Validation."""
    labels = []
    predictions = []
    historical_mean_predictions = []
    fold_metrics = []
    for fold in folds:
        model = _regression_model(candidate)
        model.fit(fold['x_regression_train'], fold['y_regression_train'])
        fold_labels = np.asarray(fold['y_regression_validation'], dtype=float)
        fold_predictions = np.asarray(
            model.predict(fold['x_regression_validation']),
            dtype=float,
        )
        zero_predictions = np.zeros(len(fold_labels), dtype=float)
        training_mean = float(mean(fold['y_regression_train']))
        mean_predictions = np.full(len(fold_labels), training_mean, dtype=float)
        model_metrics = _regression_metrics(fold_labels, fold_predictions)
        zero_metrics = _regression_metrics(fold_labels, zero_predictions)
        historical_mean_metrics = _regression_metrics(fold_labels, mean_predictions)
        mae_improvement = _relative_error_improvement(
            zero_metrics['mae'],
            model_metrics['mae'],
        )
        rmse_improvement = _relative_error_improvement(
            zero_metrics['rmse'],
            model_metrics['rmse'],
        )
        labels.extend(float(value) for value in fold_labels)
        predictions.extend(float(value) for value in fold_predictions)
        historical_mean_predictions.extend(float(value) for value in mean_predictions)
        fold_metrics.append({
            'fold': fold['fold'],
            'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'],
            'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'],
            **model_metrics,
            'zero_return_baseline': zero_metrics,
            'historical_training_mean_baseline': {
                'training_mean_return': training_mean,
                **historical_mean_metrics,
            },
            'mae_improvement_over_zero': mae_improvement,
            'rmse_improvement_over_zero': rmse_improvement,
            'beats_zero_on_mae_and_rmse': (
                mae_improvement > 0 and rmse_improvement > 0
            ),
            'prediction_diagnostics': _regression_prediction_diagnostics(
                fold_labels,
                fold_predictions,
            ),
        })

    model_metrics = _regression_metrics(labels, predictions)
    zero_metrics = _regression_metrics(labels, [0.0] * len(labels))
    historical_mean_metrics = _regression_metrics(labels, historical_mean_predictions)
    improving_fold_count = sum(
        fold['beats_zero_on_mae_and_rmse']
        for fold in fold_metrics
    )
    improving_fold_ratio = improving_fold_count / len(fold_metrics) if fold_metrics else 0.0
    mae_improvement = _relative_error_improvement(
        zero_metrics['mae'],
        model_metrics['mae'],
    )
    rmse_improvement = _relative_error_improvement(
        zero_metrics['rmse'],
        model_metrics['rmse'],
    )
    mae_ratios = [
        fold['mae'] / fold['zero_return_baseline']['mae']
        if fold['zero_return_baseline']['mae'] > 0 else float('inf')
        for fold in fold_metrics
    ]
    rmse_ratios = [
        fold['rmse'] / fold['zero_return_baseline']['rmse']
        if fold['zero_return_baseline']['rmse'] > 0 else float('inf')
        for fold in fold_metrics
    ]
    worst_fold_error_ratio = max(
        [*mae_ratios, *rmse_ratios],
        default=float('inf'),
    )
    fold_mae_std = float(pstdev(fold['mae'] for fold in fold_metrics))
    return {
        'model': candidate['model'],
        'family': candidate['family'],
        'params': dict(candidate['params']),
        'source': 'purged_walk_forward_validation',
        'sample_count': len(labels),
        'model_metrics': model_metrics,
        'zero_return_baseline': {
            'name': 'zero_future_return',
            **zero_metrics,
        },
        'historical_training_mean_baseline': {
            'name': 'fold_training_mean_future_return',
            **historical_mean_metrics,
        },
        'mae_improvement_over_zero': mae_improvement,
        'rmse_improvement_over_zero': rmse_improvement,
        'improving_fold_count': int(improving_fold_count),
        'improving_fold_ratio': float(improving_fold_ratio),
        'worst_fold_error_ratio': float(worst_fold_error_ratio),
        'fold_mae_std': fold_mae_std,
        'prediction_diagnostics': _regression_prediction_diagnostics(labels, predictions),
        'folds': fold_metrics,
    }


def evaluate_regression_walk_forward(folds):
    """Backward-compatible evaluation of the original fixed RF regressor."""
    baseline_candidate = next(
        candidate
        for candidate in REGRESSION_MODEL_CANDIDATES
        if candidate['family'] == 'random_forest'
        and candidate['params']['max_depth'] == 8
    )
    return evaluate_regression_candidate_walk_forward(baseline_candidate, folds)


def tune_regression_models(folds):
    """Select a regression candidate from Walk-Forward Validation only."""
    evaluations = []
    for candidate_index, candidate in enumerate(REGRESSION_MODEL_CANDIDATES):
        evaluation = evaluate_regression_candidate_walk_forward(candidate, folds)
        evaluation['candidate_index'] = candidate_index
        evaluation['selection_key'] = (
            float(evaluation['model_metrics']['mae']),
            float(evaluation['model_metrics']['rmse']),
            -float(evaluation['improving_fold_ratio']),
            float(evaluation['worst_fold_error_ratio']),
            float(evaluation['fold_mae_std']),
            candidate_index,
        )
        evaluation['quality_gate'] = evaluate_regression_quality_gate(evaluation)
        evaluations.append(evaluation)
    deployable_evaluations = [
        evaluation
        for evaluation in evaluations
        if evaluation['quality_gate']['passed']
    ]
    selection_pool = deployable_evaluations or evaluations
    selected = min(selection_pool, key=lambda evaluation: evaluation['selection_key'])
    for evaluation in evaluations:
        evaluation['selected'] = evaluation is selected
        evaluation['selection_score'] = float(
            1
            - (
                0.55
                * evaluation['model_metrics']['mae']
                / evaluation['zero_return_baseline']['mae']
                + 0.30
                * evaluation['model_metrics']['rmse']
                / evaluation['zero_return_baseline']['rmse']
                + 0.15
                * evaluation['worst_fold_error_ratio']
            )
        )
    return {
        'selected': selected,
        'candidates': evaluations,
        'candidate_count': len(evaluations),
        'selection_source': 'purged_walk_forward_validation',
        'selection_rule': (
            'Prefer candidates that pass the unchanged Walk-Forward regression gate; '
            'within that pool use lowest pooled Walk-Forward MAE, then RMSE, then higher improving-fold '
            'ratio, lower worst-fold error ratio, lower fold-MAE variability, and '
            'fixed candidate order. Independent Test is excluded.'
        ),
    }


def evaluate_regression_quality_gate(walk_forward_evaluation):
    """Compare walk-forward regression predictions with a zero-return baseline."""
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    sample_count = int(walk_forward_evaluation['sample_count'])
    model_metrics = walk_forward_evaluation['model_metrics']
    baseline_metrics = walk_forward_evaluation['zero_return_baseline']
    baseline_mae = float(baseline_metrics['mae'])
    baseline_rmse = float(baseline_metrics['rmse'])
    mae_improvement = (
        (baseline_mae - float(model_metrics['mae'])) / baseline_mae
        if baseline_mae > 0
        else 0.0
    )
    rmse_improvement = (
        (baseline_rmse - float(model_metrics['rmse'])) / baseline_rmse
        if baseline_rmse > 0
        else 0.0
    )
    fold_metrics = walk_forward_evaluation.get('folds', ())
    improving_fold_ratio = float(walk_forward_evaluation.get(
        'improving_fold_ratio',
        1.0 if mae_improvement > 0 and rmse_improvement > 0 else 0.0,
    ))
    prediction_diagnostics = walk_forward_evaluation.get('prediction_diagnostics', {})
    reasons = []
    reason_codes = []

    def reject(code, message):
        reason_codes.append(code)
        reasons.append(message)

    if sample_count < thresholds['minimum_oos_samples']:
        reject(
            'insufficient_oos_samples',
            f'Only {sample_count} walk-forward regression predictions are available; '
            f'at least {thresholds["minimum_oos_samples"]} are required.',
        )
    if baseline_mae <= 0 or baseline_rmse <= 0:
        reject(
            'zero_return_baseline_has_no_error',
            'The zero-return baseline has no measurable error, so the regression model cannot improve on it.',
        )
    if mae_improvement < thresholds['minimum_regression_mae_improvement']:
        reject(
            'mae_did_not_beat_zero_return_baseline',
            f'Regression MAE improvement {mae_improvement:.3f} is below the '
            f'{thresholds["minimum_regression_mae_improvement"]:.3f} minimum.',
        )
    if rmse_improvement < thresholds['minimum_regression_rmse_improvement']:
        reject(
            'rmse_did_not_beat_zero_return_baseline',
            f'Regression RMSE improvement {rmse_improvement:.3f} is below the '
            f'{thresholds["minimum_regression_rmse_improvement"]:.3f} minimum.',
        )
    if improving_fold_ratio < thresholds['minimum_regression_improving_fold_ratio']:
        reject(
            'insufficient_improving_folds',
            f'Only {improving_fold_ratio:.3f} of regression Walk-Forward folds beat '
            f'the zero-return baseline on both MAE and RMSE; at least '
            f'{thresholds["minimum_regression_improving_fold_ratio"]:.3f} is required.',
        )
    _append_regression_anomaly_reasons(
        prediction_diagnostics,
        thresholds,
        reject,
        stage_label='Walk-Forward',
    )

    return {
        'passed': not reasons,
        'source': 'purged_walk_forward_validation',
        'reason_codes': reason_codes,
        'reasons': reasons,
        'thresholds': {
            'minimum_oos_samples': thresholds['minimum_oos_samples'],
            'minimum_mae_improvement': thresholds['minimum_regression_mae_improvement'],
            'minimum_rmse_improvement': thresholds['minimum_regression_rmse_improvement'],
            'minimum_improving_fold_ratio': thresholds['minimum_regression_improving_fold_ratio'],
            'minimum_prediction_std': thresholds['minimum_regression_prediction_std'],
            'maximum_prediction_to_actual_std_ratio': (
                thresholds['maximum_regression_prediction_to_actual_std_ratio']
            ),
            'maximum_absolute_predicted_return': thresholds['maximum_absolute_predicted_return'],
        },
        'observed': {
            'oos_samples': sample_count,
            'mae': float(model_metrics['mae']),
            'rmse': float(model_metrics['rmse']),
            'r2': model_metrics['r2'],
            'baseline_mae': baseline_mae,
            'baseline_rmse': baseline_rmse,
            'mae_improvement': float(mae_improvement),
            'rmse_improvement': float(rmse_improvement),
            'improving_fold_count': int(walk_forward_evaluation.get('improving_fold_count', 0)),
            'improving_fold_ratio': improving_fold_ratio,
            'fold_count': len(fold_metrics),
            'prediction_diagnostics': prediction_diagnostics,
        },
        'baseline': baseline_metrics,
    }


def _append_regression_anomaly_reasons(diagnostics, thresholds, reject, stage_label):
    if not diagnostics:
        return
    predicted = diagnostics.get('predicted', {})
    prediction_std = float(predicted.get('std', 0.0))
    std_ratio = diagnostics.get('prediction_to_actual_std_ratio')
    maximum_absolute_prediction = float(
        diagnostics.get('maximum_absolute_prediction', 0.0)
    )
    if prediction_std < thresholds['minimum_regression_prediction_std']:
        reject(
            'effectively_constant_predictions',
            f'{stage_label} regression predictions are effectively constant.',
        )
    if (
        std_ratio is not None
        and std_ratio > thresholds['maximum_regression_prediction_to_actual_std_ratio']
    ):
        reject(
            'prediction_variance_extreme',
            f'{stage_label} regression prediction volatility is {std_ratio:.3f} times '
            'the actual target volatility, above the configured limit.',
        )
    if maximum_absolute_prediction > thresholds['maximum_absolute_predicted_return']:
        reject(
            'predicted_return_extreme',
            f'{stage_label} contains an absolute predicted return of '
            f'{maximum_absolute_prediction:.3f}, above the configured limit.',
        )


def evaluate_regression_independent_test_quality_gate(test_evaluation):
    """Publication-only regression gate for the frozen independent Test result."""
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    sample_count = int(test_evaluation['sample_count'])
    model_metrics = test_evaluation['model_metrics']
    baseline_metrics = test_evaluation['zero_return_baseline']
    mae_improvement = _relative_error_improvement(
        baseline_metrics['mae'],
        model_metrics['mae'],
    )
    rmse_improvement = _relative_error_improvement(
        baseline_metrics['rmse'],
        model_metrics['rmse'],
    )
    reasons = []
    reason_codes = []

    def reject(code, message):
        reason_codes.append(code)
        reasons.append(message)

    if sample_count < thresholds['minimum_regression_independent_test_samples']:
        reject(
            'insufficient_test_samples',
            f'Only {sample_count} independent Test regression predictions are available; '
            f'at least {thresholds["minimum_regression_independent_test_samples"]} are required.',
        )
    if baseline_metrics['mae'] <= 0 or baseline_metrics['rmse'] <= 0:
        reject(
            'zero_return_baseline_has_no_error',
            'Independent Test zero-return baseline has no measurable error.',
        )
    if mae_improvement < thresholds['minimum_regression_mae_improvement']:
        reject(
            'mae_did_not_beat_zero_return_baseline',
            f'Independent Test regression MAE improvement {mae_improvement:.3f} is below '
            f'the {thresholds["minimum_regression_mae_improvement"]:.3f} minimum.',
        )
    if rmse_improvement < thresholds['minimum_regression_rmse_improvement']:
        reject(
            'rmse_did_not_beat_zero_return_baseline',
            f'Independent Test regression RMSE improvement {rmse_improvement:.3f} is below '
            f'the {thresholds["minimum_regression_rmse_improvement"]:.3f} minimum.',
        )
    _append_regression_anomaly_reasons(
        test_evaluation.get('prediction_diagnostics', {}),
        thresholds,
        reject,
        stage_label='Independent Test',
    )
    return {
        'passed': not reasons,
        'source': 'independent_test_publication_gate',
        'role': 'publication_only',
        'reason_codes': reason_codes,
        'reasons': reasons,
        'thresholds': {
            'minimum_test_samples': thresholds['minimum_regression_independent_test_samples'],
            'minimum_mae_improvement': thresholds['minimum_regression_mae_improvement'],
            'minimum_rmse_improvement': thresholds['minimum_regression_rmse_improvement'],
            'minimum_prediction_std': thresholds['minimum_regression_prediction_std'],
            'maximum_prediction_to_actual_std_ratio': (
                thresholds['maximum_regression_prediction_to_actual_std_ratio']
            ),
            'maximum_absolute_predicted_return': thresholds['maximum_absolute_predicted_return'],
        },
        'observed': {
            'test_samples': sample_count,
            'mae': float(model_metrics['mae']),
            'rmse': float(model_metrics['rmse']),
            'r2': model_metrics['r2'],
            'baseline_mae': float(baseline_metrics['mae']),
            'baseline_rmse': float(baseline_metrics['rmse']),
            'mae_improvement': mae_improvement,
            'rmse_improvement': rmse_improvement,
            'prediction_diagnostics': test_evaluation.get('prediction_diagnostics', {}),
        },
        'baseline': baseline_metrics,
    }


def evaluate_final_regression_quality_gate(
    walk_forward_quality_gate,
    independent_test_quality_gate,
):
    failed_stages = []
    reasons = []
    reason_codes = []
    for stage, quality_gate in (
        ('walk_forward', walk_forward_quality_gate),
        ('independent_test', independent_test_quality_gate),
    ):
        if quality_gate['passed']:
            continue
        failed_stages.append(stage)
        reasons.extend(
            f'{stage.replace("_", " ").title()}: {reason}'
            for reason in quality_gate['reasons']
        )
        reason_codes.extend(
            f'{stage}:{code}'
            for code in quality_gate['reason_codes']
        )
    return {
        'passed': not failed_stages,
        'source': 'walk_forward_and_independent_test',
        'failed_stages': failed_stages,
        'reason_codes': reason_codes,
        'reasons': reasons,
        'walk_forward_passed': walk_forward_quality_gate['passed'],
        'independent_test_passed': independent_test_quality_gate['passed'],
        'rule': (
            'A formal return and price forecast is published only when the selected '
            'Walk-Forward candidate and its frozen independent Test evaluation both '
            'beat the zero-return baseline and pass anomaly checks.'
        ),
    }


def generate_regression_machine_learning_prediction(dataset, current_price):
    """Run the return pipeline using its own labels, split, purge, and folds."""
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    training_samples = split['training_samples']
    validation_samples = split['validation_samples']
    test_samples = split['test_samples']
    insufficient_reason = None
    if (
        dataset.latest_regression_features is None
        or training_samples < MINIMUM_TRAINING_SAMPLES
        or validation_samples < MINIMUM_VALIDATION_SAMPLES
        or test_samples < MINIMUM_TEST_SAMPLES
    ):
        insufficient_reason = (
            'Insufficient historical data for regression prediction. '
            f'The {dataset.horizon}-trading-day return target requires at least '
            f'{MINIMUM_TRAINING_SAMPLES} training, {MINIMUM_VALIDATION_SAMPLES} validation, '
            f'and {MINIMUM_TEST_SAMPLES} independent Test samples after two '
            f'{dataset.horizon}-sample purge gaps; {training_samples}, '
            f'{validation_samples}, and {test_samples} are available.'
        )
    elif len(folds) < 2:
        insufficient_reason = (
            'Insufficient historical data for regression purged Walk-Forward Validation. '
            f'The {dataset.horizon}-trading-day return target produced only '
            f'{len(folds)} usable fold(s).'
        )

    if insufficient_reason:
        return {
            'prediction_available': False,
            'prediction_unavailable_reason': insufficient_reason,
            'expected_return': None,
            'predicted_price': None,
            'selected_candidate_model': None,
            'selected_candidate_params': None,
            'regression_model': None,
            'walk_forward_quality_gate': None,
            'independent_test_quality_gate': None,
            'final_quality_gate': None,
            'model_metrics': {
                'status': 'insufficient_data',
                'metric_source': None,
                'forecast_horizon': dataset.horizon,
                'purge_gap': dataset.horizon,
                'training_samples': training_samples,
                'validation_samples': validation_samples,
                'test_samples': test_samples,
                'walk_forward_fold_count': len(folds),
                'unavailable_reason': insufficient_reason,
            },
            'split': split,
            'folds': folds,
        }

    regression_tuning = tune_regression_models(folds)
    selected_regression = regression_tuning['selected']
    walk_forward_quality_gate = evaluate_regression_quality_gate(selected_regression)
    regression_model = _regression_model(selected_regression)
    development_end = split['development_end']
    x_regression_development = dataset.regression_features[:development_end]
    y_regression_development = dataset.regression_labels[:development_end]
    regression_model.fit(x_regression_development, y_regression_development)
    test_predictions = np.asarray(
        regression_model.predict(split['x_regression_test']),
        dtype=float,
    )
    test_labels = np.asarray(split['y_regression_test'], dtype=float)
    zero_test_predictions = np.zeros(len(test_labels), dtype=float)
    development_mean = float(mean(y_regression_development))
    historical_mean_test_predictions = np.full(
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
            **_regression_metrics(test_labels, zero_test_predictions),
        },
        'historical_training_mean_baseline': {
            'name': 'development_training_mean_future_return',
            'training_mean_return': development_mean,
            **_regression_metrics(test_labels, historical_mean_test_predictions),
        },
        'prediction_diagnostics': _regression_prediction_diagnostics(
            test_labels,
            test_predictions,
        ),
    }
    independent_test_quality_gate = evaluate_regression_independent_test_quality_gate(
        test_evaluation,
    )
    final_quality_gate = evaluate_final_regression_quality_gate(
        walk_forward_quality_gate,
        independent_test_quality_gate,
    )
    prediction_available = final_quality_gate['passed']
    raw_expected_return = float(regression_model.predict(
        [dataset.latest_regression_features],
    )[0])
    raw_predicted_price = calculate_predicted_price(current_price, raw_expected_return)
    unavailable_reason = None
    if not prediction_available:
        unavailable_reason = (
            'The selected regression model did not pass the complete two-stage '
            f'{dataset.horizon}-trading-day return-prediction quality gate, so expected '
            'return and predicted price are unavailable. '
            + ' '.join(final_quality_gate['reasons'])
        ).strip()
    return {
        'prediction_available': prediction_available,
        'prediction_unavailable_reason': unavailable_reason,
        'expected_return': raw_expected_return if prediction_available else None,
        'predicted_price': raw_predicted_price if prediction_available else None,
        'selected_candidate_model': selected_regression['model'],
        'selected_candidate_params': selected_regression['params'],
        'regression_model': selected_regression['model'] if prediction_available else None,
        'walk_forward_quality_gate': walk_forward_quality_gate,
        'independent_test_quality_gate': independent_test_quality_gate,
        'final_quality_gate': final_quality_gate,
        'model_metrics': {
            **test_evaluation['model_metrics'],
            'metric_source': 'independent_test',
            'model': selected_regression['model'],
            'params': selected_regression['params'],
            'forecast_horizon': dataset.horizon,
            'purge_gap': dataset.horizon,
            'zero_return_baseline': test_evaluation['zero_return_baseline'],
            'historical_training_mean_baseline': (
                test_evaluation['historical_training_mean_baseline']
            ),
            'prediction_diagnostics': test_evaluation['prediction_diagnostics'],
            'walk_forward_quality_metrics': selected_regression,
            'candidate_models': regression_tuning['candidates'],
            'candidate_count': regression_tuning['candidate_count'],
            'selection_source': regression_tuning['selection_source'],
            'selection_rule': regression_tuning['selection_rule'],
            'walk_forward_quality_gate': walk_forward_quality_gate,
            'independent_test_quality_gate': independent_test_quality_gate,
            'final_quality_gate': final_quality_gate,
            'quality_gate': final_quality_gate,
        },
        'split': split,
        'folds': folds,
    }


def _classification_quality_failure_reason(quality_gate):
    details = ' '.join(quality_gate['reasons'])
    return (
        'The selected classification model did not pass the complete two-stage '
        'prediction quality gate, so no directional prediction is provided. '
        f'{details}'
    ).strip()


def generate_machine_learning_prediction(
    classification_dataset,
    regression_dataset,
    current_price,
):
    dataset = classification_dataset
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    regression_split = build_purged_chronological_split(regression_dataset)
    regression_folds = build_purged_walk_forward_folds(
        regression_dataset,
        regression_split,
    )
    training_samples = split['training_samples']
    validation_samples = split['validation_samples']
    test_samples = split['test_samples']
    if (
        dataset.latest_features is None
        or training_samples < MINIMUM_TRAINING_SAMPLES
        or validation_samples < MINIMUM_VALIDATION_SAMPLES
        or test_samples < MINIMUM_TEST_SAMPLES
    ):
        reason = (
            'Insufficient historical data for machine-learning prediction. '
            f'At least {MINIMUM_TRAINING_SAMPLES} chronological training samples and '
            f'{MINIMUM_VALIDATION_SAMPLES} validation samples and {MINIMUM_TEST_SAMPLES} independent test samples '
            f'are required after feature warm-up, horizon labeling, and two {dataset.horizon}-sample purge gaps; '
            f'{training_samples} training, {validation_samples} validation, and {test_samples} test samples are available.'
        )
        return _unavailable_result(
            reason,
            dataset,
            split,
            folds=folds,
            regression_dataset=regression_dataset,
            regression_split=regression_split,
            regression_folds=regression_folds,
        )

    if len(folds) < 2:
        reason = (
            'Insufficient historical data for purged walk-forward validation. '
            f'At least two folds with {MINIMUM_TRAINING_SAMPLES} initial training samples, '
            f'{MINIMUM_VALIDATION_SAMPLES} validation samples, and a {dataset.horizon}-sample '
            'purge are required before the independent Test.'
        )
        return _unavailable_result(
            reason,
            dataset,
            split,
            folds=folds,
            regression_dataset=regression_dataset,
            regression_split=regression_split,
            regression_folds=regression_folds,
        )

    x_test = split['x_test']
    y_classification_test = split['y_classification_test']

    for fold in folds:
        if len(set(fold['y_classification_train'])) < 2:
            reason = (
                f'Insufficient class variation in walk-forward Fold {fold["fold"]} '
                'Training data for machine-learning prediction.'
            )
            return _unavailable_result(
                reason,
                dataset,
                split,
                folds=folds,
                regression_dataset=regression_dataset,
                regression_split=regression_split,
                regression_folds=regression_folds,
            )

    x_development = dataset.features[:split['development_end']]
    y_classification_development = dataset.classification_labels[:split['development_end']]
    if len(set(y_classification_development)) < 2:
        reason = 'Insufficient class variation in development data for final classifier fitting.'
        return _unavailable_result(
            reason,
            dataset,
            split,
            folds=folds,
            regression_dataset=regression_dataset,
            regression_split=regression_split,
            regression_folds=regression_folds,
        )

    logistic_evaluation = evaluate_classifier_walk_forward(
        _logistic_regression,
        folds,
    )
    random_forest_evaluation = tune_random_forest_classifier(folds)
    evaluations = [
        {
            'model': 'Logistic Regression',
            'params': None,
            **logistic_evaluation,
        },
        {
            'model': 'Random Forest Classifier',
            **random_forest_evaluation,
        },
    ]

    eligible_evaluations = [
        evaluation
        for evaluation in evaluations
        if evaluation['threshold_eligible']
    ]
    selection_pool = eligible_evaluations or evaluations
    selected = max(
        selection_pool,
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
        evaluation['quality_gate'] = evaluate_classification_quality_gate(
            {
                **evaluation['metrics'],
                'fold_metrics': evaluation['fold_metrics'],
            },
            folds,
        )
    classification_quality_gate = selected['quality_gate']

    comparison = []
    latest_features = [dataset.latest_features]
    for evaluation in evaluations:
        if evaluation['model'] == 'Logistic Regression':
            final_model = _logistic_regression()
        else:
            final_model = _random_forest_classifier(evaluation['params'])
        final_model.fit(x_development, y_classification_development)
        evaluation['fitted_model'] = final_model
        model_probability = _positive_probability(final_model, latest_features)
        evaluation['latest_probability'] = model_probability
        model_threshold = evaluation['threshold']
        is_selected = evaluation['model'] == selected['model']
        comparison.append({
            'model': evaluation['model'],
            'selected': is_selected,
            'predicted_direction': 'UP' if model_probability > model_threshold else 'DOWN',
            'probability_increase': model_probability,
            'threshold': model_threshold,
            'threshold_source': 'purged_walk_forward_validation',
            'threshold_eligible': evaluation['threshold_eligible'],
            'non_degenerate_all_folds': evaluation['non_degenerate_all_folds'],
            'selection_score': evaluation['selection_score'],
            'metric_source': 'purged_walk_forward_validation',
            'walk_forward_folds': evaluation['fold_metrics'],
            'threshold_stability': evaluation['threshold_stability'],
            'quality_gate': evaluation['quality_gate'],
            'walk_forward_quality_gate': evaluation['quality_gate'],
            **evaluation['metrics'],
        })

    selected_classifier = selected['fitted_model']
    selected_threshold = selected['threshold']
    probability_increase = selected['latest_probability']
    test_probabilities = selected_classifier.predict_proba(x_test)[:, list(selected_classifier.classes_).index(1)]
    test_predictions = _predictions_for_threshold(test_probabilities, selected_threshold)
    test_classification_metrics = _classification_metrics(
        y_classification_test,
        test_predictions,
        test_probabilities,
    )
    independent_test_quality_gate = evaluate_independent_test_quality_gate(
        test_classification_metrics,
    )
    final_classification_quality_gate = evaluate_final_classification_quality_gate(
        classification_quality_gate,
        independent_test_quality_gate,
    )

    regression_result = generate_regression_machine_learning_prediction(
        regression_dataset,
        current_price,
    )
    regression_walk_forward_quality_gate = regression_result['walk_forward_quality_gate']
    regression_independent_test_quality_gate = regression_result['independent_test_quality_gate']
    final_regression_quality_gate = regression_result['final_quality_gate']
    confidence, confidence_details = _confidence(probability_increase, test_classification_metrics)
    reliability = _walk_forward_reliability(selected, folds)
    confidence_details = {
        **confidence_details,
        'walk_forward_reliability': reliability,
    }

    baseline_accuracy = majority_class_baseline_accuracy(y_classification_test)
    classification_prediction_available = final_classification_quality_gate['passed']
    regression_prediction_available = regression_result['prediction_available']
    prediction_unavailable_reason = (
        None
        if classification_prediction_available
        else _classification_quality_failure_reason(final_classification_quality_gate)
    )
    regression_prediction_unavailable_reason = regression_result[
        'prediction_unavailable_reason'
    ]
    return {
        'classification_forecast_horizon': dataset.horizon,
        'regression_forecast_horizon': regression_dataset.horizon,
        'classification_purge_gap': split['gap_size'],
        'regression_purge_gap': regression_result['split']['gap_size'],
        'classification_prediction': {
            'forecast_horizon': dataset.horizon,
            'purge_gap': split['gap_size'],
            'available': classification_prediction_available,
        },
        'regression_prediction': {
            'forecast_horizon': regression_dataset.horizon,
            'purge_gap': regression_result['split']['gap_size'],
            'available': regression_prediction_available,
        },
        'prediction_available': classification_prediction_available,
        'prediction_unavailable_reason': prediction_unavailable_reason,
        'predicted_direction': (
            'UP' if probability_increase > selected_threshold else 'DOWN'
        ) if classification_prediction_available else None,
        'probability_increase': (
            probability_increase if classification_prediction_available else None
        ),
        'expected_return': regression_result['expected_return'],
        'predicted_price': regression_result['predicted_price'],
        'confidence': confidence if classification_prediction_available else None,
        'selected_model': selected['model'] if classification_prediction_available else None,
        'selected_threshold': selected_threshold if classification_prediction_available else None,
        'selected_candidate_model': selected['model'],
        'selected_candidate_threshold': selected_threshold,
        'selected_regression_candidate_model': regression_result['selected_candidate_model'],
        'selected_regression_candidate_params': regression_result['selected_candidate_params'],
        'regression_prediction_available': regression_prediction_available,
        'regression_prediction_unavailable_reason': regression_prediction_unavailable_reason,
        'regression_model': regression_result['regression_model'],
        'ml_reliability': reliability,
        'prediction_quality_gate': {
            'passed': classification_prediction_available and regression_prediction_available,
            'source': 'two_stage_classification_and_two_stage_regression',
            'classification': final_classification_quality_gate,
            'walk_forward_classification': classification_quality_gate,
            'independent_test_classification': independent_test_quality_gate,
            'regression': final_regression_quality_gate,
            'walk_forward_regression': regression_walk_forward_quality_gate,
            'independent_test_regression': regression_independent_test_quality_gate,
        },
        'walk_forward_quality_gate': classification_quality_gate,
        'independent_test_quality_gate': independent_test_quality_gate,
        'final_classification_quality_gate': final_classification_quality_gate,
        'regression_walk_forward_quality_gate': regression_walk_forward_quality_gate,
        'regression_independent_test_quality_gate': regression_independent_test_quality_gate,
        'final_regression_quality_gate': final_regression_quality_gate,
        'model_metrics': {
            **test_classification_metrics,
            'metric_source': 'independent_test',
            'threshold': selected_threshold,
            'threshold_source': 'purged_walk_forward_validation',
            'selection_score': selected['selection_score'],
            'validation_selection_metrics': selected['metrics'],
            'walk_forward_folds': selected['fold_metrics'],
            'threshold_stability': selected['threshold_stability'],
            'majority_class_baseline_accuracy': float(baseline_accuracy),
            'training_samples': split['development_samples'],
            'validation_samples': sum(fold['validation_samples'] for fold in folds),
            'test_samples': test_samples,
            'gap_size': split['gap_size'],
            'quality_gate': final_classification_quality_gate,
            'walk_forward_quality_gate': classification_quality_gate,
            'independent_test_quality_gate': independent_test_quality_gate,
            'final_classification_quality_gate': final_classification_quality_gate,
            'regression': regression_result['model_metrics'],
        },
        'model_comparison': comparison,
        'confidence_details': confidence_details if classification_prediction_available else None,
        'ml_metadata': _ml_metadata(
            dataset,
            split,
            folds=folds,
            random_forest_params=random_forest_evaluation['params'],
            reliability=reliability,
            regression_dataset=regression_dataset,
            regression_split=regression_result['split'],
            regression_folds=regression_result['folds'],
        ),
    }
