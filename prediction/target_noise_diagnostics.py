from math import isfinite
from statistics import mean, pstdev

import numpy as np

from prediction.ml_service import (
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    _classification_metrics,
    _logistic_regression,
    _predictions_for_threshold,
    _random_forest_classifier,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    evaluate_classification_quality_gate,
    evaluate_classifier_walk_forward,
    evaluate_independent_test_quality_gate,
    majority_class_baseline_accuracy,
    tune_random_forest_classifier,
)


TARGET_NOISE_BANDS = (0.0, 0.001, 0.0025, 0.005)

# Research-only candidate rules. They intentionally require a broad development
# improvement and useful coverage; none of these values affect the production
# Prediction quality gate or target definition.
TARGET_NOISE_CANDIDATE_RULES = {
    'minimum_average_development_coverage': 0.70,
    'minimum_improved_context_count': 4,
    'minimum_improved_symbol_count': 2,
    'minimum_mean_macro_f1_delta': 0.005,
    'minimum_mean_balanced_accuracy_delta': -0.005,
    'minimum_mean_roc_auc_delta': -0.005,
    'minimum_mean_minimum_class_recall_delta': -0.01,
    'minimum_mean_baseline_improvement_delta': 0.0,
    'maximum_macro_f1_std_increase': 0.02,
    'per_context_balanced_accuracy_tolerance': 0.005,
    'per_context_roc_auc_tolerance': 0.005,
}


def _retained_positions(returns, start, end, noise_band):
    if float(noise_band) == 0.0:
        return tuple(range(start, end))
    return tuple(
        index
        for index in range(start, end)
        if abs(float(returns[index])) > float(noise_band)
    )


def _filtered_partition(dataset, start, end, noise_band):
    positions = _retained_positions(
        dataset.regression_labels,
        start,
        end,
        noise_band,
    )
    labels = tuple(dataset.classification_labels[index] for index in positions)
    return {
        'positions': positions,
        'features': tuple(dataset.features[index] for index in positions),
        'labels': labels,
        'returns': tuple(dataset.regression_labels[index] for index in positions),
        'original_sample_count': int(end - start),
        'retained_sample_count': len(positions),
        'excluded_sample_count': int(end - start - len(positions)),
        'coverage_ratio': float(len(positions) / (end - start)) if end > start else 0.0,
        'up_count': int(sum(label == 1 for label in labels)),
        'down_count': int(sum(label == 0 for label in labels)),
        'up_ratio': float(sum(label == 1 for label in labels) / len(labels)) if labels else 0.0,
        'down_ratio': float(sum(label == 0 for label in labels) / len(labels)) if labels else 0.0,
    }


def future_return_distribution(dataset, *, development_only=True):
    """Describe the one-day label return without opening Test during selection."""
    if dataset.horizon != 1:
        raise ValueError('Target-noise diagnostics require a 1-trading-day dataset.')
    split = build_purged_chronological_split(dataset)
    end = split['development_end'] if development_only else dataset.sample_count
    returns = np.asarray(dataset.regression_labels[:end], dtype=float)
    if not len(returns):
        raise ValueError('No labeled returns are available for target-noise diagnostics.')
    return {
        'scope': 'development_only' if development_only else 'all_labeled_rows',
        'sample_count': int(len(returns)),
        'mean': float(np.mean(returns)),
        'median': float(np.median(returns)),
        'standard_deviation': float(np.std(returns)),
        'minimum': float(np.min(returns)),
        'maximum': float(np.max(returns)),
        'q25': float(np.quantile(returns, 0.25)),
        'q75': float(np.quantile(returns, 0.75)),
        # The request uses strict '<'. Band filtering below excludes '<=' so
        # exact boundary values are treated consistently and transparently.
        'absolute_return_below': {
            '0.001': float(np.mean(np.abs(returns) < 0.001)),
            '0.0025': float(np.mean(np.abs(returns) < 0.0025)),
            '0.005': float(np.mean(np.abs(returns) < 0.005)),
        },
    }


def _filtered_walk_forward_folds(dataset, split, noise_band):
    base_folds = build_purged_walk_forward_folds(dataset, split)
    filtered_folds = []
    for fold in base_folds:
        original_training_end = fold['training_samples']
        validation_start = original_training_end + fold['gap_size']
        validation_end = validation_start + fold['validation_samples']
        training = _filtered_partition(
            dataset, 0, original_training_end, noise_band,
        )
        validation = _filtered_partition(
            dataset, validation_start, validation_end, noise_band,
        )
        minority_count = min(validation['up_count'], validation['down_count'])
        filtered_folds.append({
            **fold,
            'x_train': training['features'],
            'y_classification_train': training['labels'],
            'x_validation': validation['features'],
            'y_classification_validation': validation['labels'],
            'training_samples': training['retained_sample_count'],
            'validation_samples': validation['retained_sample_count'],
            'actual_up_count': validation['up_count'],
            'actual_down_count': validation['down_count'],
            'minority_class_count': minority_count,
            'minority_class_ratio': (
                minority_count / validation['retained_sample_count']
                if validation['retained_sample_count'] else 0.0
            ),
            'severe_class_imbalance': (
                minority_count < 3
                or validation['up_ratio'] < 0.10
                or validation['down_ratio'] < 0.10
            ),
            'original_training_samples': original_training_end,
            'original_validation_samples': fold['validation_samples'],
            'training_coverage': training['coverage_ratio'],
            'validation_coverage': validation['coverage_ratio'],
            'retained_training_positions': training['positions'],
            'retained_validation_positions': validation['positions'],
        })
    return tuple(filtered_folds)


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


def _training_majority_baseline(fold):
    training_up = sum(label == 1 for label in fold['y_classification_train'])
    majority = 1 if training_up > len(fold['y_classification_train']) - training_up else 0
    labels = fold['y_classification_validation']
    return float(sum(label == majority for label in labels) / len(labels)) if labels else 0.0


def _fold_diagnostics(selected, folds):
    thresholds = PREDICTION_QUALITY_GATE_THRESHOLDS
    diagnostics = []
    for metrics, fold in zip(selected['fold_metrics'], folds):
        baseline = _training_majority_baseline(fold)
        improvement = float(metrics['accuracy'] - baseline)
        reasons = []
        if metrics['actual_up_count'] == 0 or metrics['actual_down_count'] == 0:
            reasons.append('single_class_actual_labels')
        if metrics['predicted_up_count'] == 0 or metrics['predicted_down_count'] == 0:
            reasons.append('single_class_predictions')
        if metrics['balanced_accuracy'] < thresholds['minimum_balanced_accuracy']:
            reasons.append('balanced_accuracy_below_minimum')
        if metrics['macro_f1'] < thresholds['minimum_macro_f1']:
            reasons.append('macro_f1_below_minimum')
        if improvement < thresholds['minimum_accuracy_improvement_over_baseline']:
            reasons.append('did_not_beat_majority_baseline')
        diagnostics.append({
            **metrics,
            'original_training_samples': fold['original_training_samples'],
            'retained_training_samples': fold['training_samples'],
            'original_validation_samples': fold['original_validation_samples'],
            'retained_validation_samples': fold['validation_samples'],
            'validation_coverage': fold['validation_coverage'],
            'majority_baseline_accuracy': baseline,
            'accuracy_improvement_over_baseline': improvement,
            'fold_passed': not reasons,
            'fold_reason_codes': reasons,
        })
    return diagnostics


def evaluate_noise_band_development(dataset, noise_band):
    """Tune and compare one band using Development Walk-Forward only.

    No Test features, labels, probabilities, metrics, or coverage are read here.
    """
    if dataset.horizon != 1:
        raise ValueError('Target-noise diagnostics require purge gap = horizon = 1.')
    if float(noise_band) not in TARGET_NOISE_BANDS:
        raise ValueError('Unsupported research noise band.')
    split = build_purged_chronological_split(dataset)
    if split['gap_size'] != 1:
        raise RuntimeError('Target-noise purge gap must remain exactly 1.')
    folds = _filtered_walk_forward_folds(dataset, split, noise_band)
    if not folds or any(
        not fold['x_train']
        or not fold['x_validation']
        or len(set(fold['y_classification_train'])) < 2
        for fold in folds
    ):
        raise ValueError('Noise-band filtering left an unusable Walk-Forward fold.')

    evaluations = [
        {
            'model': 'Logistic Regression',
            'params': None,
            **evaluate_classifier_walk_forward(_logistic_regression, folds),
        },
        {
            'model': 'Random Forest Classifier',
            **tune_random_forest_classifier(folds),
        },
    ]
    for evaluation in evaluations:
        evaluation['quality_gate'] = evaluate_classification_quality_gate(
            {**evaluation['metrics'], 'fold_metrics': evaluation['fold_metrics']},
            folds,
        )
    selected = _select_classifier(evaluations)
    development = _filtered_partition(
        dataset, 0, split['development_end'], noise_band,
    )
    fold_diagnostics = _fold_diagnostics(selected, folds)
    fold_macro_f1 = [fold['macro_f1'] for fold in fold_diagnostics]
    fold_balanced_accuracy = [fold['balanced_accuracy'] for fold in fold_diagnostics]
    return {
        'noise_band': float(noise_band),
        'scope': 'development_walk_forward_only',
        'coverage': development,
        'selected_model': selected['model'],
        'selected_params': selected['params'],
        'selected_threshold': selected['threshold'],
        'metrics': selected['metrics'],
        'quality_gate': selected['quality_gate'],
        'folds': fold_diagnostics,
        'fold_pass_count': int(sum(fold['fold_passed'] for fold in fold_diagnostics)),
        'fold_count': len(fold_diagnostics),
        'fold_pass_ratio': float(
            sum(fold['fold_passed'] for fold in fold_diagnostics) / len(fold_diagnostics)
        ),
        'fold_stability': {
            'macro_f1_standard_deviation': float(pstdev(fold_macro_f1)),
            'balanced_accuracy_standard_deviation': float(
                pstdev(fold_balanced_accuracy)
            ),
            'threshold': selected['threshold_stability'],
        },
        'candidate_models': evaluations,
        'purge_gap': split['gap_size'],
        'walk_forward_chronological': True,
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
        'split_boundaries': split['boundaries'],
    }


def _development_summary(result):
    metrics = result['metrics']
    gate = result['quality_gate']
    return {
        'coverage': result['coverage']['coverage_ratio'],
        'balanced_accuracy': metrics['mean_balanced_accuracy'],
        'macro_f1': metrics['mean_macro_f1'],
        'roc_auc': metrics['mean_roc_auc'],
        'minimum_class_recall': metrics['mean_minimum_class_recall'],
        'baseline_improvement': gate['observed']['accuracy_improvement_over_baseline'],
        'macro_f1_std': result['fold_stability']['macro_f1_standard_deviation'],
    }


def select_research_candidate_noise_band(development_results):
    """Select at most one band without accepting any Test-bearing input."""
    if any('independent_test' in result for result in development_results):
        raise ValueError('Independent Test data cannot enter noise-band selection.')
    contexts = {(result['symbol'], result['lookback']) for result in development_results}
    baseline_by_context = {
        (result['symbol'], result['lookback']): result
        for result in development_results
        if result['noise_band'] == 0.0
    }
    if set(baseline_by_context) != contexts:
        raise ValueError('Every development context requires a production-target baseline.')

    rules = TARGET_NOISE_CANDIDATE_RULES
    candidates = []
    for band in TARGET_NOISE_BANDS[1:]:
        rows = [result for result in development_results if result['noise_band'] == band]
        if len(rows) != len(contexts):
            raise ValueError(f'Noise band {band} is missing a development context.')
        comparisons = []
        for row in rows:
            baseline = baseline_by_context[(row['symbol'], row['lookback'])]
            candidate_summary = _development_summary(row)
            baseline_summary = _development_summary(baseline)
            deltas = {
                key: float(candidate_summary[key] - baseline_summary[key])
                for key in (
                    'balanced_accuracy',
                    'macro_f1',
                    'roc_auc',
                    'minimum_class_recall',
                    'baseline_improvement',
                    'macro_f1_std',
                )
            }
            improved = (
                deltas['macro_f1'] > 0
                and deltas['balanced_accuracy']
                >= -rules['per_context_balanced_accuracy_tolerance']
                and deltas['roc_auc'] >= -rules['per_context_roc_auc_tolerance']
            )
            comparisons.append({
                'symbol': row['symbol'],
                'lookback': row['lookback'],
                'coverage': candidate_summary['coverage'],
                'deltas': deltas,
                'context_improved': improved,
            })
        mean_deltas = {
            key: float(mean(comparison['deltas'][key] for comparison in comparisons))
            for key in comparisons[0]['deltas']
        }
        improved_symbols = {
            symbol
            for symbol in {comparison['symbol'] for comparison in comparisons}
            if sum(
                comparison['context_improved']
                for comparison in comparisons
                if comparison['symbol'] == symbol
            ) >= 1
        }
        average_coverage = float(mean(item['coverage'] for item in comparisons))
        improved_context_count = sum(item['context_improved'] for item in comparisons)
        checks = {
            'coverage': average_coverage >= rules['minimum_average_development_coverage'],
            'multiple_contexts': (
                improved_context_count >= rules['minimum_improved_context_count']
            ),
            'multiple_symbols': (
                len(improved_symbols) >= rules['minimum_improved_symbol_count']
            ),
            'macro_f1': (
                mean_deltas['macro_f1'] >= rules['minimum_mean_macro_f1_delta']
            ),
            'balanced_accuracy': (
                mean_deltas['balanced_accuracy']
                >= rules['minimum_mean_balanced_accuracy_delta']
            ),
            'roc_auc': (
                mean_deltas['roc_auc'] >= rules['minimum_mean_roc_auc_delta']
            ),
            'minimum_class_recall': (
                mean_deltas['minimum_class_recall']
                >= rules['minimum_mean_minimum_class_recall_delta']
            ),
            'baseline_improvement': (
                mean_deltas['baseline_improvement']
                >= rules['minimum_mean_baseline_improvement_delta']
            ),
            'fold_stability': (
                mean_deltas['macro_f1_std']
                <= rules['maximum_macro_f1_std_increase']
            ),
        }
        score = float(
            0.30 * mean_deltas['macro_f1']
            + 0.25 * mean_deltas['balanced_accuracy']
            + 0.20 * mean_deltas['roc_auc']
            + 0.15 * mean_deltas['minimum_class_recall']
            + 0.10 * mean_deltas['baseline_improvement']
            - 0.05 * max(0.0, mean_deltas['macro_f1_std'])
        )
        candidates.append({
            'noise_band': band,
            'eligible': all(checks.values()),
            'checks': checks,
            'average_development_coverage': average_coverage,
            'improved_context_count': int(improved_context_count),
            'improved_symbol_count': len(improved_symbols),
            'improved_symbols': sorted(improved_symbols),
            'mean_deltas_vs_production_target': mean_deltas,
            'walk_forward_only_score': score,
            'contexts': comparisons,
        })
    eligible = [candidate for candidate in candidates if candidate['eligible']]
    selected = max(
        eligible,
        key=lambda item: (
            item['walk_forward_only_score'],
            item['average_development_coverage'],
            -item['noise_band'],
        ),
    ) if eligible else None
    return {
        'research_candidate_noise_band': (
            selected['noise_band'] if selected is not None else None
        ),
        'selected_candidate': selected,
        'candidates': candidates,
        'selection_source': 'development_purged_walk_forward_only',
        'independent_test_used': False,
        'rules': rules,
    }


def evaluate_frozen_noise_band_on_independent_test(dataset, development_result):
    """Evaluate one already-frozen development choice on Test exactly once."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a development-only frozen evaluation.')
    split = build_purged_chronological_split(dataset)
    band = development_result['noise_band']
    development = _filtered_partition(
        dataset, 0, split['development_end'], band,
    )
    test = _filtered_partition(
        dataset,
        split['final_test_start'],
        split['final_test_start'] + split['test_samples'],
        band,
    )
    model = (
        _logistic_regression()
        if development_result['selected_model'] == 'Logistic Regression'
        else _random_forest_classifier(development_result['selected_params'])
    )
    model.fit(development['features'], development['labels'])
    probabilities = model.predict_proba(test['features'])[
        :, list(model.classes_).index(1)
    ]
    predictions = _predictions_for_threshold(
        probabilities,
        development_result['selected_threshold'],
    )
    metrics = _classification_metrics(test['labels'], predictions, probabilities)
    baseline = majority_class_baseline_accuracy(test['labels'])
    gate = evaluate_independent_test_quality_gate(metrics)
    return {
        'noise_band': band,
        'scope': 'final_untouched_independent_test',
        'frozen_model': development_result['selected_model'],
        'frozen_params': development_result['selected_params'],
        'frozen_threshold': development_result['selected_threshold'],
        'coverage': test,
        'metrics': {
            **metrics,
            'majority_baseline_accuracy': baseline,
            'accuracy_improvement_over_baseline': float(metrics['accuracy'] - baseline),
        },
        'quality_gate': gate,
        'fit_scope': 'noise-filtered_development_before_test',
        'test_used_for_model_selection': False,
        'test_used_for_hyperparameter_tuning': False,
        'test_used_for_threshold_selection': False,
        'model_refit_after_test': False,
        'test_evaluation_count_for_this_frozen_context': 1,
        'purge_gap': split['gap_size'],
        'validation_test_purge_safe': split['boundaries']['validation_test_purge_safe'],
    }
