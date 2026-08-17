from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from inspect import signature
from math import sin

from django.test import SimpleTestCase

from prediction.feature_service import build_prediction_feature_dataset
from prediction.ml_service import (
    PREDICTION_PIPELINE_VERSION,
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.regime_feature_diagnostics import (
    CLASSIFICATION_REGIME_FEATURE_SETS,
    REGRESSION_REGIME_FEATURE_SETS,
    TREND_REGIME_THRESHOLDS,
    VOLATILITY_REGIME_THRESHOLDS,
    build_regime_experiment_datasets,
    build_regime_feature_rows,
    chronological_target_shift_report,
    regime_shift_report,
    select_regime_feature_candidate,
    trailing_percentile,
    trailing_zscore,
    trend_regime,
    volatility_regime,
)
from prediction.services import PredictionBar


class RegimeFeatureDiagnosticTests(SimpleTestCase):
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

    def test_rolling_zscore_uses_only_current_and_past_values(self):
        original = [float(value) for value in range(1, 31)]
        changed_future = original[:]
        changed_future[20:] = [value * 100 for value in changed_future[20:]]

        self.assertEqual(
            trailing_zscore(original, 19, 20),
            trailing_zscore(changed_future, 19, 20),
        )

    def test_rolling_percentile_uses_only_current_and_past_values(self):
        original = [float(value) for value in range(1, 61)]
        changed_future = original + [10_000.0] * 20

        self.assertEqual(
            trailing_percentile(original, 59, 60),
            trailing_percentile(changed_future, 59, 60),
        )
        self.assertEqual(trailing_percentile(original, 59, 60), 1.0)

    def test_regime_thresholds_are_predeclared_and_accept_no_test_data(self):
        self.assertEqual(
            tuple(signature(volatility_regime).parameters),
            ('percentile',),
        )
        self.assertEqual(VOLATILITY_REGIME_THRESHOLDS['source'],
                         'predeclared_development_research_rule')
        self.assertEqual(TREND_REGIME_THRESHOLDS['source'],
                         'predeclared_development_research_rule')
        self.assertEqual(volatility_regime(0.20), 'LOW_VOL')
        self.assertEqual(volatility_regime(0.50), 'NORMAL_VOL')
        self.assertEqual(volatility_regime(0.90), 'HIGH_VOL')

    def test_regime_feature_at_t_is_unchanged_when_future_bar_changes(self):
        bars = self._bars()
        _, original_rows = build_regime_feature_rows(bars, horizon=1)
        changed = list(bars)
        future = changed[251]
        changed[251] = replace(
            future,
            open=future.open * 2,
            high=future.high * 2,
            low=future.low * 2,
            close=future.close * 2,
            volume=future.volume * 3,
        )
        _, changed_rows = build_regime_feature_rows(tuple(changed), horizon=1)

        self.assertEqual(original_rows[250], changed_rows[250])

    def test_classification_split_keeps_one_sample_purge(self):
        bundle = build_regime_experiment_datasets(
            self._bars(), 1, 'classification',
        )
        split = build_purged_chronological_split(bundle['datasets']['E'])

        self.assertEqual(split['gap_size'], 1)
        self.assertTrue(split['boundaries']['train_validation_purge_safe'])
        self.assertTrue(split['boundaries']['validation_test_purge_safe'])

    def test_regression_split_keeps_ten_sample_purge(self):
        bundle = build_regime_experiment_datasets(
            self._bars(), 10, 'regression',
        )
        split = build_purged_chronological_split(bundle['datasets']['E'])

        self.assertEqual(split['gap_size'], 10)
        self.assertTrue(split['boundaries']['train_validation_purge_safe'])
        self.assertTrue(split['boundaries']['validation_test_purge_safe'])

    def test_walk_forward_is_chronological_for_both_tasks(self):
        for task, horizon in (('classification', 1), ('regression', 10)):
            bundle = build_regime_experiment_datasets(self._bars(), horizon, task)
            dataset = bundle['datasets']['E']
            split = build_purged_chronological_split(dataset)
            folds = build_purged_walk_forward_folds(dataset, split)

            self.assertTrue(folds)
            self.assertTrue(all(fold['gap_size'] == horizon for fold in folds))
            self.assertTrue(all(fold['purge_safe'] for fold in folds))
            self.assertTrue(all(
                fold['boundaries']['train_last_label_endpoint_index']
                < fold['boundaries']['validation_first_feature_index']
                for fold in folds
            ))

    def test_independent_test_cannot_enter_feature_selection(self):
        with self.assertRaisesRegex(ValueError, 'Independent Test'):
            select_regime_feature_candidate([{
                'symbol': 'AAPL',
                'lookback': 504,
                'experiment': 'A',
                'independent_test': {'score': 1.0},
            }], 'classification')

    def test_production_classification_and_regression_targets_are_unchanged(self):
        bars = self._bars()
        classification = build_prediction_feature_dataset(bars, horizon=1)
        regression = build_prediction_feature_dataset(bars, horizon=10)
        class_index = classification.sample_indices[0]
        regression_index = regression.sample_indices[0]
        expected_class_return = float(
            bars[class_index + 1].close / bars[class_index].close - 1
        )
        expected_regression_return = float(
            bars[regression_index + 10].close / bars[regression_index].close - 1
        )

        self.assertEqual(
            classification.classification_labels[0],
            1 if expected_class_return > 0 else 0,
        )
        self.assertAlmostEqual(
            regression.regression_labels[0], expected_regression_return, places=12,
        )

    def test_research_build_does_not_mutate_production_quality_gate(self):
        thresholds = dict(PREDICTION_QUALITY_GATE_THRESHOLDS)

        build_regime_experiment_datasets(self._bars(), 1, 'classification')

        self.assertEqual(PREDICTION_QUALITY_GATE_THRESHOLDS, thresholds)

    def test_classification_and_regression_feature_sets_are_independent(self):
        self.assertNotEqual(
            CLASSIFICATION_REGIME_FEATURE_SETS['B'],
            REGRESSION_REGIME_FEATURE_SETS['B'],
        )
        self.assertIn('macd_histogram_change_z60',
                      CLASSIFICATION_REGIME_FEATURE_SETS['B'])
        self.assertNotIn('macd_histogram_change_z60',
                         REGRESSION_REGIME_FEATURE_SETS['B'])
        self.assertIn('momentum_60d_z60', REGRESSION_REGIME_FEATURE_SETS['B'])

    def test_all_ablation_datasets_share_identical_sample_rows(self):
        for task, horizon in (('classification', 1), ('regression', 10)):
            bundle = build_regime_experiment_datasets(self._bars(), horizon, task)
            sample_indices = {
                dataset.sample_indices for dataset in bundle['datasets'].values()
            }

            self.assertEqual(len(sample_indices), 1)
            self.assertEqual(
                {dataset.sample_count for dataset in bundle['datasets'].values()},
                {bundle['common_sample_count']},
            )

    def test_trend_regime_requires_multiple_confirming_signals(self):
        base = {
            'price_ma20_ratio': 0.01,
            'price_ma60_ratio': -0.01,
            'ma20_ma60_ratio': -0.01,
            'ma20_slope_5': -0.01,
            'ma60_slope_5': -0.01,
        }
        bull = {name: 0.01 for name in base}
        bear = {name: -0.01 for name in base}

        self.assertEqual(trend_regime(base), 'BEAR_TREND')
        self.assertEqual(trend_regime(bull), 'BULL_TREND')
        self.assertEqual(trend_regime(bear), 'BEAR_TREND')

    def test_development_drift_report_does_not_open_test(self):
        bars = self._bars()
        bundle = build_regime_experiment_datasets(bars, 1, 'classification')
        report = regime_shift_report(
            bars, bundle['datasets']['A'], bundle['rows'], include_test=False,
        )

        self.assertFalse(report['independent_test_accessed'])
        self.assertNotIn('independent_test', report['blocks'])
        self.assertEqual(report['purge_gap'], 1)

        target_report = chronological_target_shift_report(
            bars, bundle['datasets']['A'], include_test=False,
        )
        self.assertFalse(target_report['independent_test_accessed'])
        self.assertNotIn('independent_test', target_report['blocks'])

    def test_research_module_is_not_wired_into_production_prediction_service(self):
        import prediction.services as production_services

        self.assertFalse(hasattr(production_services, 'REGIME_EXPERIMENT_LABELS'))
        self.assertNotIn('regime', PREDICTION_PIPELINE_VERSION.lower())
