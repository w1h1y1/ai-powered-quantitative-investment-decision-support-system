from datetime import date, timedelta
from decimal import Decimal
from math import isfinite, sin
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security, SecurityDailyPrice
from prediction.artifact_cache import build_prediction_artifact_cache_key
from prediction.feature_service import build_prediction_feature_dataset
from prediction.ml_service import (
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    RANDOM_FOREST_CLASSIFIER_PARAM_GRID,
    REGRESSION_MODEL_CANDIDATES,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
    calculate_predicted_price,
    evaluate_classification_quality_gate,
    evaluate_final_classification_quality_gate,
    evaluate_independent_test_quality_gate,
    evaluate_final_regression_quality_gate,
    evaluate_regression_independent_test_quality_gate,
    evaluate_regression_quality_gate,
    majority_class_baseline_accuracy,
    select_validation_threshold,
    tune_random_forest_classifier,
    tune_regression_models,
    _regression_model,
)
from prediction.services import PredictionBar, _load_prediction_bars, _prediction_start_date


class PredictionArtifactCacheTests(SimpleTestCase):
    def test_cache_key_contains_every_artifact_invalidation_dimension(self):
        base = build_prediction_artifact_cache_key(
            'aapl',
            1,
            10,
            504,
            date(2026, 8, 10),
            'pipeline-v1',
        )

        self.assertEqual(
            base,
            'prediction:AAPL:classification-1:regression-10:504:2026-08-10:pipeline-v1',
        )
        horizon_keys = {
            build_prediction_artifact_cache_key(
                'AAPL', classification_horizon, regression_horizon,
                504, date(2026, 8, 10), 'pipeline-v1',
            )
            for classification_horizon in (1, 5)
            for regression_horizon in (5, 10, 20)
        }
        self.assertEqual(len(horizon_keys), 6)
        variants = (
            build_prediction_artifact_cache_key('MSFT', 1, 10, 504, date(2026, 8, 10), 'pipeline-v1'),
            build_prediction_artifact_cache_key('AAPL', 5, 10, 504, date(2026, 8, 10), 'pipeline-v1'),
            build_prediction_artifact_cache_key('AAPL', 1, 20, 504, date(2026, 8, 10), 'pipeline-v1'),
            build_prediction_artifact_cache_key('AAPL', 1, 10, 756, date(2026, 8, 10), 'pipeline-v1'),
            build_prediction_artifact_cache_key('AAPL', 1, 10, 504, date(2026, 8, 11), 'pipeline-v1'),
            build_prediction_artifact_cache_key('AAPL', 1, 10, 504, date(2026, 8, 10), 'pipeline-v2'),
        )
        self.assertTrue(all(key != base for key in variants))


class PredictionQualityGateTests(SimpleTestCase):
    def _folds(self):
        return (
            {
                'fold': 1,
                'y_classification_train': (0, 1) * 50 + (1,),
                'y_classification_validation': (0, 0, 1, 1) * 7,
            },
            {
                'fold': 2,
                'y_classification_train': (0, 1) * 60 + (1,),
                'y_classification_validation': (0, 0, 1, 1) * 7,
            },
        )

    def _metrics(self, **overrides):
        metrics = {
            'actual_up_count': 28,
            'actual_down_count': 28,
            'predicted_up_count': 28,
            'predicted_down_count': 28,
            'balanced_accuracy': 0.62,
            'macro_f1': 0.61,
            'accuracy': 0.62,
            'fold_metrics': (
                {
                    'fold': 1,
                    'actual_up_count': 14,
                    'actual_down_count': 14,
                    'predicted_up_count': 14,
                    'predicted_down_count': 14,
                },
                {
                    'fold': 2,
                    'actual_up_count': 14,
                    'actual_down_count': 14,
                    'predicted_up_count': 14,
                    'predicted_down_count': 14,
                },
            ),
        }
        metrics.update(overrides)
        return metrics

    def test_rejects_all_down_walk_forward_predictions(self):
        fold_metrics = tuple({
            **fold,
            'predicted_up_count': 0,
            'predicted_down_count': 28,
        } for fold in self._metrics()['fold_metrics'])

        result = evaluate_classification_quality_gate(
            self._metrics(
                predicted_up_count=0,
                predicted_down_count=56,
                balanced_accuracy=0.5,
                macro_f1=1 / 3,
                accuracy=0.5,
                fold_metrics=fold_metrics,
            ),
            self._folds(),
        )

        self.assertFalse(result['passed'])
        self.assertIn('single_class_predictions', result['reason_codes'])

    def test_rejects_balanced_accuracy_of_exactly_point_five(self):
        result = evaluate_classification_quality_gate(
            self._metrics(balanced_accuracy=0.5),
            self._folds(),
        )

        self.assertFalse(result['passed'])
        self.assertIn('balanced_accuracy_below_minimum', result['reason_codes'])
        self.assertEqual(
            result['thresholds']['minimum_balanced_accuracy'],
            PREDICTION_QUALITY_GATE_THRESHOLDS['minimum_balanced_accuracy'],
        )

    def test_qualified_walk_forward_model_passes(self):
        result = evaluate_classification_quality_gate(self._metrics(), self._folds())

        self.assertTrue(result['passed'], result)
        self.assertEqual(result['reason_codes'], [])
        self.assertGreater(
            result['observed']['accuracy_improvement_over_baseline'],
            result['thresholds']['minimum_accuracy_improvement_over_baseline'],
        )

    def test_regression_must_beat_zero_return_baseline(self):
        failed = evaluate_regression_quality_gate({
            'sample_count': 50,
            'model_metrics': {'mae': 0.021, 'rmse': 0.031, 'r2': -0.2},
            'zero_return_baseline': {'name': 'zero_future_return', 'mae': 0.020, 'rmse': 0.030, 'r2': -0.1},
        })
        passed = evaluate_regression_quality_gate({
            'sample_count': 50,
            'model_metrics': {'mae': 0.015, 'rmse': 0.020, 'r2': 0.1},
            'zero_return_baseline': {'name': 'zero_future_return', 'mae': 0.020, 'rmse': 0.030, 'r2': -0.1},
        })

        self.assertFalse(failed['passed'])
        self.assertTrue(passed['passed'])

    def _independent_test_metrics(self, **overrides):
        metrics = {
            'actual_up_count': 33,
            'actual_down_count': 32,
            'predicted_up_count': 32,
            'predicted_down_count': 33,
            'accuracy': 0.63,
            'balanced_accuracy': 0.63,
            'macro_f1': 0.62,
            'minimum_class_recall': 0.58,
        }
        metrics.update(overrides)
        return metrics

    def test_independent_test_rejects_amzn_like_almost_all_down_predictions(self):
        result = evaluate_independent_test_quality_gate(self._independent_test_metrics(
            predicted_up_count=1,
            predicted_down_count=64,
            accuracy=0.5077,
            balanced_accuracy=0.5152,
            macro_f1=0.3627,
            minimum_class_recall=0.0303,
        ))

        self.assertFalse(result['passed'])
        self.assertIn('prediction_distribution_extreme_skew', result['reason_codes'])
        self.assertIn('minimum_class_recall_below_minimum', result['reason_codes'])
        self.assertIn('did_not_beat_majority_baseline', result['reason_codes'])

    def test_independent_test_rejects_balanced_accuracy_or_macro_f1_below_minimum(self):
        low_balanced_accuracy = evaluate_independent_test_quality_gate(
            self._independent_test_metrics(balanced_accuracy=0.5),
        )
        low_macro_f1 = evaluate_independent_test_quality_gate(
            self._independent_test_metrics(macro_f1=0.40),
        )

        self.assertIn('balanced_accuracy_below_minimum', low_balanced_accuracy['reason_codes'])
        self.assertIn('macro_f1_below_minimum', low_macro_f1['reason_codes'])

    def test_independent_test_rejects_low_minority_class_recall(self):
        result = evaluate_independent_test_quality_gate(
            self._independent_test_metrics(minimum_class_recall=0.10),
        )

        self.assertFalse(result['passed'])
        self.assertIn('minimum_class_recall_below_minimum', result['reason_codes'])

    def test_distribution_skew_guard_is_not_a_fixed_prediction_ratio(self):
        result = evaluate_independent_test_quality_gate(self._independent_test_metrics(
            actual_up_count=59,
            actual_down_count=6,
            predicted_up_count=64,
            predicted_down_count=1,
            accuracy=0.94,
            balanced_accuracy=0.58,
            macro_f1=0.52,
            minimum_class_recall=0.25,
        ))

        self.assertFalse(result['observed']['distribution_check_applied'])
        self.assertNotIn('prediction_distribution_extreme_skew', result['reason_codes'])

    def test_two_stage_classification_gate_requires_both_stages(self):
        walk_forward_gate = {'passed': True, 'reason_codes': [], 'reasons': []}
        failed_test_gate = {
            'passed': False,
            'reason_codes': ['minimum_class_recall_below_minimum'],
            'reasons': ['Minimum class recall is too low.'],
        }
        passed_test_gate = {'passed': True, 'reason_codes': [], 'reasons': []}

        failed = evaluate_final_classification_quality_gate(
            walk_forward_gate,
            failed_test_gate,
        )
        passed = evaluate_final_classification_quality_gate(
            walk_forward_gate,
            passed_test_gate,
        )

        self.assertFalse(failed['passed'])
        self.assertEqual(failed['failed_stages'], ['independent_test'])
        self.assertIn(
            'independent_test:minimum_class_recall_below_minimum',
            failed['reason_codes'],
        )
        self.assertTrue(passed['passed'])


class PredictionRegressionPipelineTests(SimpleTestCase):
    def _walk_forward_evaluation(self, **overrides):
        evaluation = {
            'sample_count': 100,
            'model_metrics': {'mae': 0.015, 'rmse': 0.020, 'r2': 0.10},
            'zero_return_baseline': {
                'name': 'zero_future_return',
                'mae': 0.020,
                'rmse': 0.030,
                'r2': -0.10,
            },
            'improving_fold_count': 3,
            'improving_fold_ratio': 0.60,
            'folds': [
                {'fold': index + 1, 'beats_zero_on_mae_and_rmse': index < 3}
                for index in range(5)
            ],
            'prediction_diagnostics': {
                'actual': {'std': 0.03},
                'predicted': {'std': 0.02},
                'prediction_to_actual_std_ratio': 2 / 3,
                'maximum_absolute_prediction': 0.08,
            },
        }
        evaluation.update(overrides)
        return evaluation

    def _test_evaluation(self, **overrides):
        evaluation = {
            'sample_count': 40,
            'model_metrics': {'mae': 0.015, 'rmse': 0.020, 'r2': 0.05},
            'zero_return_baseline': {
                'name': 'zero_future_return',
                'mae': 0.020,
                'rmse': 0.030,
                'r2': -0.05,
            },
            'prediction_diagnostics': {
                'actual': {'std': 0.03},
                'predicted': {'std': 0.02},
                'prediction_to_actual_std_ratio': 2 / 3,
                'maximum_absolute_prediction': 0.08,
            },
        }
        evaluation.update(overrides)
        return evaluation

    def test_walk_forward_gate_rejects_improvement_confined_to_one_fold(self):
        result = evaluate_regression_quality_gate(self._walk_forward_evaluation(
            improving_fold_count=1,
            improving_fold_ratio=0.20,
        ))

        self.assertFalse(result['passed'])
        self.assertIn('insufficient_improving_folds', result['reason_codes'])

    def test_walk_forward_gate_rejects_effectively_constant_predictions(self):
        evaluation = self._walk_forward_evaluation()
        evaluation['prediction_diagnostics'] = {
            **evaluation['prediction_diagnostics'],
            'predicted': {'std': 0.0},
        }

        result = evaluate_regression_quality_gate(evaluation)

        self.assertFalse(result['passed'])
        self.assertIn('effectively_constant_predictions', result['reason_codes'])

    def test_independent_test_gate_rejects_model_below_zero_return_baseline(self):
        result = evaluate_regression_independent_test_quality_gate(self._test_evaluation(
            model_metrics={'mae': 0.021, 'rmse': 0.031, 'r2': -0.20},
        ))

        self.assertFalse(result['passed'])
        self.assertIn('mae_did_not_beat_zero_return_baseline', result['reason_codes'])
        self.assertIn('rmse_did_not_beat_zero_return_baseline', result['reason_codes'])
        self.assertEqual(result['role'], 'publication_only')

    def test_independent_test_gate_rejects_extreme_prediction_amplitude(self):
        evaluation = self._test_evaluation()
        evaluation['prediction_diagnostics'] = {
            **evaluation['prediction_diagnostics'],
            'maximum_absolute_prediction': 0.75,
        }

        result = evaluate_regression_independent_test_quality_gate(evaluation)

        self.assertFalse(result['passed'])
        self.assertIn('predicted_return_extreme', result['reason_codes'])

    def test_final_regression_gate_requires_both_stages(self):
        passed_stage = {'passed': True, 'reason_codes': [], 'reasons': []}
        failed_stage = {
            'passed': False,
            'reason_codes': ['mae_did_not_beat_zero_return_baseline'],
            'reasons': ['MAE did not beat zero return.'],
        }

        failed = evaluate_final_regression_quality_gate(passed_stage, failed_stage)
        passed = evaluate_final_regression_quality_gate(passed_stage, passed_stage)

        self.assertFalse(failed['passed'])
        self.assertEqual(failed['failed_stages'], ['independent_test'])
        self.assertTrue(passed['passed'])

    def test_predicted_price_uses_simple_return_for_positive_negative_and_zero(self):
        cases = ((0.10, 110.0), (-0.10, 90.0), (0.0, 100.0))
        for expected_return, expected_price in cases:
            with self.subTest(expected_return=expected_return):
                self.assertAlmostEqual(
                    calculate_predicted_price(100.0, expected_return),
                    expected_price,
                )

    def test_predicted_price_is_null_when_input_is_unavailable(self):
        self.assertIsNone(calculate_predicted_price(None, 0.1))
        self.assertIsNone(calculate_predicted_price(100, None))

    def test_scaled_regressor_learns_scaler_only_from_training_rows(self):
        candidate = {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 1.0}}
        training = ((1.0, 10.0), (2.0, 20.0), (3.0, 30.0))
        model = _regression_model(candidate)

        model.fit(training, (0.01, 0.02, 0.03))

        self.assertEqual(tuple(model.named_steps['scaler'].mean_), (2.0, 20.0))
        self.assertNotEqual(tuple(model.named_steps['scaler'].mean_), (26.5, 265.0))

    def test_walk_forward_regression_tuning_is_deterministic_and_has_no_test_input(self):
        candidates = (
            {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 0.1}},
            {'model': 'Ridge Regression', 'family': 'ridge', 'params': {'alpha': 10.0}},
        )
        folds = tuple({
            'fold': fold,
            'x_regression_train': tuple((float(i), float(i % 3)) for i in range(1, 21 + fold)),
            'y_regression_train': tuple(0.001 * i for i in range(1, 21 + fold)),
            'x_regression_validation': tuple((float(i), float(i % 3)) for i in range(22 + fold, 27 + fold)),
            'y_regression_validation': tuple(0.001 * i for i in range(22 + fold, 27 + fold)),
            'training_samples': 20 + fold,
            'validation_samples': 5,
            'gap_size': 5,
            'purge_safe': True,
        } for fold in (1, 2))
        self.assertTrue(all('x_test' not in fold for fold in folds))

        with patch('prediction.ml_service.REGRESSION_MODEL_CANDIDATES', candidates):
            first = tune_regression_models(folds)
            second = tune_regression_models(folds)

        self.assertEqual(first['selected']['model'], second['selected']['model'])
        self.assertEqual(first['selected']['params'], second['selected']['params'])
        self.assertEqual(
            first['selected']['model_metrics'],
            second['selected']['model_metrics'],
        )
        self.assertEqual(first['selection_source'], 'purged_walk_forward_validation')


class PredictionGenerateApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='prediction-user', password='test-password')
        self.security = Security.objects.create(
            symbol='TEST',
            name='Test Security',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        self.end_date = date(2026, 2, 20)
        self.start_date = self.end_date - timedelta(days=520)
        current = self.start_date
        row = 0
        while current <= self.end_date:
            if current.weekday() < 5:
                price = (
                    Decimal('100')
                    + Decimal(row) * Decimal('0.03')
                    + Decimal(str(sin(row / 4) * 4))
                ).quantize(Decimal('0.000001'))
                SecurityDailyPrice.objects.create(
                    security=self.security,
                    date=current,
                    open=price - Decimal('0.3'),
                    high=price + Decimal('1.0'),
                    low=price - Decimal('1.0'),
                    close=price,
                    volume=1_000_000 + row * 1_000,
                )
                row += 1
            current += timedelta(days=1)
        self.client.force_authenticate(self.user)

    def _post_horizon_validation_request(self, payload):
        with patch(
            'prediction.views.generate_prediction_market_data',
            return_value={'validation_probe': True},
        ) as generator:
            response = self.client.post(
                '/api/predictions/generate/',
                {'symbol': self.security.symbol, 'lookback': 504, **payload},
                format='json',
            )
        return response, generator

    def test_prediction_horizon_defaults_are_one_and_ten(self):
        response, generator = self._post_horizon_validation_request({})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(generator.call_args.kwargs['classification_forecast_horizon'], 1)
        self.assertEqual(generator.call_args.kwargs['regression_forecast_horizon'], 10)

    def test_all_six_prediction_horizon_combinations_reach_the_service(self):
        for classification_horizon in (1, 5):
            for regression_horizon in (5, 10, 20):
                with self.subTest(
                    classification_horizon=classification_horizon,
                    regression_horizon=regression_horizon,
                ):
                    response, generator = self._post_horizon_validation_request({
                        'classification_forecast_horizon': classification_horizon,
                        'regression_forecast_horizon': regression_horizon,
                    })
                    self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                    self.assertEqual(
                        generator.call_args.kwargs['classification_forecast_horizon'],
                        classification_horizon,
                    )
                    self.assertEqual(
                        generator.call_args.kwargs['regression_forecast_horizon'],
                        regression_horizon,
                    )

    def test_invalid_prediction_horizons_return_400_without_running_prediction(self):
        invalid_inputs = (
            ('classification_forecast_horizon', 10),
            ('classification_forecast_horizon', 0),
            ('classification_forecast_horizon', 'abc'),
            ('regression_forecast_horizon', 1),
            ('regression_forecast_horizon', 0),
            ('regression_forecast_horizon', 'abc'),
        )
        for field, value in invalid_inputs:
            with self.subTest(field=field, value=value):
                response, generator = self._post_horizon_validation_request({field: value})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)
                generator.assert_not_called()

    def test_new_horizons_take_priority_over_legacy_compatibility_input(self):
        for legacy_field in ('horizon', 'forecast_horizon'):
            with self.subTest(legacy_field=legacy_field):
                response, generator = self._post_horizon_validation_request({
                    legacy_field: 5,
                    'classification_forecast_horizon': 1,
                    'regression_forecast_horizon': 10,
                })
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                self.assertEqual(generator.call_args.kwargs['classification_forecast_horizon'], 1)
                self.assertEqual(generator.call_args.kwargs['regression_forecast_horizon'], 10)

        legacy_response, legacy_generator = self._post_horizon_validation_request({'horizon': 5})
        self.assertEqual(legacy_response.status_code, status.HTTP_200_OK, legacy_response.data)
        self.assertEqual(legacy_generator.call_args.kwargs['classification_forecast_horizon'], 5)
        self.assertEqual(legacy_generator.call_args.kwargs['regression_forecast_horizon'], 5)

        invalid_response, invalid_generator = self._post_horizon_validation_request({'horizon': 10})
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('horizon', invalid_response.data)
        invalid_generator.assert_not_called()

    @patch('prediction.services.get_latest_complete_market_date')
    def test_returns_real_historical_prices_and_technical_indicators(self, latest_market_date):
        latest_market_date.return_value = self.end_date

        response = self.client.post('/api/predictions/generate/', {
            'symbol': self.security.symbol,
            'classification_forecast_horizon': 5,
            'regression_forecast_horizon': 5,
            'lookback': 60,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['ml_cache']['hit'])
        self.assertEqual(response.data['ml_cache']['key_date'], self.end_date.isoformat())
        self.assertEqual(
            response.data['ml_cache']['pipeline_version'],
            response.data['ml_metadata']['ml_cache']['pipeline_version'],
        )
        self.assertEqual(response.data['symbol'], 'TEST')
        latest_close = float(SecurityDailyPrice.objects.filter(security=self.security).latest('date').close)
        self.assertEqual(response.data['current_price'], latest_close)
        self.assertEqual(response.data['latest_market_date'], self.end_date.isoformat())
        self.assertEqual(response.data['historical_data_count'], 60)
        self.assertEqual(len(response.data['historical_data']), 60)
        self.assertEqual(response.data['historical_data'][-1]['close'], latest_close)
        self.assertIsNotNone(response.data['technical_indicators']['ma5'])
        self.assertIsNotNone(response.data['technical_indicators']['ma60'])
        self.assertIsNotNone(response.data['technical_indicators']['rsi'])
        self.assertIsNotNone(response.data['technical_indicators']['macd'])
        self.assertIsNotNone(response.data['technical_indicators']['macd_signal'])
        self.assertIsNotNone(response.data['technical_indicators']['atr'])
        self.assertIsNotNone(response.data['technical_indicators']['recent_return'])
        self.assertIsNotNone(response.data['technical_indicators']['volatility'])
        self.assertEqual(response.data['prediction']['status'], 'insufficient_data')
        self.assertFalse(response.data['prediction_available'])
        self.assertIsNone(response.data['predicted_price'])
        self.assertIsNone(response.data['confidence'])

    @patch('prediction.services.get_latest_complete_market_date')
    def test_accepts_thirty_day_lookback_without_inventing_long_window_indicators(self, latest_market_date):
        latest_market_date.return_value = self.end_date

        response = self.client.post('/api/predictions/generate/', {
            'symbol': self.security.symbol,
            'classification_forecast_horizon': 5,
            'regression_forecast_horizon': 5,
            'lookback': 30,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['lookback'], 30)
        self.assertEqual(response.data['historical_data_count'], 30)
        self.assertEqual(len(response.data['historical_data']), 30)
        self.assertFalse(response.data['prediction_available'])
        self.assertIn('Insufficient historical data', response.data['prediction_unavailable_reason'])
        self.assertIsNotNone(response.data['technical_indicators']['ma5'])
        self.assertIsNotNone(response.data['technical_indicators']['ma10'])
        self.assertIsNotNone(response.data['technical_indicators']['ma20'])
        self.assertIsNone(response.data['technical_indicators']['ma60'])
        self.assertIsNone(response.data['technical_indicators']['macd_signal'])
        self.assertEqual(response.data['technical_indicators']['volume_trend']['direction'], 'unavailable')
        self.assertIsNone(response.data['technical_indicators']['volume_trend']['percent_change'])

    @patch('prediction.services.get_latest_complete_market_date')
    def test_walk_forward_pass_and_independent_test_failure_withholds_forecast_but_preserves_diagnostics(self, latest_market_date):
        latest_market_date.return_value = self.end_date
        walk_forward_gate = {
            'passed': True,
            'source': 'purged_walk_forward_validation',
            'reason_codes': [],
            'reasons': [],
        }
        independent_test_gate = {
            'passed': False,
            'source': 'independent_test_publication_gate',
            'role': 'publication_only',
            'reason_codes': [
                'minimum_class_recall_below_minimum',
                'prediction_distribution_extreme_skew',
            ],
            'reasons': [
                'Independent Test minimum class recall 0.030 is below the 0.200 minimum.',
                'Independent Test predicted class distribution is extremely skewed.',
            ],
        }
        final_gate = evaluate_final_classification_quality_gate(
            walk_forward_gate,
            independent_test_gate,
        )
        quality_gate = {
            'passed': False,
            'source': 'two_stage_classification_and_walk_forward_regression',
            'classification': final_gate,
            'walk_forward_classification': walk_forward_gate,
            'independent_test_classification': independent_test_gate,
            'regression': {'passed': True, 'source': 'purged_walk_forward_validation'},
        }
        artifact = {
            'prediction_available': False,
            'prediction_unavailable_reason': (
                'The selected model passed Walk-Forward Validation but failed the independent '
                'Test publication gate because minimum class recall was too low.'
            ),
            'predicted_direction': None,
            'probability_increase': None,
            'expected_return': 0.02,
            'predicted_price': 102.0,
            'confidence': None,
            'selected_model': None,
            'selected_threshold': None,
            'selected_candidate_model': 'Logistic Regression',
            'selected_candidate_threshold': 0.42,
            'regression_prediction_available': True,
            'regression_prediction_unavailable_reason': None,
            'regression_model': 'Random Forest Regressor',
            'prediction_quality_gate': quality_gate,
            'walk_forward_quality_gate': walk_forward_gate,
            'independent_test_quality_gate': independent_test_gate,
            'final_classification_quality_gate': final_gate,
            'ml_reliability': {'level': 'Low'},
            'model_metrics': {
                'balanced_accuracy': 0.5152,
                'macro_f1': 0.3627,
                'minimum_class_recall': 0.0303,
                'independent_test_quality_gate': independent_test_gate,
                'walk_forward_folds': [{'fold': 1, 'purge_safe': True}],
            },
            'model_comparison': [{
                'model': 'Logistic Regression',
                'selected': True,
                'predicted_direction': 'DOWN',
                'walk_forward_quality_gate': walk_forward_gate,
            }],
            'confidence_details': None,
            'ml_metadata': {'walk_forward_folds': [{'fold': 1, 'purge_safe': True}]},
        }

        with patch(
            'prediction.services.generate_machine_learning_prediction',
            return_value=artifact,
        ):
            response = self.client.post('/api/predictions/generate/', {
                'symbol': self.security.symbol,
                'classification_forecast_horizon': 5,
                'regression_forecast_horizon': 5,
                'lookback': 60,
            }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['prediction_available'])
        self.assertEqual(response.data['prediction']['status'], 'quality_gate_failed')
        for field in (
            'predicted_direction',
            'probability_increase',
            'confidence',
            'selected_model',
            'selected_threshold',
        ):
            self.assertIsNone(response.data[field])
        self.assertTrue(response.data['regression_prediction_available'])
        self.assertEqual(response.data['expected_return'], 0.02)
        self.assertEqual(response.data['predicted_price'], 102.0)
        self.assertEqual(response.data['model_metrics'], artifact['model_metrics'])
        self.assertEqual(response.data['model_comparison'], artifact['model_comparison'])
        self.assertEqual(response.data['prediction_quality_gate'], quality_gate)
        self.assertTrue(response.data['walk_forward_quality_gate']['passed'])
        self.assertFalse(response.data['independent_test_quality_gate']['passed'])
        self.assertEqual(
            response.data['final_classification_quality_gate']['failed_stages'],
            ['independent_test'],
        )
        self.assertEqual(response.data['selected_candidate_model'], 'Logistic Regression')
        self.assertEqual(response.data['ml_metadata']['walk_forward_folds'][0]['fold'], 1)

    @patch('prediction.services.get_latest_complete_market_date')
    def test_generates_real_machine_learning_prediction_for_sufficient_history(self, latest_market_date):
        latest_market_date.return_value = self.end_date

        with patch(
            'prediction.ml_service.select_validation_threshold',
            wraps=select_validation_threshold,
        ) as threshold_selector, patch(
            'prediction.ml_service.tune_random_forest_classifier',
            wraps=tune_random_forest_classifier,
        ) as random_forest_tuner, patch(
            'prediction.ml_service.evaluate_independent_test_quality_gate',
            wraps=evaluate_independent_test_quality_gate,
        ) as independent_test_gate:
            response = self.client.post('/api/predictions/generate/', {
                'symbol': self.security.symbol,
                'classification_forecast_horizon': 5,
                'regression_forecast_horizon': 5,
                'lookback': 252,
            }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['ml_cache']['hit'])
        self.assertEqual(response.data['ml_cache']['key_date'], self.end_date.isoformat())
        self.assertEqual(
            response.data['ml_cache']['pipeline_version'],
            response.data['ml_metadata']['ml_cache']['pipeline_version'],
        )
        self.assertTrue(response.data['prediction_available'], response.data)
        self.assertEqual(response.data['prediction']['status'], 'available')
        self.assertTrue(response.data['prediction_quality_gate']['classification']['passed'])
        self.assertTrue(response.data['walk_forward_quality_gate']['passed'])
        self.assertTrue(response.data['independent_test_quality_gate']['passed'])
        self.assertTrue(response.data['final_classification_quality_gate']['passed'])
        self.assertTrue(response.data['prediction_quality_gate']['regression']['passed'])
        self.assertEqual(
            response.data['prediction_quality_gate']['source'],
            'two_stage_classification_and_two_stage_regression',
        )
        self.assertIn(response.data['predicted_direction'], {'UP', 'DOWN'})
        self.assertGreaterEqual(response.data['probability_increase'], 0)
        self.assertLessEqual(response.data['probability_increase'], 1)
        self.assertTrue(isfinite(response.data['expected_return']))
        self.assertTrue(isfinite(response.data['predicted_price']))
        self.assertAlmostEqual(
            response.data['predicted_price'],
            response.data['current_price'] * (1 + response.data['expected_return']),
        )
        self.assertIn(response.data['confidence'], {'High', 'Medium', 'Low'})
        self.assertIn(response.data['selected_model'], {'Logistic Regression', 'Random Forest Classifier'})
        self.assertIn(
            response.data['regression_model'],
            {candidate['model'] for candidate in REGRESSION_MODEL_CANDIDATES},
        )
        self.assertEqual(len(response.data['model_comparison']), 2)
        walk_forward_fold_count = response.data['ml_metadata']['walk_forward_fold_count']
        self.assertEqual(walk_forward_fold_count, 2)
        self.assertEqual(
            threshold_selector.call_count,
            (len(RANDOM_FOREST_CLASSIFIER_PARAM_GRID) + 1) * walk_forward_fold_count,
        )
        self.assertTrue(all(
            len(call.args[0]) == 25
            and len(call.args[1]) == 25
            for call in threshold_selector.call_args_list
        ))
        self.assertEqual(random_forest_tuner.call_count, 1)
        self.assertEqual(independent_test_gate.call_count, 1)
        self.assertIsInstance(independent_test_gate.call_args.args[0], dict)
        self.assertNotIn('features', independent_test_gate.call_args.args[0])
        self.assertNotIn('model', independent_test_gate.call_args.args[0])
        tuner_call = random_forest_tuner.call_args
        tuning_folds = tuner_call.args[0]
        self.assertEqual(len(tuning_folds), walk_forward_fold_count)
        self.assertEqual(
            [fold['training_samples'] for fold in tuning_folds],
            [100, 125],
        )
        self.assertTrue(all(
            fold['validation_samples'] == 25
            and fold['gap_size'] == 5
            and fold['purge_safe']
            for fold in tuning_folds
        ))
        self.assertTrue(all(
            model['metric_source'] == 'purged_walk_forward_validation'
            for model in response.data['model_comparison']
        ))
        self.assertTrue(all(
            model['threshold_source'] == 'purged_walk_forward_validation'
            and 0 <= model['threshold'] <= 1
            for model in response.data['model_comparison']
        ))
        selected_comparison = next(
            model for model in response.data['model_comparison'] if model['selected']
        )
        self.assertTrue(selected_comparison['threshold_eligible'])
        self.assertFalse(selected_comparison['degenerate_threshold'])
        for model in response.data['model_comparison']:
            for metric in (
                'macro_f1',
                'balanced_accuracy',
                'up_recall',
                'down_recall',
                'specificity',
                'minimum_class_recall',
                'actual_up_count',
                'actual_down_count',
                'predicted_up_count',
                'predicted_down_count',
                'mean_macro_f1',
                'std_macro_f1',
                'mean_balanced_accuracy',
                'mean_roc_auc',
                'worst_fold_minimum_class_recall',
            ):
                self.assertIn(metric, model)
            self.assertEqual(len(model['walk_forward_folds']), walk_forward_fold_count)
            self.assertIn(model['threshold_stability']['status'], {
                'stable', 'moderate', 'unstable', 'insufficient_folds',
            })
        self.assertEqual(response.data['selected_threshold'], selected_comparison['threshold'])
        self.assertEqual(
            response.data['predicted_direction'],
            'UP'
            if response.data['probability_increase'] > response.data['selected_threshold']
            else 'DOWN',
        )
        self.assertEqual(response.data['model_metrics']['metric_source'], 'independent_test')
        self.assertEqual(
            response.data['model_metrics']['threshold_source'],
            'purged_walk_forward_validation',
        )
        self.assertEqual(response.data['model_metrics']['threshold'], response.data['selected_threshold'])
        self.assertGreaterEqual(response.data['model_metrics']['majority_class_baseline_accuracy'], 0.5)
        for metric in ('accuracy', 'precision', 'recall', 'f1'):
            self.assertGreaterEqual(response.data['model_metrics'][metric], 0)
            self.assertLessEqual(response.data['model_metrics'][metric], 1)
        regression = response.data['model_metrics']['regression']
        self.assertEqual(regression['metric_source'], 'independent_test')
        self.assertEqual(
            regression['quality_gate']['source'],
            'walk_forward_and_independent_test',
        )
        self.assertGreaterEqual(
            regression['walk_forward_quality_metrics']['sample_count'],
            PREDICTION_QUALITY_GATE_THRESHOLDS['minimum_oos_samples'],
        )
        self.assertGreaterEqual(regression['mae'], 0)
        self.assertGreaterEqual(regression['rmse'], 0)
        self.assertTrue(isfinite(regression['r2']))
        self.assertEqual(response.data['model_metrics']['training_samples'], 155)
        self.assertEqual(response.data['model_metrics']['validation_samples'], 50)
        self.assertGreaterEqual(response.data['model_metrics']['test_samples'], 20)
        self.assertEqual(response.data['model_metrics']['gap_size'], 5)
        self.assertEqual(response.data['confidence_details']['performance_source'], 'independent_test')
        metadata = response.data['ml_metadata']
        self.assertEqual(metadata['hyperparameter_source'], 'purged_walk_forward_validation')
        self.assertEqual(metadata['random_forest_candidate_count'], len(RANDOM_FOREST_CLASSIFIER_PARAM_GRID))
        self.assertEqual(metadata['random_forest_params']['random_state'], 42)
        self.assertEqual(metadata['random_forest_params']['n_jobs'], 1)
        self.assertEqual(metadata['random_forest_parallel_strategy'], 'candidate_fold_threads')
        self.assertGreaterEqual(metadata['random_forest_parallel_workers'], 1)
        self.assertFalse(metadata['random_forest_nested_parallelism'])
        self.assertIn(
            {
                key: metadata['random_forest_params'][key]
                for key in (
                    'n_estimators',
                    'max_depth',
                    'min_samples_split',
                    'min_samples_leaf',
                    'max_features',
                )
            },
            RANDOM_FOREST_CLASSIFIER_PARAM_GRID,
        )
        self.assertEqual(metadata['first_gap_samples'], 5)
        self.assertEqual(metadata['second_gap_samples'], 5)
        self.assertTrue(metadata['boundaries']['train_validation_purge_safe'])
        self.assertTrue(metadata['boundaries']['validation_test_purge_safe'])
        self.assertTrue(metadata['final_test_untouched'])
        self.assertEqual(
            metadata['independent_test_role'],
            'final_evaluation_and_publication_gate_only',
        )
        self.assertFalse(metadata['independent_test_used_for_model_selection'])
        self.assertFalse(metadata['independent_test_used_for_hyperparameter_tuning'])
        self.assertFalse(metadata['independent_test_used_for_threshold_selection'])
        self.assertFalse(metadata['classifier_refit_after_independent_test'])
        self.assertFalse(metadata['walk_forward_shuffle'])
        self.assertEqual(metadata['fold_scaler_fit_scope'], 'fold_training_only')
        self.assertEqual(len(metadata['walk_forward_folds']), walk_forward_fold_count)
        self.assertTrue(all(fold['purge_safe'] for fold in metadata['walk_forward_folds']))
        self.assertIn(response.data['ml_reliability']['level'], {'Low', 'Limited', 'Stable'})

        with patch(
            'prediction.services.generate_machine_learning_prediction',
            side_effect=AssertionError('Cache hit must not execute ML fitting.'),
        ):
            repeated_response = self.client.post('/api/predictions/generate/', {
                'symbol': self.security.symbol,
                'classification_forecast_horizon': 5,
                'regression_forecast_horizon': 5,
                'lookback': 252,
            }, format='json')
        self.assertEqual(repeated_response.status_code, status.HTTP_200_OK, repeated_response.data)
        self.assertTrue(repeated_response.data['ml_cache']['hit'])
        self.assertEqual(repeated_response.data['selected_model'], response.data['selected_model'])
        self.assertEqual(repeated_response.data['selected_threshold'], response.data['selected_threshold'])
        self.assertEqual(repeated_response.data['model_comparison'], response.data['model_comparison'])
        self.assertEqual(
            repeated_response.data['ml_metadata']['random_forest_params'],
            metadata['random_forest_params'],
        )

    @patch('prediction.services.get_latest_complete_market_date')
    def test_failed_regression_test_gate_clears_formal_fields_but_keeps_diagnostics(
        self,
        latest_market_date,
    ):
        latest_market_date.return_value = self.end_date
        failed_test_gate = {
            'passed': False,
            'source': 'independent_test_publication_gate',
            'role': 'publication_only',
            'reason_codes': ['mae_did_not_beat_zero_return_baseline'],
            'reasons': ['Independent Test regression MAE did not beat zero return.'],
            'thresholds': {},
            'observed': {},
            'baseline': {},
        }

        with patch(
            'prediction.ml_service.evaluate_regression_independent_test_quality_gate',
            return_value=failed_test_gate,
        ):
            response = self.client.post('/api/predictions/generate/', {
                'symbol': self.security.symbol,
                'classification_forecast_horizon': 5,
                'regression_forecast_horizon': 5,
                'lookback': 252,
            }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['regression_prediction_available'])
        self.assertIsNone(response.data['expected_return'])
        self.assertIsNone(response.data['predicted_price'])
        self.assertIsNone(response.data['regression_model'])
        self.assertIsNotNone(response.data['selected_regression_candidate_model'])
        self.assertIn('Independent Test', response.data['regression_prediction_unavailable_reason'])
        self.assertFalse(response.data['regression_independent_test_quality_gate']['passed'])
        self.assertFalse(response.data['final_regression_quality_gate']['passed'])
        regression = response.data['model_metrics']['regression']
        self.assertTrue(regression['candidate_models'])
        self.assertTrue(regression['walk_forward_quality_metrics']['folds'])
        self.assertEqual(
            regression['independent_test_quality_gate'],
            failed_test_gate,
        )
        self.assertFalse(
            response.data['ml_metadata']['independent_test_used_for_regression_model_selection']
        )
        self.assertFalse(
            response.data['ml_metadata']['independent_test_used_for_regression_hyperparameter_tuning']
        )
        self.assertFalse(response.data['ml_metadata']['regressor_refit_after_independent_test'])

    def test_rejects_lookback_shorter_than_thirty_trading_days(self):
        response = self.client.post('/api/predictions/generate/', {
            'symbol': self.security.symbol,
            'classification_forecast_horizon': 5,
            'regression_forecast_horizon': 5,
            'lookback': 29,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('lookback', response.data)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/predictions/generate/', {
            'symbol': self.security.symbol,
            'classification_forecast_horizon': 5,
            'regression_forecast_horizon': 5,
            'lookback': 60,
        }, format='json')
        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})


class PredictionHistoricalLookbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.security = Security.objects.create(
            symbol='LONG',
            name='Long History Security',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        prices = []
        current = date(2021, 1, 4)
        row = 0
        while row < 1260:
            if current.weekday() < 5:
                close = Decimal('100') + Decimal(row) * Decimal('0.01')
                prices.append(SecurityDailyPrice(
                    security=cls.security,
                    date=current,
                    open=close - Decimal('0.1'),
                    high=close + Decimal('0.5'),
                    low=close - Decimal('0.5'),
                    close=close,
                    volume=1_000_000 + row,
                ))
                row += 1
            current += timedelta(days=1)
        SecurityDailyPrice.objects.bulk_create(prices)
        cls.end_date = prices[-1].date

    @patch('prediction.services.fetch_and_cache_daily_prices')
    @patch('prediction.services.cache_has_requested_coverage', return_value=True)
    @patch('prediction.services.get_latest_complete_market_date')
    def test_two_three_and_five_year_lookbacks_load_distinct_exact_bar_counts(
        self,
        latest_market_date,
        _coverage,
        fetch_prices,
    ):
        latest_market_date.return_value = self.end_date
        requested_starts = []

        for lookback in (504, 756, 1260):
            with self.subTest(lookback=lookback):
                bars, metadata = _load_prediction_bars(self.security, lookback)
                self.assertEqual(len(bars), lookback)
                self.assertEqual(bars[-1].date, self.end_date)
                self.assertEqual(metadata['source'], 'database_cache')
                requested_starts.append(metadata['requested_start_date'])

        self.assertLess(requested_starts[2], requested_starts[1])
        self.assertLess(requested_starts[1], requested_starts[0])
        fetch_prices.assert_not_called()

    def test_five_year_start_date_is_older_than_two_and_three_year_windows(self):
        starts = {
            lookback: _prediction_start_date(self.end_date, lookback)
            for lookback in (504, 756, 1260)
        }

        self.assertLess(starts[1260], starts[756])
        self.assertLess(starts[756], starts[504])


class PredictionFeatureServiceTests(SimpleTestCase):
    def _bars(self, count=90):
        start = date(2025, 1, 1)
        return tuple(
            PredictionBar(
                date=start + timedelta(days=index),
                open=Decimal(100 + index),
                high=Decimal(101 + index),
                low=Decimal(99 + index),
                close=Decimal(100 + index),
                volume=1_000_000 + index * 1_000,
            )
            for index in range(count)
        )

    def test_labels_use_only_future_close_at_the_selected_horizon(self):
        bars = self._bars()
        horizon = 5

        dataset = build_prediction_feature_dataset(bars, horizon)

        first_index = dataset.sample_indices[0]
        expected_return = float((bars[first_index + horizon].close / bars[first_index].close) - 1)
        self.assertEqual(first_index, 59)
        self.assertAlmostEqual(dataset.regression_labels[0], expected_return)
        self.assertEqual(dataset.classification_labels[0], 1)
        self.assertEqual(dataset.sample_indices, tuple(sorted(dataset.sample_indices)))
        self.assertEqual(dataset.sample_indices[-1], len(bars) - horizon - 1)

    def test_future_price_changes_labels_without_changing_earlier_features(self):
        bars = self._bars()
        horizon = 5
        original = build_prediction_feature_dataset(bars, horizon)
        first_index = original.sample_indices[0]
        future_index = first_index + horizon
        changed_bars = list(bars)
        future_bar = changed_bars[future_index]
        changed_bars[future_index] = PredictionBar(
            date=future_bar.date,
            open=future_bar.open,
            high=future_bar.high * 2,
            low=future_bar.low,
            close=future_bar.close * 2,
            volume=future_bar.volume,
        )

        changed = build_prediction_feature_dataset(tuple(changed_bars), horizon)

        self.assertEqual(original.features[0], changed.features[0])
        self.assertEqual(original.regression_features[0], changed.regression_features[0])
        self.assertNotEqual(original.regression_labels[0], changed.regression_labels[0])

    def test_regression_features_and_labels_are_aligned_and_unlabeled_tail_is_removed(self):
        bars = self._bars(100)
        horizon = 10

        dataset = build_prediction_feature_dataset(bars, horizon)

        self.assertEqual(len(dataset.regression_features), len(dataset.regression_labels))
        self.assertEqual(len(dataset.regression_features), len(dataset.sample_indices))
        self.assertEqual(dataset.sample_indices[-1], len(bars) - horizon - 1)
        self.assertIsNotNone(dataset.latest_regression_features)
        self.assertEqual(
            len(dataset.latest_regression_features),
            len(dataset.regression_feature_names),
        )

    def test_feature_builder_rejects_non_chronological_market_bars(self):
        bars = list(self._bars(90))
        bars[70], bars[71] = bars[71], bars[70]

        with self.assertRaisesRegex(ValueError, 'ascending market date'):
            build_prediction_feature_dataset(tuple(bars), horizon=5)

    def test_chronological_split_purges_horizon_at_both_boundaries(self):
        horizon = 5
        dataset = build_prediction_feature_dataset(self._bars(252), horizon)

        split = build_purged_chronological_split(dataset)

        self.assertEqual(split['training_samples'], 124)
        self.assertEqual(split['validation_samples'], 26)
        self.assertEqual(split['test_samples'], 28)
        self.assertEqual(split['first_gap_samples'], horizon)
        self.assertEqual(split['second_gap_samples'], horizon)
        self.assertEqual(split['purged_samples'], horizon * 2)
        boundaries = split['boundaries']
        self.assertLess(
            boundaries['train_last_label_endpoint_index'],
            boundaries['validation_first_feature_index'],
        )
        self.assertLess(
            boundaries['validation_last_label_endpoint_index'],
            boundaries['test_first_feature_index'],
        )

    def test_split_counts_reflect_warmup_labels_and_two_purge_gaps(self):
        cases = (
            (126, 5, (36, 7, 9)),
            (252, 5, (124, 26, 28)),
            (252, 20, (93, 19, 21)),
            (504, 5, (301, 64, 65)),
            (504, 20, (269, 57, 59)),
        )
        for lookback, horizon, expected_counts in cases:
            with self.subTest(lookback=lookback, horizon=horizon):
                dataset = build_prediction_feature_dataset(self._bars(lookback), horizon)
                split = build_purged_chronological_split(dataset)
                self.assertEqual(
                    (
                        split['training_samples'],
                        split['validation_samples'],
                        split['test_samples'],
                    ),
                    expected_counts,
                )

    def test_walk_forward_fold_counts_and_sizes_follow_lookback_capacity(self):
        cases = (
            (252, 2, [100, 125], 25),
            (504, 5, [165, 205, 245, 285, 325], 40),
            (756, 7, [229, 279, 329, 379, 429, 479, 529], 50),
        )
        for lookback, expected_fold_count, expected_training, expected_validation in cases:
            with self.subTest(lookback=lookback):
                dataset = build_prediction_feature_dataset(self._bars(lookback), horizon=5)
                split = build_purged_chronological_split(dataset)

                folds = build_purged_walk_forward_folds(dataset, split)

                self.assertEqual(len(folds), expected_fold_count)
                self.assertEqual(
                    [fold['training_samples'] for fold in folds],
                    expected_training,
                )
                self.assertTrue(all(
                    fold['validation_samples'] == expected_validation
                    and fold['gap_size'] == 5
                    and fold['purge_safe']
                    for fold in folds
                ))

    def test_walk_forward_folds_never_include_independent_test_rows(self):
        dataset = build_prediction_feature_dataset(self._bars(504), horizon=5)
        split = build_purged_chronological_split(dataset)

        folds = build_purged_walk_forward_folds(dataset, split)

        self.assertTrue(all(
            fold['boundaries']['validation_last_feature_index']
            < split['boundaries']['test_first_feature_index']
            for fold in folds
        ))
        self.assertTrue(all(
            fold['boundaries']['train_last_label_endpoint_index']
            < fold['boundaries']['validation_first_feature_index']
            for fold in folds
        ))

    def test_default_horizons_gain_samples_without_changing_purge_or_test_isolation(self):
        expected = {
            504: {
                1: (444, 309, 66, 67, 5, [175, 215, 255, 295, 335]),
                10: (435, 290, 62, 63, 5, [152, 192, 232, 272, 312]),
            },
            756: {
                1: (696, 485, 104, 105, 7, [239, 289, 339, 389, 439, 489, 539]),
                10: (687, 466, 100, 101, 7, [216, 266, 316, 366, 416, 466, 516]),
            },
            1260: {
                1: (1200, 838, 179, 181, 7, [667, 717, 767, 817, 867, 917, 967]),
                10: (1191, 819, 175, 177, 7, [644, 694, 744, 794, 844, 894, 944]),
            },
        }

        for lookback, horizons in expected.items():
            for horizon, counts in horizons.items():
                with self.subTest(lookback=lookback, horizon=horizon):
                    dataset = build_prediction_feature_dataset(self._bars(lookback), horizon)
                    split = build_purged_chronological_split(dataset)
                    folds = build_purged_walk_forward_folds(dataset, split)
                    self.assertEqual(
                        (
                            dataset.sample_count,
                            split['training_samples'],
                            split['validation_samples'],
                            split['test_samples'],
                            len(folds),
                            [fold['training_samples'] for fold in folds],
                        ),
                        counts,
                    )
                    self.assertEqual(split['first_gap_samples'], horizon)
                    self.assertEqual(split['second_gap_samples'], horizon)
                    self.assertTrue(split['boundaries']['train_validation_purge_safe'])
                    self.assertTrue(split['boundaries']['validation_test_purge_safe'])
                    self.assertTrue(all(fold['gap_size'] == horizon for fold in folds))
                    self.assertTrue(all(fold['purge_safe'] for fold in folds))
                    self.assertTrue(all(
                        fold['boundaries']['validation_last_feature_index']
                        < split['boundaries']['test_first_feature_index']
                        for fold in folds
                    ))

    def test_threshold_search_maximizes_validation_macro_f1(self):
        result = select_validation_threshold(
            labels=(0, 0, 1, 1),
            probabilities=(0.10, 0.40, 0.45, 0.90),
        )

        self.assertAlmostEqual(result['threshold'], 0.425)
        self.assertEqual(result['metrics']['f1'], 1.0)
        self.assertEqual(result['metrics']['macro_f1'], 1.0)
        self.assertEqual(result['metrics']['balanced_accuracy'], 1.0)
        self.assertTrue(result['threshold_eligible'])

    def test_threshold_search_rejects_higher_positive_f1_all_up_solution(self):
        result = select_validation_threshold(
            labels=(1, 1, 1, 1, 1, 1, 1, 1, 0, 0),
            probabilities=(0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.45, 0.35),
        )

        self.assertTrue(result['threshold_eligible'])
        self.assertFalse(result['metrics']['degenerate_threshold'])
        self.assertGreater(result['metrics']['up_recall'], 0)
        self.assertGreater(result['metrics']['down_recall'], 0)
        self.assertGreater(result['metrics']['predicted_up_count'], 0)
        self.assertGreater(result['metrics']['predicted_down_count'], 0)

    def test_threshold_search_marks_result_ineligible_when_no_non_degenerate_threshold_exists(self):
        result = select_validation_threshold(
            labels=(0, 0, 1, 1),
            probabilities=(0.40, 0.40, 0.40, 0.40),
        )

        self.assertFalse(result['threshold_eligible'])
        self.assertTrue(result['metrics']['degenerate_threshold'])
        self.assertEqual(result['metrics']['minimum_class_recall'], 0)

    def test_majority_class_baseline_uses_independent_evaluation_labels(self):
        labels = (1,) * 20 + (0,) * 8

        self.assertAlmostEqual(majority_class_baseline_accuracy(labels), 20 / 28)
