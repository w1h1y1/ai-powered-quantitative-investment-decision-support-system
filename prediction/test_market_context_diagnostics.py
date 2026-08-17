from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from math import sin

from django.test import SimpleTestCase

from prediction.feature_service import (
    FEATURE_NAMES,
    REGRESSION_FEATURE_NAMES,
    build_prediction_feature_dataset,
)
from prediction.market_context_diagnostics import (
    CLASSIFICATION_MARKET_FEATURE_SETS,
    MARKET_CONTEXT_EXPERIMENTS,
    REGRESSION_MARKET_FEATURE_SETS,
    build_date_aligned_market_rows,
    build_market_context_experiment_datasets,
    select_market_context_candidate,
)
from prediction.ml_service import (
    PREDICTION_PIPELINE_VERSION,
    PREDICTION_QUALITY_GATE_THRESHOLDS,
    build_purged_chronological_split,
    build_purged_walk_forward_folds,
)
from prediction.services import PredictionBar


class MarketContextDiagnosticTests(SimpleTestCase):
    def _dates(self, count=504):
        values, current = [], date(2024, 1, 2)
        while len(values) < count:
            if current.weekday() < 5:
                values.append(current)
            current += timedelta(days=1)
        return values

    def _bars(self, count=504, *, base=100.0, phase=0.0, dates=None):
        dates = dates or self._dates(count)
        bars, previous = [], base
        for index, market_date in enumerate(dates):
            close = previous * (1 + 0.0004 + 0.008 * sin(index / 7 + phase))
            open_price = previous * (1 + 0.001 * sin(index / 5 + phase))
            bars.append(PredictionBar(
                date=market_date, open=Decimal(str(open_price)),
                high=Decimal(str(max(open_price, close) * 1.01)),
                low=Decimal(str(min(open_price, close) * 0.99)),
                close=Decimal(str(close)), volume=1_000_000 + index * 1_000,
            ))
            previous = close
        return tuple(bars)

    def test_exact_date_alignment_never_uses_row_position_or_future_fill(self):
        dates = self._dates(100)
        stock = self._bars(dates=dates)
        spy = self._bars(dates=[value for index, value in enumerate(dates) if index != 50], phase=1)
        qqq = self._bars(dates=dates, phase=2)
        rows, report = build_date_aligned_market_rows(stock, spy, qqq)

        self.assertIsNone(rows[50]['spy_date'])
        self.assertEqual(rows[51]['spy_date'], dates[51])
        self.assertIsNone(rows[50]['spy_return_1d'])
        self.assertIsNone(rows[51]['spy_return_1d'])
        self.assertIn(dates[50].isoformat(), report['missing_spy_on_stock_dates'])
        self.assertFalse(report['future_fill_used'])
        self.assertFalse(report['row_index_alignment_used'])

    def test_rolling_market_features_are_prefix_invariant(self):
        dates = self._dates(140)
        stock = self._bars(dates=dates)
        spy = self._bars(dates=dates, phase=1)
        qqq = self._bars(dates=dates, phase=2)
        original, _ = build_date_aligned_market_rows(stock, spy, qqq)
        changed_spy = list(spy)
        changed_qqq = list(qqq)
        for index in range(101, len(dates)):
            changed_spy[index] = replace(changed_spy[index], close=changed_spy[index].close * 4)
            changed_qqq[index] = replace(changed_qqq[index], close=changed_qqq[index].close * 3)
        changed, _ = build_date_aligned_market_rows(stock, tuple(changed_spy), tuple(changed_qqq))

        for name in (
            'spy_return_1d', 'spy_return_60d', 'spy_volatility_60d',
            'qqq_close_to_ma60', 'relative_strength_qqq_20d',
            'correlation_stock_spy_60d', 'beta_stock_qqq_60d',
        ):
            self.assertAlmostEqual(original[100][name], changed[100][name], places=14)

    def test_relative_strength_uses_stock_minus_same_date_benchmark_return(self):
        dates = self._dates(100)
        stock = self._bars(dates=dates)
        spy = self._bars(dates=dates, phase=1)
        rows, _ = build_date_aligned_market_rows(stock, spy, self._bars(dates=dates, phase=2))
        index, period = 80, 20
        stock_return = float(stock[index].close / stock[index - period].close - 1)
        spy_return = float(spy[index].close / spy[index - period].close - 1)
        self.assertAlmostEqual(
            rows[index]['relative_strength_spy_20d'], stock_return - spy_return,
            places=14,
        )

    def test_zero_variance_correlation_and_beta_are_unavailable_not_fake_values(self):
        dates = self._dates(100)
        stock = self._bars(dates=dates)
        constant = tuple(replace(bar, close=Decimal('100')) for bar in self._bars(dates=dates))
        rows, _ = build_date_aligned_market_rows(stock, constant, constant)
        self.assertIsNone(rows[80]['correlation_stock_spy_60d'])
        self.assertIsNone(rows[80]['beta_stock_spy_60d'])

    def test_a_to_f_share_identical_development_dates_and_fixed_folds(self):
        dates = self._dates(504)
        stock = self._bars(dates=dates)
        bundle = build_market_context_experiment_datasets(
            stock, self._bars(dates=dates, phase=1), self._bars(dates=dates, phase=2),
            1, 'classification',
        )
        self.assertEqual(
            len({dataset.sample_indices for dataset in bundle['datasets'].values()}), 1,
        )
        signatures = set()
        for dataset in bundle['datasets'].values():
            folds = build_purged_walk_forward_folds(
                dataset, {'development_samples': dataset.sample_count},
            )
            signatures.add(tuple(
                (fold['training_samples'], fold['validation_samples'],
                 fold['boundaries']['validation_first_feature_index'],
                 fold['boundaries']['validation_last_feature_index'])
                for fold in folds
            ))
        self.assertEqual(len(signatures), 1)

    def test_test_period_benchmark_deletion_cannot_move_development_or_folds(self):
        dates = self._dates(504)
        stock = self._bars(dates=dates)
        spy = self._bars(dates=dates, phase=1)
        qqq = self._bars(dates=dates, phase=2)
        production = build_prediction_feature_dataset(stock, 1)
        split = build_purged_chronological_split(production)
        test_first_index = production.sample_indices[split['final_test_start']]
        original = build_market_context_experiment_datasets(
            stock, spy, qqq, 1, 'classification',
        )
        qqq_without_test = tuple(
            bar for index, bar in enumerate(qqq) if index < test_first_index
        )
        changed = build_market_context_experiment_datasets(
            stock, spy, qqq_without_test, 1, 'classification',
        )
        self.assertEqual(original['common_sample_indices'], changed['common_sample_indices'])
        self.assertEqual(original['fixed_partition'], changed['fixed_partition'])

    def test_classification_and_regression_keep_independent_feature_designs(self):
        self.assertIn('spy_return_1d', CLASSIFICATION_MARKET_FEATURE_SETS['B'])
        self.assertNotIn('spy_return_60d', CLASSIFICATION_MARKET_FEATURE_SETS['B'])
        self.assertIn('spy_return_60d', REGRESSION_MARKET_FEATURE_SETS['B'])
        self.assertNotIn('spy_return_1d', REGRESSION_MARKET_FEATURE_SETS['B'])
        self.assertEqual(CLASSIFICATION_MARKET_FEATURE_SETS['A'], FEATURE_NAMES)
        self.assertEqual(REGRESSION_MARKET_FEATURE_SETS['A'], REGRESSION_FEATURE_NAMES)

    def test_classification_and_regression_purge_gaps_remain_one_and_ten(self):
        dates = self._dates(504)
        stock, spy, qqq = self._bars(dates=dates), self._bars(dates=dates, phase=1), self._bars(dates=dates, phase=2)
        for task, horizon in (('classification', 1), ('regression', 10)):
            bundle = build_market_context_experiment_datasets(stock, spy, qqq, horizon, task)
            for dataset in bundle['datasets'].values():
                folds = build_purged_walk_forward_folds(
                    dataset, {'development_samples': dataset.sample_count},
                )
                self.assertTrue(folds)
                self.assertTrue(all(fold['gap_size'] == horizon for fold in folds))
                self.assertTrue(all(fold['purge_safe'] for fold in folds))

    def test_test_matrix_is_not_constructed_before_candidate_freeze(self):
        dates = self._dates(504)
        stock, spy, qqq = self._bars(dates=dates), self._bars(dates=dates, phase=1), self._bars(dates=dates, phase=2)
        development = build_market_context_experiment_datasets(stock, spy, qqq, 1, 'classification')
        post_freeze = build_market_context_experiment_datasets(
            stock, spy, qqq, 1, 'classification', include_independent_test=True,
        )
        self.assertFalse(development['independent_test_accessed'])
        self.assertEqual(development['independent_test_datasets'], {})
        self.assertTrue(post_freeze['independent_test_accessed'])
        self.assertTrue(post_freeze['fixed_partition']['development_test_purge_safe'])

    def test_candidate_selector_rejects_test_bearing_input(self):
        with self.assertRaisesRegex(ValueError, 'Independent Test'):
            select_market_context_candidate([{
                'experiment': 'A', 'symbol': 'AAPL', 'lookback': 504,
                'independent_test': {'score': 1.0},
            }], 'classification')

    def test_production_targets_and_quality_gate_remain_unchanged(self):
        dates = self._dates(504)
        stock, spy, qqq = self._bars(dates=dates), self._bars(dates=dates, phase=1), self._bars(dates=dates, phase=2)
        thresholds = dict(PREDICTION_QUALITY_GATE_THRESHOLDS)
        production_classification = build_prediction_feature_dataset(stock, 1)
        production_regression = build_prediction_feature_dataset(stock, 10)
        class_bundle = build_market_context_experiment_datasets(stock, spy, qqq, 1, 'classification')
        reg_bundle = build_market_context_experiment_datasets(stock, spy, qqq, 10, 'regression')
        first_class_index = class_bundle['common_sample_indices'][0]
        first_reg_index = reg_bundle['common_sample_indices'][0]
        class_position = production_classification.sample_indices.index(first_class_index)
        reg_position = production_regression.sample_indices.index(first_reg_index)
        self.assertEqual(
            class_bundle['datasets']['A'].features[0],
            production_classification.features[class_position],
        )
        self.assertEqual(
            reg_bundle['datasets']['A'].regression_features[0],
            production_regression.regression_features[reg_position],
        )
        self.assertEqual(
            class_bundle['datasets']['A'].classification_labels[0],
            production_classification.classification_labels[class_position],
        )
        self.assertAlmostEqual(
            reg_bundle['datasets']['A'].regression_labels[0],
            production_regression.regression_labels[reg_position], places=14,
        )
        self.assertEqual(PREDICTION_QUALITY_GATE_THRESHOLDS, thresholds)

    def test_vix_is_explicitly_not_run_and_research_not_wired_to_production(self):
        import prediction.services as production_services
        self.assertIn('G', MARKET_CONTEXT_EXPERIMENTS)
        self.assertIn('not run', MARKET_CONTEXT_EXPERIMENTS['G'])
        self.assertFalse(hasattr(production_services, 'MARKET_CONTEXT_EXPERIMENTS'))
        self.assertNotIn('market-context', PREDICTION_PIPELINE_VERSION.lower())
