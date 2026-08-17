from datetime import date, timedelta
from decimal import Decimal
from math import sin

import numpy as np
from django.test import SimpleTestCase

from prediction.feature_service import build_prediction_feature_datasets
from prediction.ml_service import (
    PREDICTION_PIPELINE_VERSION,
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.model_architecture_diagnostics import (
    CLASSIFICATION_FAMILY_CONFIGS,
    REGRESSION_FAMILY_CONFIGS,
    _regression_training_target,
    evaluate_classifier_configuration,
    regression_target_diagnostics,
    select_cross_context_candidate,
    training_magnitude_sample_weights,
)
from prediction.services import PredictionBar


class ModelArchitectureDiagnosticTests(SimpleTestCase):
    def _bars(self, count=504):
        start = date(2024, 1, 1)
        bars, previous = [], 100.0
        for index in range(count):
            close = previous * (1 + 0.0003 + 0.009 * sin(index / 7))
            open_price = previous * (1 + 0.001 * sin(index / 5))
            bars.append(PredictionBar(
                date=start + timedelta(days=index),
                open=Decimal(str(open_price)),
                high=Decimal(str(max(open_price, close) * 1.01)),
                low=Decimal(str(min(open_price, close) * 0.99)),
                close=Decimal(str(close)),
                volume=1_000_000 + (index % 29) * 12_000,
            ))
            previous = close
        return tuple(bars)

    def test_model_inventory_contains_requested_families_and_real_production_candidates(self):
        self.assertEqual(set(CLASSIFICATION_FAMILY_CONFIGS), {
            'Current Logistic Regression', 'Current Random Forest',
            'Regularized Logistic Regression', 'Extra Trees Classifier',
            'Histogram Gradient Boosting Classifier',
        })
        regression_families = {row['family'] for row in REGRESSION_FAMILY_CONFIGS}
        self.assertTrue({'ridge', 'elastic_net', 'huber', 'random_forest',
                         'hist_gradient_boosting', 'extra_trees'} <= regression_families)

    def test_tasks_use_separate_horizons_and_safe_purges(self):
        datasets = build_prediction_feature_datasets(self._bars(), 1, 10)
        for task, expected_gap in (('classification', 1), ('regression', 10)):
            dataset = datasets[task]
            split = build_purged_chronological_split(dataset)
            folds = build_purged_walk_forward_folds(dataset, split)
            self.assertEqual(dataset.horizon, expected_gap)
            self.assertTrue(folds)
            self.assertTrue(all(fold['gap_size'] == expected_gap and fold['purge_safe'] for fold in folds))
            self.assertTrue(split['boundaries']['validation_test_purge_safe'])

    def test_volatility_scaled_target_uses_trailing_feature_at_t(self):
        dataset = build_prediction_feature_datasets(self._bars(), 1, 10)['regression']
        split = build_purged_chronological_split(dataset)
        fold = build_purged_walk_forward_folds(dataset, split)[0]
        y_fit, _, train_scale, validation_scale, metadata = _regression_training_target(
            fold, dataset, 'volatility_scaled_return',
        )
        index = dataset.regression_feature_names.index('volatility_20')
        self.assertTrue(np.allclose(train_scale, np.asarray(fold['x_regression_train'])[:, index]))
        self.assertTrue(np.allclose(validation_scale, np.asarray(fold['x_regression_validation'])[:, index]))
        self.assertTrue(np.allclose(y_fit * train_scale, fold['y_regression_train']))
        self.assertFalse(metadata['future_volatility_used'])

    def test_winsorization_thresholds_are_training_fold_only(self):
        dataset = build_prediction_feature_datasets(self._bars(), 1, 10)['regression']
        fold = build_purged_walk_forward_folds(
            dataset, build_purged_chronological_split(dataset),
        )[0]
        y_fit, y_validation, _, _, metadata = _regression_training_target(
            fold, dataset, 'winsorized_return',
        )
        expected = np.quantile(fold['y_regression_train'], (0.025, 0.975))
        self.assertEqual(metadata['threshold_source'], 'training_fold_only')
        self.assertAlmostEqual(metadata['lower'], expected[0])
        self.assertAlmostEqual(metadata['upper'], expected[1])
        self.assertEqual(tuple(y_validation), fold['y_regression_validation'])
        self.assertTrue(np.all(y_fit >= expected[0]) and np.all(y_fit <= expected[1]))

    def test_cost_sensitive_weights_are_bounded_and_training_only_function(self):
        weights = training_magnitude_sample_weights([-0.02, -0.001, 0.0, 0.003, 0.02])
        self.assertTrue(np.all(weights >= 1.0))
        self.assertTrue(np.all(weights <= 3.0))
        self.assertEqual(weights[2], 1.0)
        self.assertEqual(weights[0], 3.0)

    def test_candidate_selector_rejects_independent_test_payload(self):
        with self.assertRaisesRegex(ValueError, 'Independent Test'):
            select_cross_context_candidate([{
                'symbol': 'AAPL', 'lookback': 504, 'name': 'Production Baseline',
                'summary': {}, 'independent_test': {'score': 1.0},
            }], 'classification')

    def test_regression_target_diagnostics_are_development_only(self):
        dataset = build_prediction_feature_datasets(self._bars(), 1, 10)['regression']
        result = regression_target_diagnostics(dataset)
        self.assertEqual(result['scope'], 'development_only')
        self.assertFalse(result['independent_test_accessed'])
        self.assertIn('skewness', result)
        self.assertIn('excess_kurtosis', result)

    def test_one_logistic_evaluation_reports_train_and_validation_without_test(self):
        dataset = build_prediction_feature_datasets(self._bars(), 1, 10)['classification']
        params = CLASSIFICATION_FAMILY_CONFIGS['Current Logistic Regression'][0]
        thresholds = dict(PREDICTION_QUALITY_GATE_THRESHOLDS)
        result = evaluate_classifier_configuration(
            dataset, 'Current Logistic Regression', params,
        )
        self.assertIn('balanced_accuracy', result['train'])
        self.assertIn('mean_balanced_accuracy', result['validation'])
        self.assertTrue(all(fold['purge_safe'] for fold in result['folds']))
        self.assertFalse(result['independent_test_accessed'])
        self.assertEqual(PREDICTION_QUALITY_GATE_THRESHOLDS, thresholds)

    def test_research_module_is_not_wired_into_production(self):
        import prediction.services as production_services
        self.assertFalse(hasattr(production_services, 'CLASSIFICATION_FAMILY_CONFIGS'))
        self.assertNotIn('architecture', PREDICTION_PIPELINE_VERSION.lower())
