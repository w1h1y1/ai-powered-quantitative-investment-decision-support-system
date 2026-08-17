from datetime import date, timedelta
from decimal import Decimal
from inspect import signature
from math import sin
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from prediction.confidence_abstention_diagnostics import (
    ABSTENTION_RULES,
    apply_abstention,
    evaluate_frozen_abstention_on_independent_test,
    evaluate_selective_predictions,
    probability_quality_diagnostics,
    select_research_candidate_abstention_rule,
)
from prediction.feature_service import (
    FEATURE_NAMES,
    REGRESSION_FEATURE_NAMES,
    PredictionFeatureDataset,
    build_prediction_feature_dataset,
)
from prediction.ml_service import (
    PREDICTION_PIPELINE_VERSION,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.services import PredictionBar


class ConfidenceAbstentionDiagnosticTests(SimpleTestCase):
    def _bars(self, count=504):
        start = date(2024, 1, 1)
        bars = []
        previous = 100.0
        for index in range(count):
            close = previous * (1 + 0.0004 + 0.009 * sin(index / 6))
            open_price = previous * (1 + 0.001 * sin(index / 4))
            bars.append(PredictionBar(
                date=start + timedelta(days=index),
                open=Decimal(str(open_price)),
                high=Decimal(str(max(open_price, close) * 1.01)),
                low=Decimal(str(min(open_price, close) * 0.99)),
                close=Decimal(str(close)),
                volume=1_000_000 + (index % 31) * 10_000,
            ))
            previous = close
        return tuple(bars)

    def _simple_dataset(self, count=200):
        labels = tuple(index % 2 for index in range(count))
        return PredictionFeatureDataset(
            horizon=1,
            feature_names=('feature',),
            features=tuple((float(index % 4),) for index in range(count)),
            classification_labels=labels,
            regression_labels=tuple((index % 7 - 3) / 1000 for index in range(count)),
            regression_feature_names=('regression_feature',),
            regression_features=tuple((float(index % 5),) for index in range(count)),
            sample_indices=tuple(range(60, 60 + count)),
            latest_features=(1.0,),
            latest_regression_features=(1.0,),
            discarded_labeled_rows=60,
        )

    def test_abstention_does_not_change_production_one_day_target(self):
        bars = self._bars()
        dataset = build_prediction_feature_dataset(bars, horizon=1)
        first_index = dataset.sample_indices[0]
        expected_return = float(
            bars[first_index + 1].close / bars[first_index].close - 1
        )

        evaluate_selective_predictions((0, 1), (0.2, 0.8), 0.5, 0.1)

        self.assertAlmostEqual(dataset.regression_labels[0], expected_return, places=12)
        self.assertEqual(
            dataset.classification_labels[0],
            1 if expected_return > 0 else 0,
        )
        self.assertEqual(dataset.sample_indices[-1], len(bars) - 2)

    def test_abstention_does_not_change_regression_pipeline_contract(self):
        dataset = build_prediction_feature_dataset(self._bars(), horizon=1)
        regression_snapshot = (
            dataset.regression_feature_names,
            dataset.regression_features,
            dataset.regression_labels,
            dataset.latest_regression_features,
        )

        evaluate_selective_predictions((0, 1), (0.2, 0.8), 0.5, 0.1)

        self.assertEqual(dataset.feature_names, FEATURE_NAMES)
        self.assertEqual(dataset.regression_feature_names, REGRESSION_FEATURE_NAMES)
        self.assertEqual(
            regression_snapshot,
            (
                dataset.regression_feature_names,
                dataset.regression_features,
                dataset.regression_labels,
                dataset.latest_regression_features,
            ),
        )

    def test_abstention_rule_uses_only_probability_threshold_and_margin(self):
        self.assertEqual(
            tuple(signature(apply_abstention).parameters),
            ('probabilities', 'selected_threshold', 'margin'),
        )
        decision = apply_abstention((0.40, 0.60, 0.80), 0.60, 0.10)

        self.assertEqual(decision['lower_bound'], 0.50)
        self.assertEqual(decision['upper_bound'], 0.70)
        self.assertEqual(decision['positions'], (0, 2))
        self.assertEqual(decision['predictions'], (0, 1))

    def test_coverage_counts_are_correct(self):
        result = evaluate_selective_predictions(
            (0, 1, 0, 1),
            (0.10, 0.90, 0.49, 0.51),
            0.50,
            0.10,
        )

        self.assertEqual(result['total_samples'], 4)
        self.assertEqual(result['published_samples'], 2)
        self.assertEqual(result['abstained_samples'], 2)
        self.assertEqual(result['coverage'], 0.5)
        self.assertEqual(result['abstention_rate'], 0.5)

    def test_no_abstention_preserves_production_strict_threshold_rule(self):
        decision = apply_abstention((0.49, 0.50, 0.51), 0.50, 0.0)

        self.assertEqual(decision['positions'], (0, 1, 2))
        self.assertEqual(decision['predictions'], (0, 0, 1))

    def test_abstained_rows_are_excluded_not_counted_as_errors(self):
        result = evaluate_selective_predictions(
            (0, 1, 1),
            (0.10, 0.90, 0.49),
            0.50,
            0.10,
        )

        self.assertEqual(result['published_samples'], 2)
        self.assertEqual(result['accuracy'], 1.0)
        self.assertEqual(result['actual_up_count'], 1)
        self.assertEqual(result['actual_down_count'], 1)

    def test_published_subset_balanced_accuracy_and_macro_f1_are_correct(self):
        result = evaluate_selective_predictions(
            (0, 1, 0, 1),
            (0.10, 0.90, 0.80, 0.20),
            0.50,
            0.0,
        )

        self.assertEqual(result['balanced_accuracy'], 0.5)
        self.assertEqual(result['macro_f1'], 0.5)
        self.assertEqual(result['minimum_class_recall'], 0.5)

    def test_fold_with_no_published_predictions_is_safe(self):
        result = evaluate_selective_predictions(
            (0, 1),
            (0.49, 0.51),
            0.50,
            0.10,
        )

        self.assertEqual(result['published_samples'], 0)
        self.assertEqual(result['coverage'], 0.0)
        self.assertIsNone(result['accuracy'])
        self.assertIsNone(result['balanced_accuracy'])
        self.assertIsNone(result['macro_f1'])
        self.assertIsNone(result['majority_baseline_accuracy'])

    def test_walk_forward_remains_chronological_with_one_sample_purge(self):
        dataset = build_prediction_feature_dataset(self._bars(), horizon=1)
        split = build_purged_chronological_split(dataset)
        folds = build_purged_walk_forward_folds(dataset, split)

        self.assertEqual(split['gap_size'], 1)
        self.assertTrue(folds)
        self.assertTrue(all(fold['gap_size'] == 1 for fold in folds))
        self.assertTrue(all(fold['purge_safe'] for fold in folds))
        self.assertTrue(all(
            fold['boundaries']['train_last_label_endpoint_index']
            < fold['boundaries']['validation_first_feature_index']
            for fold in folds
        ))

    def test_candidate_selector_rejects_test_data(self):
        with self.assertRaisesRegex(ValueError, 'Independent Test'):
            select_research_candidate_abstention_rule([{
                'symbol': 'AAPL',
                'lookback': 504,
                'independent_test': {'balanced_accuracy': 1.0},
            }])

    def test_probability_quality_reports_raw_uncalibrated_scores(self):
        diagnostics = probability_quality_diagnostics(
            (0, 1), (0.10, 0.90), 0.50,
        )

        self.assertAlmostEqual(diagnostics['brier_score'], 0.01)
        self.assertAlmostEqual(diagnostics['log_loss'], -np.log(0.9))
        self.assertEqual(diagnostics['roc_auc'], 1.0)
        self.assertAlmostEqual(diagnostics['expected_calibration_error'], 0.1)
        self.assertEqual(diagnostics['calibration_method'], 'none')
        self.assertFalse(diagnostics['probabilities_are_calibrated'])
        self.assertEqual(
            sum(row['sample_count'] for row in diagnostics['calibration_bins']),
            2,
        )

    def test_independent_test_is_used_once_after_rule_is_frozen(self):
        dataset = self._simple_dataset()
        calls = {'fit': 0, 'predict_proba': 0}

        class FakeModel:
            classes_ = np.asarray((0, 1))

            def fit(self, features, labels):
                calls['fit'] += 1
                return self

            def predict_proba(self, features):
                calls['predict_proba'] += 1
                probabilities = np.asarray([
                    0.25 if int(row[0]) % 2 == 0 else 0.75
                    for row in features
                ])
                return np.column_stack((1 - probabilities, probabilities))

        development = {
            'selected_model': 'Logistic Regression',
            'selected_params': None,
            'selected_threshold': 0.5,
            'independent_test_accessed': False,
        }
        with patch(
            'prediction.confidence_abstention_diagnostics._model_factory',
            return_value=lambda: FakeModel(),
        ):
            result = evaluate_frozen_abstention_on_independent_test(
                dataset,
                development,
                ABSTENTION_RULES[1],
            )

        self.assertEqual(calls, {'fit': 1, 'predict_proba': 1})
        self.assertEqual(result['test_predict_proba_count'], 1)
        self.assertFalse(result['test_used_for_model_selection'])
        self.assertFalse(result['test_used_for_hyperparameter_tuning'])
        self.assertFalse(result['test_used_for_threshold_selection'])
        self.assertFalse(result['test_used_for_abstention_rule_selection'])
        self.assertFalse(result['model_refit_after_test'])

    def test_abstention_rules_are_research_only_and_production_version_is_unchanged(self):
        import prediction.services as production_services

        self.assertFalse(hasattr(production_services, 'ABSTENTION_RULES'))
        self.assertNotIn('abstention', PREDICTION_PIPELINE_VERSION.lower())
        self.assertEqual(len(ABSTENTION_RULES), 4)
