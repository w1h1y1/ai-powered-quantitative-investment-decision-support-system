"""Offline confidence-based abstention diagnostics for one-day classification.

This module deliberately sits outside the production Prediction service.  It
reuses the production feature set, target, purged Walk-Forward folds, classifier
selection, and threshold, but never changes the API publication decision.
"""

from statistics import mean, pstdev

import numpy as np

from prediction.ml_service import (
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


# The labels retain the familiar 55/45 notation.  Because production selects a
# development-only decision threshold that is often not 0.5, the numeric margin
# is applied symmetrically around that frozen threshold instead of mechanically
# around 0.5.
ABSTENTION_RULES = (
    {'name': 'none', 'label': 'No Abstention', 'margin': 0.0},
    {'name': '55_45', 'label': '55/45-equivalent margin', 'margin': 0.05},
    {'name': '60_40', 'label': '60/40-equivalent margin', 'margin': 0.10},
    {'name': '65_35', 'label': '65/35-equivalent margin', 'margin': 0.15},
)

# Research-only selection rules.  They are intentionally centralized and do
# not affect the production model-level quality gates.  A rule must improve
# several contexts and most folds while retaining useful coverage.
ABSTENTION_CANDIDATE_RULES = {
    'minimum_average_development_coverage': 0.50,
    'minimum_improved_context_count': 4,
    'minimum_improved_symbol_count': 2,
    'minimum_mean_balanced_accuracy_delta': 0.01,
    'minimum_mean_macro_f1_delta': 0.01,
    'minimum_mean_minimum_class_recall_delta': 0.0,
    'minimum_mean_baseline_improvement_delta': 0.01,
    'minimum_improved_fold_ratio': 0.60,
    'maximum_harmed_context_count': 1,
    'maximum_context_balanced_accuracy_decline': 0.03,
    'maximum_context_macro_f1_decline': 0.03,
    'maximum_macro_f1_std_increase': 0.02,
}


def _model_factory(model_name, params):
    if model_name == 'Logistic Regression':
        return _logistic_regression
    if model_name == 'Random Forest Classifier':
        return lambda: _random_forest_classifier(params)
    raise ValueError(f'Unsupported classification model: {model_name}')


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


def probability_distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {
            'count': 0,
            'mean': None,
            'standard_deviation': None,
            'minimum': None,
            'q25': None,
            'median': None,
            'q75': None,
            'maximum': None,
        }
    return {
        'count': int(len(values)),
        'mean': float(np.mean(values)),
        'standard_deviation': float(np.std(values)),
        'minimum': float(np.min(values)),
        'q25': float(np.quantile(values, 0.25)),
        'median': float(np.median(values)),
        'q75': float(np.quantile(values, 0.75)),
        'maximum': float(np.max(values)),
    }


def probability_quality_diagnostics(labels, probabilities, selected_threshold, bin_count=10):
    """Describe raw, uncalibrated out-of-sample probabilities."""
    labels = np.asarray(labels, dtype=np.int8)
    probabilities = np.asarray(probabilities, dtype=float)
    if len(labels) != len(probabilities):
        raise ValueError('Labels and probabilities must have equal length.')
    if not len(labels):
        raise ValueError('Probability diagnostics require at least one sample.')
    clipped = np.clip(probabilities, 1e-15, 1 - 1e-15)
    brier_score = float(np.mean((probabilities - labels) ** 2))
    log_loss = float(-np.mean(
        (labels * np.log(clipped)) + ((1 - labels) * np.log(1 - clipped))
    ))
    roc_auc = None
    if len(set(labels.tolist())) == 2:
        from sklearn.metrics import roc_auc_score

        roc_auc = float(roc_auc_score(labels, probabilities))

    calibration_bins = []
    expected_calibration_error = 0.0
    for bin_index in range(bin_count):
        lower = bin_index / bin_count
        upper = (bin_index + 1) / bin_count
        mask = (
            (probabilities >= lower)
            & (probabilities <= upper if bin_index == bin_count - 1 else probabilities < upper)
        )
        count = int(np.sum(mask))
        mean_probability = float(np.mean(probabilities[mask])) if count else None
        actual_up_rate = float(np.mean(labels[mask])) if count else None
        absolute_gap = (
            abs(mean_probability - actual_up_rate) if count else None
        )
        if count:
            expected_calibration_error += (count / len(labels)) * absolute_gap
        calibration_bins.append({
            'lower_bound': float(lower),
            'upper_bound': float(upper),
            'sample_count': count,
            'mean_predicted_probability': mean_probability,
            'actual_up_rate': actual_up_rate,
            'absolute_calibration_gap': absolute_gap,
        })

    return {
        'probability_source': 'raw_predict_proba_class_1',
        'calibration_method': 'none',
        'probabilities_are_calibrated': False,
        'interpretation_warning': (
            'Raw classifier scores are not calibrated probabilities and should not be '
            'interpreted as literal real-world UP frequencies.'
        ),
        'sample_count': int(len(labels)),
        'brier_score': brier_score,
        'log_loss': log_loss,
        'roc_auc': roc_auc,
        'expected_calibration_error': float(expected_calibration_error),
        'calibration_bin_count': int(bin_count),
        'calibration_bins': calibration_bins,
        'all_probabilities': probability_distribution(probabilities),
        'actual_up_probabilities': probability_distribution(probabilities[labels == 1]),
        'actual_down_probabilities': probability_distribution(probabilities[labels == 0]),
        'distance_from_selected_threshold': probability_distribution(
            np.abs(probabilities - float(selected_threshold))
        ),
        'distance_from_point_five': probability_distribution(
            np.abs(probabilities - 0.5)
        ),
    }


def apply_abstention(probabilities, selected_threshold, margin):
    """Return published positions/predictions using model output only.

    The function intentionally accepts no labels or future returns.  ABSTAIN is
    an instance-level lack of directional signal, not a prediction error.
    """
    probabilities = tuple(float(value) for value in probabilities)
    threshold = float(selected_threshold)
    margin = float(margin)
    if not 0 <= threshold <= 1:
        raise ValueError('Selected threshold must be between 0 and 1.')
    if margin < 0:
        raise ValueError('Abstention margin cannot be negative.')
    lower_bound = max(0.0, threshold - margin)
    upper_bound = min(1.0, threshold + margin)
    if margin == 0:
        positions = tuple(range(len(probabilities)))
        predictions = tuple(_predictions_for_threshold(probabilities, threshold))
    else:
        positions = tuple(
            index
            for index, probability in enumerate(probabilities)
            if probability <= lower_bound or probability >= upper_bound
        )
        predictions = tuple(
            1 if probabilities[index] >= upper_bound else 0
            for index in positions
        )
    return {
        'positions': positions,
        'predictions': predictions,
        'selected_threshold': threshold,
        'margin': margin,
        'lower_bound': lower_bound,
        'upper_bound': upper_bound,
    }


def evaluate_selective_predictions(labels, probabilities, selected_threshold, margin):
    labels = tuple(int(value) for value in labels)
    probabilities = tuple(float(value) for value in probabilities)
    decision = apply_abstention(probabilities, selected_threshold, margin)
    positions = decision['positions']
    published_labels = tuple(labels[index] for index in positions)
    published_probabilities = tuple(probabilities[index] for index in positions)
    predictions = decision['predictions']
    total_samples = len(labels)
    published_samples = len(positions)
    abstained_samples = total_samples - published_samples
    coverage = published_samples / total_samples if total_samples else 0.0
    if published_samples:
        metrics = _classification_metrics(
            published_labels,
            predictions,
            published_probabilities,
        )
        majority_baseline = majority_class_baseline_accuracy(published_labels)
        improvement = float(metrics['accuracy'] - majority_baseline)
    else:
        metrics = {
            'accuracy': None,
            'balanced_accuracy': None,
            'precision': None,
            'recall': None,
            'f1': None,
            'macro_f1': None,
            'up_recall': None,
            'down_recall': None,
            'specificity': None,
            'minimum_class_recall': None,
            'actual_up_count': 0,
            'actual_down_count': 0,
            'predicted_up_count': 0,
            'predicted_down_count': 0,
            'degenerate_threshold': True,
            'roc_auc': None,
        }
        majority_baseline = None
        improvement = None
    return {
        **decision,
        'total_samples': total_samples,
        'published_samples': published_samples,
        'abstained_samples': abstained_samples,
        'coverage': float(coverage),
        'abstention_rate': float(1 - coverage) if total_samples else 0.0,
        'majority_baseline_accuracy': majority_baseline,
        'accuracy_improvement_over_majority_baseline': improvement,
        **metrics,
    }


def _fit_selected_fold_probabilities(selected, folds):
    factory = _model_factory(selected['model'], selected.get('params'))
    records = []
    for fold in folds:
        model = factory()
        model.fit(fold['x_train'], fold['y_classification_train'])
        probabilities = model.predict_proba(fold['x_validation'])[
            :, list(model.classes_).index(1)
        ]
        records.append({
            'fold': fold['fold'],
            'training_samples': fold['training_samples'],
            'validation_samples': fold['validation_samples'],
            'gap_size': fold['gap_size'],
            'purge_safe': fold['purge_safe'],
            'labels': tuple(fold['y_classification_validation']),
            'probabilities': tuple(float(value) for value in probabilities),
            'fit_count': 1,
            'predict_proba_count': 1,
        })
    return records


def _optional_mean(values):
    valid = [float(value) for value in values if value is not None]
    return float(mean(valid)) if valid else None


def _optional_std(values):
    valid = [float(value) for value in values if value is not None]
    return float(pstdev(valid)) if valid else None


def _rule_evaluation(rule, fold_probability_records, selected_threshold):
    fold_results = []
    pooled_labels = []
    pooled_probabilities = []
    for record in fold_probability_records:
        fold_result = evaluate_selective_predictions(
            record['labels'],
            record['probabilities'],
            selected_threshold,
            rule['margin'],
        )
        fold_results.append({
            'fold': record['fold'],
            'training_samples': record['training_samples'],
            'validation_samples': record['validation_samples'],
            'gap_size': record['gap_size'],
            'purge_safe': record['purge_safe'],
            **fold_result,
        })
        pooled_labels.extend(
            record['labels'][index] for index in fold_result['positions']
        )
        pooled_probabilities.extend(
            record['probabilities'][index] for index in fold_result['positions']
        )
    pooled_result = evaluate_selective_predictions(
        pooled_labels,
        pooled_probabilities,
        selected_threshold,
        0.0,
    )
    # The pooled arrays already contain only published rows, so the second call
    # has 100% internal coverage.  Restore overall Walk-Forward coverage/counts.
    total_samples = sum(record['validation_samples'] for record in fold_probability_records)
    published_samples = len(pooled_labels)
    pooled_result.update({
        'total_samples': total_samples,
        'published_samples': published_samples,
        'abstained_samples': total_samples - published_samples,
        'coverage': float(published_samples / total_samples) if total_samples else 0.0,
        'abstention_rate': float(1 - (published_samples / total_samples)) if total_samples else 0.0,
        'margin': rule['margin'],
        'lower_bound': max(0.0, selected_threshold - rule['margin']),
        'upper_bound': min(1.0, selected_threshold + rule['margin']),
    })
    return {
        **rule,
        'center': 'selected_walk_forward_threshold',
        'pooled_walk_forward': pooled_result,
        'folds': fold_results,
        'fold_stability': {
            'fold_count': len(fold_results),
            'empty_fold_count': sum(row['published_samples'] == 0 for row in fold_results),
            'mean_coverage': _optional_mean(row['coverage'] for row in fold_results),
            'coverage_standard_deviation': _optional_std(row['coverage'] for row in fold_results),
            'mean_balanced_accuracy': _optional_mean(
                row['balanced_accuracy'] for row in fold_results
            ),
            'balanced_accuracy_standard_deviation': _optional_std(
                row['balanced_accuracy'] for row in fold_results
            ),
            'mean_macro_f1': _optional_mean(row['macro_f1'] for row in fold_results),
            'macro_f1_standard_deviation': _optional_std(
                row['macro_f1'] for row in fold_results
            ),
            'mean_minimum_class_recall': _optional_mean(
                row['minimum_class_recall'] for row in fold_results
            ),
            'mean_baseline_improvement': _optional_mean(
                row['accuracy_improvement_over_majority_baseline']
                for row in fold_results
            ),
        },
    }


def evaluate_abstention_development(dataset):
    """Run all abstention rules on pre-Test purged Walk-Forward predictions."""
    if dataset.horizon != 1:
        raise ValueError('Abstention diagnostics require classification horizon = 1.')
    split = build_purged_chronological_split(dataset)
    folds = build_purged_walk_forward_folds(dataset, split)
    if split['gap_size'] != 1 or not folds:
        raise ValueError('A valid one-sample-purged Walk-Forward split is required.')
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
    records = _fit_selected_fold_probabilities(selected, folds)
    pooled_labels = tuple(
        label for record in records for label in record['labels']
    )
    pooled_probabilities = tuple(
        probability for record in records for probability in record['probabilities']
    )
    threshold = float(selected['threshold'])
    return {
        'scope': 'development_purged_walk_forward_only',
        'selected_model': selected['model'],
        'selected_params': selected.get('params'),
        'selected_threshold': threshold,
        'model_level_quality_gate': selected['quality_gate'],
        'candidate_models': evaluations,
        'probability_quality': probability_quality_diagnostics(
            pooled_labels, pooled_probabilities, threshold,
        ),
        'rules': [
            _rule_evaluation(rule, records, threshold)
            for rule in ABSTENTION_RULES
        ],
        'walk_forward_fold_count': len(folds),
        'walk_forward_chronological': True,
        'purge_gap': split['gap_size'],
        'all_fold_purges_safe': all(fold['purge_safe'] for fold in folds),
        'selected_model_refit_count_for_probability_diagnostics': len(folds),
        'predict_proba_count_for_all_abstention_rules': len(folds),
        'probability_arrays_reused_across_rules': True,
        'independent_test_accessed': False,
        'independent_test_used_for_selection': False,
        'split_boundaries': split['boundaries'],
    }


def _context_rule_summary(context, rule):
    pooled = rule['pooled_walk_forward']
    stability = rule['fold_stability']
    return {
        'symbol': context['symbol'],
        'lookback': context['lookback'],
        'coverage': pooled['coverage'],
        'balanced_accuracy': pooled['balanced_accuracy'],
        'macro_f1': pooled['macro_f1'],
        'minimum_class_recall': pooled['minimum_class_recall'],
        'roc_auc': pooled['roc_auc'],
        'baseline_improvement': pooled['accuracy_improvement_over_majority_baseline'],
        'macro_f1_std': stability['macro_f1_standard_deviation'],
        'folds': rule['folds'],
    }


def select_research_candidate_abstention_rule(development_results):
    """Select at most one rule from Development results; reject Test-bearing input."""
    if any(
        'independent_test' in result or result.get('independent_test_accessed') is True
        for result in development_results
    ):
        raise ValueError('Independent Test data cannot enter abstention-rule selection.')
    contexts = {(row['symbol'], row['lookback']) for row in development_results}
    if len(contexts) != len(development_results):
        raise ValueError('Development contexts must be unique.')
    rules = ABSTENTION_CANDIDATE_RULES
    evaluations = []
    for candidate_rule in ABSTENTION_RULES[1:]:
        comparisons = []
        for context in development_results:
            baseline = next(rule for rule in context['rules'] if rule['name'] == 'none')
            candidate = next(
                rule for rule in context['rules'] if rule['name'] == candidate_rule['name']
            )
            base = _context_rule_summary(context, baseline)
            current = _context_rule_summary(context, candidate)
            metric_keys = (
                'balanced_accuracy', 'macro_f1', 'minimum_class_recall',
                'baseline_improvement', 'macro_f1_std',
            )
            deltas = {
                key: (
                    float(current[key] - base[key])
                    if current[key] is not None and base[key] is not None
                    else None
                )
                for key in metric_keys
            }
            fold_comparisons = []
            for base_fold, current_fold in zip(base['folds'], current['folds']):
                improved = (
                    current_fold['balanced_accuracy'] is not None
                    and current_fold['macro_f1'] is not None
                    and current_fold['accuracy_improvement_over_majority_baseline'] is not None
                    and current_fold['balanced_accuracy'] > base_fold['balanced_accuracy']
                    and current_fold['macro_f1'] > base_fold['macro_f1']
                    and current_fold['accuracy_improvement_over_majority_baseline']
                    >= base_fold['accuracy_improvement_over_majority_baseline']
                )
                fold_comparisons.append({
                    'fold': base_fold['fold'],
                    'coverage': current_fold['coverage'],
                    'improved': improved,
                })
            fold_improved_ratio = float(
                sum(row['improved'] for row in fold_comparisons) / len(fold_comparisons)
            ) if fold_comparisons else 0.0
            harmed = (
                deltas['balanced_accuracy'] is None
                or deltas['macro_f1'] is None
                or deltas['balanced_accuracy']
                < -rules['maximum_context_balanced_accuracy_decline']
                or deltas['macro_f1'] < -rules['maximum_context_macro_f1_decline']
            )
            improved = (
                not harmed
                and deltas['balanced_accuracy'] is not None
                and deltas['macro_f1'] is not None
                and deltas['balanced_accuracy'] > 0
                and deltas['macro_f1'] > 0
                and deltas['baseline_improvement'] >= 0
                and fold_improved_ratio >= rules['minimum_improved_fold_ratio']
            )
            comparisons.append({
                'symbol': context['symbol'],
                'lookback': context['lookback'],
                'coverage': current['coverage'],
                'deltas': deltas,
                'fold_improved_ratio': fold_improved_ratio,
                'fold_comparisons': fold_comparisons,
                'context_improved': improved,
                'context_harmed': harmed,
            })
        delta_keys = (
            'balanced_accuracy', 'macro_f1', 'minimum_class_recall',
            'baseline_improvement', 'macro_f1_std',
        )
        mean_deltas = {
            key: _optional_mean(row['deltas'][key] for row in comparisons)
            for key in delta_keys
        }
        improved_symbols = {
            row['symbol'] for row in comparisons if row['context_improved']
        }
        improved_context_count = sum(row['context_improved'] for row in comparisons)
        harmed_context_count = sum(row['context_harmed'] for row in comparisons)
        average_coverage = float(mean(row['coverage'] for row in comparisons))
        average_fold_improved_ratio = float(mean(
            row['fold_improved_ratio'] for row in comparisons
        ))
        checks = {
            'coverage': average_coverage >= rules['minimum_average_development_coverage'],
            'multiple_contexts': (
                improved_context_count >= rules['minimum_improved_context_count']
            ),
            'multiple_symbols': len(improved_symbols) >= rules['minimum_improved_symbol_count'],
            'balanced_accuracy': (
                mean_deltas['balanced_accuracy'] is not None
                and mean_deltas['balanced_accuracy']
                >= rules['minimum_mean_balanced_accuracy_delta']
            ),
            'macro_f1': (
                mean_deltas['macro_f1'] is not None
                and mean_deltas['macro_f1'] >= rules['minimum_mean_macro_f1_delta']
            ),
            'minimum_class_recall': (
                mean_deltas['minimum_class_recall'] is not None
                and mean_deltas['minimum_class_recall']
                >= rules['minimum_mean_minimum_class_recall_delta']
            ),
            'baseline_improvement': (
                mean_deltas['baseline_improvement'] is not None
                and mean_deltas['baseline_improvement']
                >= rules['minimum_mean_baseline_improvement_delta']
            ),
            'fold_improvement': (
                average_fold_improved_ratio >= rules['minimum_improved_fold_ratio']
            ),
            'limited_harm': harmed_context_count <= rules['maximum_harmed_context_count'],
            'fold_stability': (
                mean_deltas['macro_f1_std'] is not None
                and mean_deltas['macro_f1_std']
                <= rules['maximum_macro_f1_std_increase']
            ),
        }
        score = float(
            0.30 * (mean_deltas['macro_f1'] or 0.0)
            + 0.25 * (mean_deltas['balanced_accuracy'] or 0.0)
            + 0.15 * (mean_deltas['minimum_class_recall'] or 0.0)
            + 0.15 * (mean_deltas['baseline_improvement'] or 0.0)
            + 0.10 * average_fold_improved_ratio
            + 0.05 * average_coverage
            - 0.05 * max(0.0, mean_deltas['macro_f1_std'] or 0.0)
        )
        evaluations.append({
            'rule': candidate_rule,
            'eligible': all(checks.values()),
            'checks': checks,
            'average_development_coverage': average_coverage,
            'average_fold_improved_ratio': average_fold_improved_ratio,
            'improved_context_count': int(improved_context_count),
            'improved_symbol_count': len(improved_symbols),
            'improved_symbols': sorted(improved_symbols),
            'harmed_context_count': int(harmed_context_count),
            'mean_deltas_vs_no_abstention': mean_deltas,
            'walk_forward_only_score': score,
            'contexts': comparisons,
        })
    eligible = [row for row in evaluations if row['eligible']]
    selected = max(
        eligible,
        key=lambda row: (
            row['walk_forward_only_score'],
            row['average_development_coverage'],
            -row['rule']['margin'],
        ),
    ) if eligible else None
    return {
        'research_candidate_abstention_rule': selected['rule'] if selected else None,
        'selected_candidate': selected,
        'candidates': evaluations,
        'selection_source': 'development_purged_walk_forward_only',
        'independent_test_used': False,
        'rules': rules,
    }


def evaluate_frozen_abstention_on_independent_test(dataset, development_result, candidate_rule):
    """Evaluate baseline and at most one frozen rule with one Test probability pass."""
    if development_result.get('independent_test_accessed') is not False:
        raise ValueError('Expected a development-only frozen evaluation.')
    if candidate_rule is not None and candidate_rule not in ABSTENTION_RULES[1:]:
        raise ValueError('Only a predeclared frozen abstention rule may enter Test.')
    split = build_purged_chronological_split(dataset)
    model = _model_factory(
        development_result['selected_model'],
        development_result.get('selected_params'),
    )()
    model.fit(
        dataset.features[:split['development_end']],
        dataset.classification_labels[:split['development_end']],
    )
    labels = tuple(split['y_classification_test'])
    probabilities = tuple(float(value) for value in model.predict_proba(split['x_test'])[
        :, list(model.classes_).index(1)
    ])
    baseline = evaluate_selective_predictions(
        labels, probabilities, development_result['selected_threshold'], 0.0,
    )
    baseline['quality_gate'] = evaluate_independent_test_quality_gate(baseline)
    candidate = None
    if candidate_rule is not None:
        candidate = evaluate_selective_predictions(
            labels,
            probabilities,
            development_result['selected_threshold'],
            candidate_rule['margin'],
        )
        candidate['name'] = candidate_rule['name']
        candidate['label'] = candidate_rule['label']
        candidate['quality_gate'] = evaluate_independent_test_quality_gate(candidate)
    return {
        'scope': 'final_untouched_independent_test',
        'frozen_model': development_result['selected_model'],
        'frozen_params': development_result.get('selected_params'),
        'frozen_threshold': development_result['selected_threshold'],
        'no_abstention': baseline,
        'frozen_research_candidate': candidate,
        'test_used_for_model_selection': False,
        'test_used_for_hyperparameter_tuning': False,
        'test_used_for_threshold_selection': False,
        'test_used_for_abstention_rule_selection': False,
        'model_refit_after_test': False,
        'test_predict_proba_count': 1,
        'test_evaluation_count_for_this_frozen_context': 1,
        'purge_gap': split['gap_size'],
        'validation_test_purge_safe': split['boundaries']['validation_test_purge_safe'],
    }
