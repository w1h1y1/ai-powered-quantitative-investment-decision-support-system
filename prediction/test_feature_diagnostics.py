from datetime import date, timedelta
from decimal import Decimal
from math import sin

from django.test import SimpleTestCase

from prediction.feature_diagnostics import (
    CLASSIFICATION_FEATURE_SETS,
    REGRESSION_FEATURE_SETS,
    build_experiment_dataset,
    feature_quality_report,
    target_alignment_example,
    target_distribution,
)
from prediction.feature_service import FEATURE_NAMES, REGRESSION_FEATURE_NAMES
from prediction.ml_service import (
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.services import PredictionBar


class PredictionFeatureDiagnosticTests(SimpleTestCase):
    def _bars(self, count=800):
        start = date(2022, 1, 1)
        values = []
        previous = 100.0
        for index in range(count):
            close = previous * (1 + 0.0004 + 0.008 * sin(index / 7))
            open_price = previous * (1 + 0.001 * sin(index / 3))
            values.append(PredictionBar(
                date=start + timedelta(days=index),
                open=Decimal(str(open_price)),
                high=Decimal(str(max(open_price, close) * 1.01)),
                low=Decimal(str(min(open_price, close) * 0.99)),
                close=Decimal(str(close)),
                volume=1_000_000 + (index % 37) * 13_000,
            ))
            previous = close
        return tuple(values)

    def test_experiment_a_is_exactly_the_current_production_feature_contract(self):
        self.assertEqual(CLASSIFICATION_FEATURE_SETS['A'], FEATURE_NAMES)
        self.assertEqual(REGRESSION_FEATURE_SETS['A'], REGRESSION_FEATURE_NAMES)
        self.assertNotEqual(FEATURE_NAMES, REGRESSION_FEATURE_NAMES)

    def test_all_ablation_sets_use_identical_aligned_rows_and_purged_splits(self):
        bars = self._bars()
        for task, horizon in (('classification', 1), ('regression', 10)):
            datasets = {
                experiment: build_experiment_dataset(bars, horizon, task, experiment)
                for experiment in ('A', 'B', 'C', 'D', 'E')
            }
            sample_indices = {dataset.sample_indices for dataset in datasets.values()}
            self.assertEqual(len(sample_indices), 1)
            for dataset in datasets.values():
                split = build_purged_chronological_split(dataset)
                folds = build_purged_walk_forward_folds(dataset, split)
                self.assertEqual(split['gap_size'], horizon)
                self.assertTrue(split['boundaries']['train_validation_purge_safe'])
                self.assertTrue(split['boundaries']['validation_test_purge_safe'])
                self.assertTrue(all(fold['purge_safe'] for fold in folds))

    def test_target_alignment_uses_exact_future_horizon_close_without_off_by_one(self):
        bars = self._bars()
        dataset = build_experiment_dataset(bars, 10, 'regression', 'A')

        alignment = target_alignment_example(bars, dataset)

        self.assertEqual(alignment['target_index'] - alignment['feature_index'], 10)
        self.assertEqual(
            alignment['target_date'],
            bars[alignment['feature_index'] + 10].date.isoformat(),
        )
        self.assertAlmostEqual(
            alignment['calculated_target'], alignment['stored_target'], places=12,
        )

    def test_experimental_features_at_time_t_do_not_change_when_future_bar_changes(self):
        bars = self._bars()
        original = build_experiment_dataset(bars, 10, 'regression', 'E')
        feature_index = original.sample_indices[30]
        future_index = feature_index + 10
        changed_bars = list(bars)
        future = changed_bars[future_index]
        changed_bars[future_index] = PredictionBar(
            date=future.date,
            open=future.open,
            high=future.high * 2,
            low=future.low,
            close=future.close * 2,
            volume=future.volume * 2,
        )

        changed = build_experiment_dataset(
            tuple(changed_bars), 10, 'regression', 'E',
        )
        changed_position = changed.sample_indices.index(feature_index)

        self.assertEqual(
            original.regression_features[30],
            changed.regression_features[changed_position],
        )
        self.assertNotEqual(
            original.regression_labels[30],
            changed.regression_labels[changed_position],
        )

    def test_target_distribution_reports_all_requested_noise_bands(self):
        dataset = build_experiment_dataset(
            self._bars(), 1, 'classification', 'A',
        )

        distribution = target_distribution(dataset)

        self.assertEqual(
            set(distribution['within_noise_band']), {'0.001', '0.0025', '0.005'},
        )
        self.assertEqual(
            distribution['up_count'] + distribution['down_count'],
            distribution['sample_count'],
        )

    def test_feature_quality_separates_raw_warmup_missingness_from_model_matrix(self):
        bars = self._bars()
        dataset = build_experiment_dataset(bars, 1, 'classification', 'E')

        report = feature_quality_report(dataset, 'classification', bars=bars)

        self.assertEqual(report['source'], 'development_data_only')
        self.assertTrue(any(
            feature['raw_pre_warmup_missing_ratio'] > 0
            for feature in report['features']
        ))
        self.assertTrue(all(
            feature['model_matrix_missing_ratio'] == 0
            for feature in report['features']
        ))

    def test_noise_band_filter_cannot_silently_change_split_boundaries(self):
        with self.assertRaisesRegex(ValueError, 'Test remains untouched'):
            build_experiment_dataset(
                self._bars(), 1, 'classification', 'A', noise_band=0.001,
            )
