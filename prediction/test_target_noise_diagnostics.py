from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from math import sin

from django.test import SimpleTestCase

from prediction.feature_service import (
    FEATURE_NAMES,
    PredictionFeatureDataset,
    build_prediction_feature_dataset,
)
from prediction.ml_service import (
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.services import PredictionBar
from prediction.target_noise_diagnostics import (
    _filtered_partition,
    _filtered_walk_forward_folds,
    select_research_candidate_noise_band,
)


class ClassificationTargetNoiseDiagnosticTests(SimpleTestCase):
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

    def _boundary_dataset(self):
        returns = (-0.006, -0.005, -0.0025, -0.001, 0.0, 0.001, 0.003)
        return PredictionFeatureDataset(
            horizon=1,
            feature_names=('feature',),
            features=tuple((float(index),) for index in range(len(returns))),
            classification_labels=tuple(1 if value > 0 else 0 for value in returns),
            regression_labels=returns,
            regression_feature_names=('regression_feature',),
            regression_features=tuple((float(index),) for index in range(len(returns))),
            sample_indices=tuple(range(len(returns))),
            latest_features=(1.0,),
            latest_regression_features=(1.0,),
            discarded_labeled_rows=0,
        )

    def test_production_one_day_target_uses_exact_next_close_alignment(self):
        bars = self._bars()
        dataset = build_prediction_feature_dataset(bars, horizon=1)
        first_index = dataset.sample_indices[0]
        expected = float(bars[first_index + 1].close / bars[first_index].close - 1)

        self.assertAlmostEqual(dataset.regression_labels[0], expected, places=12)
        self.assertEqual(dataset.classification_labels[0], 1 if expected > 0 else 0)
        self.assertEqual(dataset.sample_indices[-1], len(bars) - 2)

    def test_zero_band_preserves_the_production_target_and_full_coverage(self):
        dataset = self._boundary_dataset()

        filtered = _filtered_partition(dataset, 0, dataset.sample_count, 0.0)

        self.assertEqual(filtered['retained_sample_count'], dataset.sample_count)
        self.assertEqual(filtered['coverage_ratio'], 1.0)
        self.assertEqual(filtered['labels'], dataset.classification_labels)

    def test_point_one_percent_band_excludes_boundaries_and_inside_rows(self):
        dataset = self._boundary_dataset()

        filtered = _filtered_partition(dataset, 0, dataset.sample_count, 0.001)

        self.assertEqual(filtered['returns'], (-0.006, -0.005, -0.0025, 0.003))
        self.assertEqual(filtered['excluded_sample_count'], 3)

    def test_point_two_five_percent_band_excludes_boundaries_and_inside_rows(self):
        dataset = self._boundary_dataset()

        filtered = _filtered_partition(dataset, 0, dataset.sample_count, 0.0025)

        self.assertEqual(filtered['returns'], (-0.006, -0.005, 0.003))
        self.assertEqual(filtered['excluded_sample_count'], 4)

    def test_point_five_percent_band_excludes_boundaries_and_inside_rows(self):
        dataset = self._boundary_dataset()

        filtered = _filtered_partition(dataset, 0, dataset.sample_count, 0.005)

        self.assertEqual(filtered['returns'], (-0.006,))
        self.assertEqual(filtered['excluded_sample_count'], 6)

    def test_noise_filter_does_not_change_point_in_time_features(self):
        bars = self._bars()
        original = build_prediction_feature_dataset(bars, horizon=1)
        feature_index = original.sample_indices[20]
        future_index = feature_index + 1
        changed_bars = list(bars)
        future = changed_bars[future_index]
        changed_bars[future_index] = replace(
            future,
            close=future.close * 2,
            high=future.high * 2,
            volume=future.volume * 2,
        )

        changed = build_prediction_feature_dataset(tuple(changed_bars), horizon=1)
        changed_position = changed.sample_indices.index(feature_index)

        self.assertEqual(original.features[20], changed.features[changed_position])
        self.assertNotEqual(
            original.regression_labels[20], changed.regression_labels[changed_position],
        )

    def test_filtered_walk_forward_remains_chronological_with_one_sample_purge(self):
        dataset = build_prediction_feature_dataset(self._bars(), horizon=1)
        split = build_purged_chronological_split(dataset)
        base_folds = build_purged_walk_forward_folds(dataset, split)

        filtered_folds = _filtered_walk_forward_folds(dataset, split, 0.0025)

        self.assertEqual(split['gap_size'], 1)
        self.assertEqual(len(filtered_folds), len(base_folds))
        self.assertTrue(all(fold['purge_safe'] for fold in filtered_folds))
        self.assertTrue(all(
            fold['boundaries']['train_last_label_endpoint_index']
            < fold['boundaries']['validation_first_feature_index']
            for fold in filtered_folds
        ))
        self.assertTrue(all(
            list(fold['retained_training_positions'])
            == sorted(fold['retained_training_positions'])
            if 'retained_training_positions' in fold else True
            for fold in filtered_folds
        ))

    def test_candidate_selector_rejects_any_test_bearing_input(self):
        with self.assertRaisesRegex(ValueError, 'Independent Test'):
            select_research_candidate_noise_band([{'independent_test': {'score': 1.0}}])

    def test_noise_experiment_does_not_mutate_production_or_regression_contract(self):
        dataset = build_prediction_feature_dataset(self._bars(), horizon=1)
        production_features = dataset.features
        production_labels = dataset.classification_labels
        regression_features = dataset.regression_features
        regression_labels = dataset.regression_labels

        _filtered_partition(dataset, 0, dataset.sample_count, 0.005)

        self.assertEqual(dataset.feature_names, FEATURE_NAMES)
        self.assertEqual(dataset.features, production_features)
        self.assertEqual(dataset.classification_labels, production_labels)
        self.assertEqual(dataset.regression_features, regression_features)
        self.assertEqual(dataset.regression_labels, regression_labels)
