"""Offline model-family and learning-objective diagnostics.

This module is deliberately isolated from ``prediction.ml_service`` production
entry points.  It reuses the production point-in-time feature matrices and
purged Walk-Forward folds, but never mutates the API, targets, quality gates, or
frontend.  Model/objective selection is Development-only; the independent Test
is exposed through a separate, post-freeze function.
"""

from dataclasses import dataclass
from itertools import combinations
from math import isfinite
from statistics import mean, median, pstdev

import numpy as np
from scipy.stats import kurtosis, skew, spearmanr
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
)
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, HuberRegressor, LogisticRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from prediction.ml_service import (
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    RANDOM_FOREST_CLASSIFIER_PARAM_GRID,
    REGRESSION_MODEL_CANDIDATES,
    RANDOM_STATE,
    _classification_metrics,
    _roc_auc_for_probabilities,
    _regression_metrics,
    _walk_forward_selection_score,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    majority_class_baseline_accuracy,
    select_walk_forward_threshold,
)


CLASSIFICATION_FAMILY_CONFIGS = {
    'Current Logistic Regression': (
        {'penalty': 'l2', 'C': 1.0, 'solver': 'lbfgs', 'class_weight': 'balanced'},
    ),
    'Current Random Forest': tuple(dict(params) for params in RANDOM_FOREST_CLASSIFIER_PARAM_GRID),
    'Regularized Logistic Regression': tuple(
        {'penalty': penalty, 'C': strength, 'solver': 'liblinear', 'class_weight': 'balanced'}
        for penalty in ('l1', 'l2') for strength in (0.1, 1.0, 10.0)
    ),
    'Extra Trees Classifier': (
        {'n_estimators': 200, 'max_depth': 3, 'min_samples_leaf': 6, 'max_features': 'sqrt'},
        {'n_estimators': 200, 'max_depth': 5, 'min_samples_leaf': 4, 'max_features': 'sqrt'},
        {'n_estimators': 300, 'max_depth': 4, 'min_samples_leaf': 5, 'max_features': 0.5},
    ),
    'Histogram Gradient Boosting Classifier': (
        {'learning_rate': 0.03, 'max_iter': 100, 'max_leaf_nodes': 7,
         'min_samples_leaf': 20, 'l2_regularization': 1.0},
        {'learning_rate': 0.05, 'max_iter': 100, 'max_leaf_nodes': 7,
         'min_samples_leaf': 25, 'l2_regularization': 1.0},
        {'learning_rate': 0.03, 'max_iter': 150, 'max_leaf_nodes': 5,
         'min_samples_leaf': 20, 'l2_regularization': 2.0},
    ),
}

EXTRA_REGRESSION_CONFIGS = (
    {'model': 'Extra Trees Regressor', 'family': 'extra_trees',
     'params': {'n_estimators': 200, 'max_depth': 4, 'min_samples_leaf': 5, 'max_features': 0.7}},
    {'model': 'Extra Trees Regressor', 'family': 'extra_trees',
     'params': {'n_estimators': 300, 'max_depth': 6, 'min_samples_leaf': 4, 'max_features': 0.7}},
    {'model': 'Extra Trees Regressor', 'family': 'extra_trees',
     'params': {'n_estimators': 200, 'max_depth': 3, 'min_samples_leaf': 7, 'max_features': 1.0}},
)
REGRESSION_FAMILY_CONFIGS = tuple(dict(candidate) for candidate in REGRESSION_MODEL_CANDIDATES) + EXTRA_REGRESSION_CONFIGS

# Pre-registered research-only cross-context rules.  These do not weaken or
# replace the deployment quality gates in ml_service.py.
ARCHITECTURE_CANDIDATE_RULES = {
    'classification': {
        'minimum_improved_contexts': 4,
        'minimum_improved_symbols': 2,
        'minimum_mean_ba_delta': 0.005,
        'minimum_mean_macro_f1_delta': 0.005,
        'minimum_mean_auc_delta': -0.005,
        'minimum_mean_baseline_improvement_delta': 0.0,
        'minimum_fold_pass_ratio_delta': 0.0,
        'maximum_train_validation_gap_increase': 0.03,
        'maximum_harmed_contexts': 1,
    },
    'regression': {
        'minimum_improved_contexts': 4,
        'minimum_improved_symbols': 2,
        'minimum_mean_mae_improvement_delta': 0.005,
        'minimum_mean_rmse_improvement_delta': 0.005,
        'minimum_improving_fold_ratio_delta': 0.0,
        'maximum_train_validation_gap_increase': 0.03,
        'maximum_harmed_contexts': 1,
    },
}

CLASSIFICATION_OBJECTIVES = {
    'production_class_weighted': {'class_weight': 'balanced', 'sample_weight': None},
    'unweighted_control': {'class_weight': None, 'sample_weight': None},
    # Target magnitude is known only for Training rows.  Weights remain bounded
    # to [1, 3] and do not delete low-amplitude observations.
    'magnitude_cost_sensitive': {'class_weight': 'balanced', 'sample_weight': 'magnitude'},
}
REGRESSION_OBJECTIVES = ('raw_return', 'volatility_scaled_return', 'winsorized_return')


def _classifier(family, params, *, class_weight_override='production'):
    params = dict(params)
    if class_weight_override != 'production':
        params['class_weight'] = class_weight_override
    if family in ('Current Logistic Regression', 'Regularized Logistic Regression'):
        class_weight = params.pop('class_weight', 'balanced')
        return Pipeline([
            ('scaler', StandardScaler()),
            ('model', LogisticRegression(
                **params, class_weight=class_weight, max_iter=2_000,
                random_state=RANDOM_STATE,
            )),
        ])
    if family == 'Current Random Forest':
        class_weight = params.pop('class_weight', 'balanced_subsample')
        return RandomForestClassifier(
            **params, class_weight=class_weight,
            random_state=RANDOM_STATE, n_jobs=1,
        )
    if family == 'Extra Trees Classifier':
        class_weight = params.pop('class_weight', 'balanced')
        return ExtraTreesClassifier(
            **params, class_weight=class_weight,
            random_state=RANDOM_STATE, n_jobs=1,
        )
    if family == 'Histogram Gradient Boosting Classifier':
        params.pop('class_weight', None)
        return HistGradientBoostingClassifier(**params, random_state=RANDOM_STATE)
    raise ValueError(f'Unknown classification family: {family}')


def _regressor(candidate):
    family, params = candidate['family'], dict(candidate['params'])
    if family == 'ridge':
        return Pipeline([('scaler', StandardScaler()), ('model', Ridge(**params))])
    if family == 'elastic_net':
        return Pipeline([('scaler', StandardScaler()), ('model', ElasticNet(
            **params, max_iter=10_000, selection='cyclic', tol=1e-3,
        ))])
    if family == 'huber':
        return Pipeline([('scaler', StandardScaler()), ('model', HuberRegressor(
            **params, max_iter=1_000,
        ))])
    if family == 'random_forest':
        from sklearn.ensemble import RandomForestRegressor
        return RandomForestRegressor(**params, random_state=RANDOM_STATE, n_jobs=1)
    if family == 'hist_gradient_boosting':
        return HistGradientBoostingRegressor(**params, random_state=RANDOM_STATE)
    if family == 'extra_trees':
        return ExtraTreesRegressor(**params, random_state=RANDOM_STATE, n_jobs=1)
    raise ValueError(f'Unknown regression family: {family}')


def _positive_probabilities(model, x):
    classes = list(model.classes_)
    return np.asarray(model.predict_proba(x)[:, classes.index(1)], dtype=float)


def _fit_with_optional_weights(model, x, y, weights):
    if weights is None:
        model.fit(x, y)
    elif isinstance(model, Pipeline):
        model.fit(x, y, model__sample_weight=weights)
    else:
        model.fit(x, y, sample_weight=weights)


def training_magnitude_sample_weights(training_returns):
    """Bounded cost weights derived exclusively from known Training labels."""
    values = np.asarray(training_returns, dtype=float)
    return 1.0 + np.minimum(np.abs(values) / 0.005, 2.0)


def _importance_vector(model, x_validation, y_validation, feature_count):
    fitted = model.named_steps['model'] if isinstance(model, Pipeline) else model
    if hasattr(fitted, 'coef_'):
        coefficients = np.asarray(fitted.coef_, dtype=float)
        if coefficients.ndim > 1:
            coefficients = coefficients[0]
        return coefficients, 'standardized_coefficient'
    if hasattr(fitted, 'feature_importances_'):
        return np.asarray(fitted.feature_importances_, dtype=float), 'impurity_importance'
    unique_targets = set(float(value) for value in y_validation)
    scoring = 'balanced_accuracy' if unique_targets <= {0.0, 1.0} else 'neg_mean_absolute_error'
    result = permutation_importance(
        model, x_validation, y_validation, n_repeats=3,
        random_state=RANDOM_STATE, scoring=scoring, n_jobs=1,
    )
    values = np.asarray(result.importances_mean, dtype=float)
    if len(values) != feature_count:
        raise RuntimeError('Permutation importance feature count mismatch.')
    return values, 'validation_permutation_importance'


def _importance_stability(vectors, feature_names, kind):
    correlations = []
    for left, right in combinations(vectors, 2):
        correlation = spearmanr(np.abs(left), np.abs(right)).statistic
        if correlation is not None and isfinite(float(correlation)):
            correlations.append(float(correlation))
    top_sets = [set(np.argsort(np.abs(vector))[-5:]) for vector in vectors]
    overlaps = [len(left & right) / len(left | right) for left, right in combinations(top_sets, 2)]
    sign_stability = None
    sign_flip_features = []
    if kind == 'standardized_coefficient':
        signs = np.sign(np.asarray(vectors))
        per_feature = np.abs(np.mean(signs, axis=0))
        sign_stability = float(np.mean(per_feature))
        sign_flip_features = [
            feature_names[index] for index in range(len(feature_names))
            if len(set(signs[:, index])) > 1
        ]
    mean_abs = np.mean(np.abs(np.asarray(vectors)), axis=0)
    return {
        'kind': kind,
        'mean_pairwise_rank_correlation': float(mean(correlations)) if correlations else None,
        'mean_top5_jaccard': float(mean(overlaps)) if overlaps else None,
        'coefficient_sign_stability': sign_stability,
        'sign_flip_feature_count': len(sign_flip_features),
        'sign_flip_features': sign_flip_features,
        'top_features_by_mean_absolute_importance': [
            feature_names[index] for index in np.argsort(mean_abs)[-8:][::-1]
        ],
    }


def _classification_fold_pass(metrics, fold):
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    training_majority = 1 if sum(fold['y_classification_train']) > len(fold['y_classification_train']) / 2 else 0
    baseline = mean(label == training_majority for label in fold['y_classification_validation'])
    return bool(
        metrics['actual_up_count'] and metrics['actual_down_count']
        and metrics['predicted_up_count'] and metrics['predicted_down_count']
        and metrics['balanced_accuracy'] >= thresholds['minimum_balanced_accuracy']
        and metrics['macro_f1'] >= thresholds['minimum_macro_f1']
        and metrics['accuracy'] - baseline >= thresholds['minimum_accuracy_improvement_over_baseline']
    ), float(baseline)


def evaluate_classifier_configuration(dataset, family, params, objective='production_class_weighted'):
    """Fit each Fold once; threshold selection consumes Validation only."""
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    objective_config = CLASSIFICATION_OBJECTIVES[objective]
    fold_predictions, fitted_rows = [], []
    for fold in folds:
        override = objective_config['class_weight']
        if family == 'Histogram Gradient Boosting Classifier':
            override = 'production'
        model = _classifier(family, params, class_weight_override=override)
        weights = None
        if objective_config['sample_weight'] == 'magnitude':
            count = fold['training_samples']
            returns = np.asarray(dataset.regression_labels[:count], dtype=float)
            weights = training_magnitude_sample_weights(returns)
        _fit_with_optional_weights(model, fold['x_train'], fold['y_classification_train'], weights)
        validation_probabilities = _positive_probabilities(model, fold['x_validation'])
        train_probabilities = _positive_probabilities(model, fold['x_train'])
        fold_predictions.append({
            'fold': fold,
            'labels': fold['y_classification_validation'],
            'probabilities': validation_probabilities,
            'roc_auc': _roc_auc_for_probabilities(
                fold['y_classification_validation'], validation_probabilities,
            ),
        })
        importance, kind = _importance_vector(
            model, fold['x_validation'], fold['y_classification_validation'],
            len(dataset.feature_names),
        )
        fitted_rows.append((model, train_probabilities, validation_probabilities, importance, kind))
    threshold_result = select_walk_forward_threshold(fold_predictions)
    threshold = threshold_result['threshold']
    fold_diagnostics = []
    importance_vectors = []
    for fold, fitted in zip(folds, fitted_rows):
        _model, train_probabilities, validation_probabilities, importance, _kind = fitted
        train_predictions = (train_probabilities >= threshold).astype(int)
        validation_predictions = (validation_probabilities >= threshold).astype(int)
        train_metrics = _classification_metrics(
            fold['y_classification_train'], train_predictions, train_probabilities,
        )
        validation_metrics = _classification_metrics(
            fold['y_classification_validation'], validation_predictions, validation_probabilities,
        )
        passed, baseline = _classification_fold_pass(validation_metrics, fold)
        fold_diagnostics.append({
            'fold': fold['fold'], 'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'], 'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'], 'train': train_metrics,
            'validation': validation_metrics, 'majority_baseline_accuracy': baseline,
            'baseline_improvement': validation_metrics['accuracy'] - baseline,
            'fold_passed': passed,
        })
        importance_vectors.append(importance)
    validation = threshold_result['metrics']
    train_ba = mean(row['train']['balanced_accuracy'] for row in fold_diagnostics)
    train_f1 = mean(row['train']['macro_f1'] for row in fold_diagnostics)
    train_auc_values = [row['train']['roc_auc'] for row in fold_diagnostics if row['train']['roc_auc'] is not None]
    baseline_improvements = [row['baseline_improvement'] for row in fold_diagnostics]
    fold_pass_ratio = mean(row['fold_passed'] for row in fold_diagnostics)
    return {
        'family': family, 'params': dict(params), 'objective': objective,
        'selected_threshold': float(threshold), 'fold_count': len(folds),
        'sample_count': sum(row['validation_samples'] for row in fold_diagnostics),
        'feature_count': len(dataset.feature_names),
        'minimum_training_samples': min(row['training_samples'] for row in fold_diagnostics),
        'samples_per_feature_ratio': min(row['training_samples'] for row in fold_diagnostics) / len(dataset.feature_names),
        'validation': validation,
        'train': {'balanced_accuracy': float(train_ba), 'macro_f1': float(train_f1),
                  'roc_auc': float(mean(train_auc_values)) if train_auc_values else None},
        'train_validation_gap': {
            'balanced_accuracy': float(train_ba - validation['mean_balanced_accuracy']),
            'macro_f1': float(train_f1 - validation['mean_macro_f1']),
            'roc_auc': float(mean(train_auc_values) - validation['mean_roc_auc'])
            if train_auc_values and validation['mean_roc_auc'] is not None else None,
        },
        'majority_baseline_accuracy': float(mean(row['majority_baseline_accuracy'] for row in fold_diagnostics)),
        'baseline_improvement': float(mean(baseline_improvements)),
        'fold_pass_ratio': float(fold_pass_ratio),
        'fold_stability': {'macro_f1_std': validation['std_macro_f1'],
                           'balanced_accuracy_std': validation['std_balanced_accuracy']},
        'selection_score': _walk_forward_selection_score(validation, threshold_result['threshold_stability']),
        'threshold_stability': threshold_result['threshold_stability'],
        'folds': fold_diagnostics,
        'importance_stability': _importance_stability(importance_vectors, dataset.feature_names, fitted_rows[0][4]),
        'independent_test_accessed': False,
    }


def evaluate_classification_families(dataset):
    family_results = []
    for family, configurations in CLASSIFICATION_FAMILY_CONFIGS.items():
        candidates = [evaluate_classifier_configuration(dataset, family, params) for params in configurations]
        selected = max(candidates, key=lambda row: (
            row['selection_score'], row['validation']['mean_macro_f1'],
            row['validation']['mean_balanced_accuracy'], -configurations.index(row['params']),
        ))
        family_results.append({**selected, 'searched_configurations': len(candidates),
                               'candidate_summaries': [_compact_classification(row) for row in candidates]})
    production = max(
        (row for row in family_results if row['family'] in ('Current Logistic Regression', 'Current Random Forest')),
        key=lambda row: row['selection_score'],
    )
    return {'families': family_results, 'production_baseline': production,
            'folds_use_independent_test': False}


def _compact_classification(row):
    return {'params': row['params'], 'selection_score': row['selection_score'],
            'balanced_accuracy': row['validation']['mean_balanced_accuracy'],
            'macro_f1': row['validation']['mean_macro_f1'],
            'roc_auc': row['validation']['mean_roc_auc'],
            'train_validation_gap': row['train_validation_gap']}


def _regression_training_target(fold, dataset, objective):
    y_train = np.asarray(fold['y_regression_train'], dtype=float)
    y_validation = np.asarray(fold['y_regression_validation'], dtype=float)
    train_scale = validation_scale = None
    metadata = {'threshold_source': None, 'future_volatility_used': False}
    if objective == 'volatility_scaled_return':
        volatility_index = dataset.regression_feature_names.index('volatility_20')
        train_scale = np.asarray(fold['x_regression_train'], dtype=float)[:, volatility_index]
        validation_scale = np.asarray(fold['x_regression_validation'], dtype=float)[:, volatility_index]
        y_train = y_train / train_scale
        metadata['scale_feature'] = 'trailing_volatility_20_available_at_t'
    elif objective == 'winsorized_return':
        lower, upper = np.quantile(y_train, (0.025, 0.975))
        y_train = np.clip(y_train, lower, upper)
        metadata.update({'threshold_source': 'training_fold_only', 'lower': float(lower), 'upper': float(upper)})
    return y_train, y_validation, train_scale, validation_scale, metadata


def evaluate_regression_configuration(dataset, candidate, objective='raw_return'):
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    pooled_labels, pooled_predictions, fold_rows, importance_vectors = [], [], [], []
    importance_kind = None
    for fold in folds:
        model = _regressor(candidate)
        y_fit, y_validation, train_scale, validation_scale, objective_metadata = _regression_training_target(
            fold, dataset, objective,
        )
        model.fit(fold['x_regression_train'], y_fit)
        validation_predictions = np.asarray(model.predict(fold['x_regression_validation']), dtype=float)
        train_predictions = np.asarray(model.predict(fold['x_regression_train']), dtype=float)
        if objective == 'volatility_scaled_return':
            validation_predictions = validation_predictions * validation_scale
            train_predictions = train_predictions * train_scale
        raw_train_labels = np.asarray(fold['y_regression_train'], dtype=float)
        validation_metrics = _regression_metrics(y_validation, validation_predictions)
        train_metrics = _regression_metrics(raw_train_labels, train_predictions)
        zero_metrics = _regression_metrics(y_validation, np.zeros(len(y_validation)))
        mae_improvement = (zero_metrics['mae'] - validation_metrics['mae']) / zero_metrics['mae']
        rmse_improvement = (zero_metrics['rmse'] - validation_metrics['rmse']) / zero_metrics['rmse']
        importance, importance_kind = _importance_vector(
            model, fold['x_regression_validation'], y_validation,
            len(dataset.regression_feature_names),
        )
        importance_vectors.append(importance)
        fold_rows.append({
            'fold': fold['fold'], 'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'], 'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'], 'train': train_metrics,
            'validation': validation_metrics, 'zero_return_baseline': zero_metrics,
            'mae_improvement': float(mae_improvement), 'rmse_improvement': float(rmse_improvement),
            'beats_zero_on_both': bool(mae_improvement > 0 and rmse_improvement > 0),
            'objective_metadata': objective_metadata,
        })
        pooled_labels.extend(y_validation)
        pooled_predictions.extend(validation_predictions)
    model_metrics = _regression_metrics(pooled_labels, pooled_predictions)
    zero = _regression_metrics(pooled_labels, np.zeros(len(pooled_labels)))
    mae_improvement = (zero['mae'] - model_metrics['mae']) / zero['mae']
    rmse_improvement = (zero['rmse'] - model_metrics['rmse']) / zero['rmse']
    improving_ratio = mean(row['beats_zero_on_both'] for row in fold_rows)
    train_mae = mean(row['train']['mae'] for row in fold_rows)
    train_rmse = mean(row['train']['rmse'] for row in fold_rows)
    train_r2 = mean(row['train']['r2'] for row in fold_rows)
    return {
        'model': candidate['model'], 'family': candidate['family'], 'params': dict(candidate['params']),
        'objective': objective, 'fold_count': len(folds), 'feature_count': len(dataset.regression_feature_names),
        'minimum_training_samples': min(row['training_samples'] for row in fold_rows),
        'samples_per_feature_ratio': min(row['training_samples'] for row in fold_rows) / len(dataset.regression_feature_names),
        'validation': {**model_metrics, 'zero_return_baseline': zero,
                       'mae_improvement': float(mae_improvement), 'rmse_improvement': float(rmse_improvement),
                       'improving_fold_ratio': float(improving_ratio),
                       'fold_mae_std': float(pstdev(row['validation']['mae'] for row in fold_rows))},
        'train': {'mae': float(train_mae), 'rmse': float(train_rmse), 'r2': float(train_r2)},
        'train_validation_gap': {
            'mae': float(model_metrics['mae'] - train_mae),
            'rmse': float(model_metrics['rmse'] - train_rmse),
            'r2': float(train_r2 - model_metrics['r2']),
        },
        'folds': fold_rows,
        'importance_stability': _importance_stability(
            importance_vectors, dataset.regression_feature_names, importance_kind,
        ),
        'independent_test_accessed': False,
    }


def evaluate_regression_families(dataset):
    rows = [evaluate_regression_configuration(dataset, candidate) for candidate in REGRESSION_FAMILY_CONFIGS]
    grouped = []
    for family in dict.fromkeys(candidate['family'] for candidate in REGRESSION_FAMILY_CONFIGS):
        candidates = [row for row in rows if row['family'] == family]
        selected = min(candidates, key=lambda row: (
            row['validation']['mae'], row['validation']['rmse'],
            -row['validation']['improving_fold_ratio'],
        ))
        grouped.append({**selected, 'searched_configurations': len(candidates),
                        'candidate_summaries': [_compact_regression(row) for row in candidates]})
    production_candidates = [row for row in rows if row['family'] != 'extra_trees']
    production = min(production_candidates, key=lambda row: (
        row['validation']['mae'], row['validation']['rmse'],
        -row['validation']['improving_fold_ratio'],
    ))
    return {'families': grouped, 'production_baseline': production,
            'folds_use_independent_test': False}


def _compact_regression(row):
    return {'params': row['params'], 'mae': row['validation']['mae'],
            'rmse': row['validation']['rmse'], 'r2': row['validation']['r2'],
            'mae_improvement': row['validation']['mae_improvement'],
            'rmse_improvement': row['validation']['rmse_improvement'],
            'train_validation_gap': row['train_validation_gap']}


def regression_target_diagnostics(dataset):
    split = build_purged_chronological_split(dataset)
    values = np.asarray(dataset.regression_labels[:split['development_end']], dtype=float)
    return {
        'scope': 'development_only', 'sample_count': len(values),
        'mean': float(np.mean(values)), 'median': float(np.median(values)),
        'standard_deviation': float(np.std(values)), 'skewness': float(skew(values)),
        'excess_kurtosis': float(kurtosis(values)),
        'absolute_return_over_5_percent_ratio': float(np.mean(np.abs(values) > 0.05)),
        'absolute_return_over_10_percent_ratio': float(np.mean(np.abs(values) > 0.10)),
        'independent_test_accessed': False,
    }


def _classification_context_summary(row):
    v = row['validation']
    return {'balanced_accuracy': v['mean_balanced_accuracy'], 'macro_f1': v['mean_macro_f1'],
            'roc_auc': v['mean_roc_auc'] if v['mean_roc_auc'] is not None else 0.5,
            'roc_auc_available': v['mean_roc_auc'] is not None,
            'minimum_recall': v['mean_minimum_class_recall'],
            'baseline_improvement': row['baseline_improvement'], 'fold_pass_ratio': row['fold_pass_ratio'],
            'train_validation_gap': row['train_validation_gap']['macro_f1']}


def _regression_context_summary(row):
    v = row['validation']
    return {'mae_improvement': v['mae_improvement'], 'rmse_improvement': v['rmse_improvement'],
            'improving_fold_ratio': v['improving_fold_ratio'], 'r2': v['r2'],
            'train_validation_gap': row['train_validation_gap']['mae']}


def aggregate_model_results(context_results, task):
    names = sorted({row['name'] for row in context_results})
    aggregates = []
    for name in names:
        rows = [row for row in context_results if row['name'] == name]
        values = [row['summary'] for row in rows]
        if task == 'classification':
            aggregates.append({
                'name': name, 'context_count': len(rows),
                'mean_balanced_accuracy': float(mean(v['balanced_accuracy'] for v in values)),
                'mean_macro_f1': float(mean(v['macro_f1'] for v in values)),
                'mean_roc_auc': float(mean(v['roc_auc'] for v in values)),
                'mean_baseline_improvement': float(mean(v['baseline_improvement'] for v in values)),
                'mean_fold_pass_ratio': float(mean(v['fold_pass_ratio'] for v in values)),
                'mean_train_validation_gap': float(mean(v['train_validation_gap'] for v in values)),
            })
        else:
            aggregates.append({
                'name': name, 'context_count': len(rows),
                'mean_mae_improvement': float(mean(v['mae_improvement'] for v in values)),
                'mean_rmse_improvement': float(mean(v['rmse_improvement'] for v in values)),
                'mean_improving_fold_ratio': float(mean(v['improving_fold_ratio'] for v in values)),
                'mean_r2': float(mean(v['r2'] for v in values)),
                'mean_train_validation_gap': float(mean(v['train_validation_gap'] for v in values)),
            })
    return aggregates


def select_cross_context_candidate(context_results, task, baseline_name='Production Baseline'):
    if any(
        row.get('independent_test') is not None
        or (row.get('result') or {}).get('independent_test_accessed') is True
        for row in context_results
    ):
        raise ValueError('Independent Test data cannot enter candidate selection.')
    rules = ARCHITECTURE_CANDIDATE_RULES[task]
    contexts = {(row['symbol'], row['lookback']) for row in context_results if row['name'] == baseline_name}
    evaluations = []
    for name in sorted({row['name'] for row in context_results if row['name'] != baseline_name}):
        deltas, improved, harmed, symbols = [], 0, 0, set()
        for symbol, lookback in sorted(contexts):
            baseline = next(row['summary'] for row in context_results if row['name'] == baseline_name and row['symbol'] == symbol and row['lookback'] == lookback)
            candidate = next(row['summary'] for row in context_results if row['name'] == name and row['symbol'] == symbol and row['lookback'] == lookback)
            if task == 'classification':
                delta = {key: candidate[key] - baseline[key] for key in (
                    'balanced_accuracy', 'macro_f1', 'roc_auc', 'baseline_improvement', 'fold_pass_ratio',
                )}
                context_improved = delta['balanced_accuracy'] > 0 and delta['macro_f1'] > 0 and delta['roc_auc'] >= -0.01
                context_harmed = min(delta['balanced_accuracy'], delta['macro_f1']) < -0.03
            else:
                delta = {key: candidate[key] - baseline[key] for key in (
                    'mae_improvement', 'rmse_improvement', 'improving_fold_ratio',
                )}
                context_improved = delta['mae_improvement'] > 0 and delta['rmse_improvement'] > 0
                context_harmed = min(delta['mae_improvement'], delta['rmse_improvement']) < -0.03
            delta['train_validation_gap_increase'] = candidate['train_validation_gap'] - baseline['train_validation_gap']
            deltas.append(delta)
            if context_improved:
                improved += 1; symbols.add(symbol)
            harmed += bool(context_harmed)
        means = {key: float(mean(delta[key] for delta in deltas)) for key in deltas[0]}
        if task == 'classification':
            passed = (improved >= rules['minimum_improved_contexts'] and len(symbols) >= rules['minimum_improved_symbols']
                      and means['balanced_accuracy'] >= rules['minimum_mean_ba_delta']
                      and means['macro_f1'] >= rules['minimum_mean_macro_f1_delta']
                      and means['roc_auc'] >= rules['minimum_mean_auc_delta']
                      and means['baseline_improvement'] >= rules['minimum_mean_baseline_improvement_delta']
                      and means['fold_pass_ratio'] >= rules['minimum_fold_pass_ratio_delta']
                      and means['train_validation_gap_increase'] <= rules['maximum_train_validation_gap_increase']
                      and harmed <= rules['maximum_harmed_contexts'])
            rank = means['macro_f1'] + means['balanced_accuracy'] + means['roc_auc']
        else:
            passed = (improved >= rules['minimum_improved_contexts'] and len(symbols) >= rules['minimum_improved_symbols']
                      and means['mae_improvement'] >= rules['minimum_mean_mae_improvement_delta']
                      and means['rmse_improvement'] >= rules['minimum_mean_rmse_improvement_delta']
                      and means['improving_fold_ratio'] >= rules['minimum_improving_fold_ratio_delta']
                      and means['train_validation_gap_increase'] <= rules['maximum_train_validation_gap_increase']
                      and harmed <= rules['maximum_harmed_contexts'])
            rank = means['mae_improvement'] + means['rmse_improvement']
        evaluations.append({'name': name, 'passed': bool(passed), 'improved_contexts': improved,
                            'improved_symbols': sorted(symbols), 'harmed_contexts': harmed,
                            'mean_deltas': means, 'rank': float(rank)})
    eligible = [row for row in evaluations if row['passed']]
    selected = max(eligible, key=lambda row: row['rank'])['name'] if eligible else None
    return {'selected_candidate': selected, 'rules': rules, 'evaluations': evaluations,
            'selection_source': 'development_purged_walk_forward_only',
            'independent_test_accessed': False}


def classification_objective_experiments(dataset, family_result):
    return [evaluate_classifier_configuration(
        dataset, family_result['family'], family_result['params'], objective,
    ) for objective in CLASSIFICATION_OBJECTIVES]


def regression_objective_experiments(dataset, family_result):
    candidate = {'model': family_result['model'], 'family': family_result['family'], 'params': family_result['params']}
    return [evaluate_regression_configuration(dataset, candidate, objective) for objective in REGRESSION_OBJECTIVES]


def evaluate_classification_independent_test(dataset, frozen):
    split = build_purged_chronological_split(dataset)
    x_development = dataset.features[:split['development_end']]
    y_development = dataset.classification_labels[:split['development_end']]
    model = _classifier(frozen['family'], frozen['params'])
    model.fit(x_development, y_development)
    probabilities = _positive_probabilities(model, split['x_test'])
    predictions = (probabilities >= frozen['selected_threshold']).astype(int)
    return {'metrics': _classification_metrics(split['y_classification_test'], predictions, probabilities),
            'test_samples': split['test_samples'], 'model_refit_after_test': False,
            'selection_source': 'frozen_development_candidate'}


def evaluate_regression_independent_test(dataset, frozen):
    split = build_purged_chronological_split(dataset)
    candidate = {'model': frozen['model'], 'family': frozen['family'], 'params': frozen['params']}
    model = _regressor(candidate)
    y_train = np.asarray(dataset.regression_labels[:split['development_end']], dtype=float)
    x_train = dataset.regression_features[:split['development_end']]
    objective = frozen['objective']
    test_scale = train_scale = None
    if objective == 'volatility_scaled_return':
        index = dataset.regression_feature_names.index('volatility_20')
        train_scale = np.asarray(x_train)[:, index]
        test_scale = np.asarray(split['x_regression_test'])[:, index]
        y_train = y_train / train_scale
    elif objective == 'winsorized_return':
        lower, upper = np.quantile(y_train, (0.025, 0.975))
        y_train = np.clip(y_train, lower, upper)
    model.fit(x_train, y_train)
    predictions = np.asarray(model.predict(split['x_regression_test']), dtype=float)
    if test_scale is not None:
        predictions *= test_scale
    labels = np.asarray(split['y_regression_test'], dtype=float)
    zero = _regression_metrics(labels, np.zeros(len(labels)))
    metrics = _regression_metrics(labels, predictions)
    return {'metrics': metrics, 'zero_return_baseline': zero,
            'mae_improvement': float((zero['mae'] - metrics['mae']) / zero['mae']),
            'rmse_improvement': float((zero['rmse'] - metrics['rmse']) / zero['rmse']),
            'test_samples': split['test_samples'], 'model_refit_after_test': False,
            'selection_source': 'frozen_development_candidate'}
