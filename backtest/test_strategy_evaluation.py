from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security
from market.regime_config import (
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
)
from market.regime_service import (
    MarketRegimeDataRateLimited,
    MarketRegimeDataUnavailable,
)
from market.strategy_selection_service import (
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
)

from .services import (
    ONE,
    REGIME_BULL,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
    DailyBacktestBar,
    StrategyParameters,
    build_indicator_inputs,
    calculate_bollinger_lower,
    format_decimal,
    simulate_layered_strategy,
)
from .strategy_evaluation_service import (
    EVALUATION_STATUS_NOT_APPLICABLE,
    EVALUATION_STATUS_UNAVAILABLE,
    STRATEGY_EVALUATOR_REGISTRY,
    StrategyEvaluationContractError,
    StrategyEvaluatorRegistration,
    evaluate_selected_strategy,
    evaluate_trend_following,
    simulate_mean_reversion,
)


def regime_payload(regime=REGIME_BULLISH, *, available=True):
    return {
        'symbol': 'AAPL',
        'security_id': 1,
        'latest_market_date': '2026-08-14' if available else None,
        'regime_available': available,
        'regime_unavailable_reason': None if available else 'insufficient_history',
        'regime': regime if available else None,
        'confidence': 'medium' if available else None,
        'confidence_score': 0.68 if available else None,
    }


def fake_security(symbol, pk):
    return SimpleNamespace(
        id=pk,
        pk=pk,
        symbol=symbol,
        name=f'{symbol} Security',
        asset_type='STOCK' if symbol != 'SPY' else 'ETF',
        exchange='NASDAQ',
        currency='USD',
    )


def completed_evaluation(strategy_id):
    return {
        'evaluation_available': True,
        'evaluation_status': 'completed',
        'evaluation_unavailable_reason': None,
        'evaluation_strategy': strategy_id,
        'initial_capital': '10000.000000',
        'final_equity': '10100.000000',
        'total_return': '1.000000',
        'maximum_drawdown': '0.500000',
        'annualized_volatility': '10.000000',
        'total_fees': '2.000000',
        'executed_order_count': 0,
        'equity_curve': [],
        'drawdown_curve': [],
        'trades': [],
    }


class StrategyEvaluationDispatchTests(SimpleTestCase):
    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)

    def run_with_evaluator(self, regime, strategy_id):
        trend_evaluator = Mock(return_value=completed_evaluation(STRATEGY_TREND_FOLLOWING))
        mean_evaluator = Mock(return_value=completed_evaluation(STRATEGY_MEAN_REVERSION))
        evaluators = {
            STRATEGY_TREND_FOLLOWING: trend_evaluator,
            STRATEGY_MEAN_REVERSION: mean_evaluator,
        }
        registry = {
            STRATEGY_TREND_FOLLOWING: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_TREND_FOLLOWING,
                evaluator=trend_evaluator,
                active_backtest=True,
            ),
            STRATEGY_MEAN_REVERSION: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_MEAN_REVERSION,
                evaluator=mean_evaluator,
                active_backtest=True,
            ),
            STRATEGY_RISK_OFF: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_RISK_OFF,
                evaluator=None,
                active_backtest=False,
            ),
        }
        with (
            patch(
                'backtest.strategy_evaluation_service.get_market_regime',
                return_value=regime_payload(regime),
            ) as get_market_regime,
            patch.dict(
                STRATEGY_EVALUATOR_REGISTRY,
                registry,
                clear=True,
            ),
        ):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
            )
        get_market_regime.assert_called_once_with(self.security)
        evaluators[strategy_id].assert_called_once()
        self.assertEqual(sum(item.call_count for item in evaluators.values()), 1)
        call_kwargs = evaluators[strategy_id].call_args.kwargs
        self.assertEqual(call_kwargs['start_date'], date(2025, 8, 14))
        self.assertEqual(call_kwargs['end_date'], date(2026, 8, 14))
        return result

    def test_registry_contains_only_three_formal_strategies(self):
        self.assertEqual(
            set(STRATEGY_EVALUATOR_REGISTRY),
            {
                STRATEGY_TREND_FOLLOWING,
                STRATEGY_MEAN_REVERSION,
                STRATEGY_RISK_OFF,
            },
        )
        self.assertIsNone(STRATEGY_EVALUATOR_REGISTRY[STRATEGY_RISK_OFF].evaluator)

    def test_bullish_trend_dispatches_trend_following(self):
        result = self.run_with_evaluator(REGIME_BULLISH, STRATEGY_TREND_FOLLOWING)

        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertTrue(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assertEqual(result['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)

    def test_bearish_trend_still_dispatches_trend_following_with_long_only_constraint(self):
        result = self.run_with_evaluator(REGIME_BEARISH, STRATEGY_TREND_FOLLOWING)

        self.assertEqual(result['market_regime'], REGIME_BEARISH)
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertFalse(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assertEqual(result['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)

    def test_sideways_range_dispatches_independent_mean_reversion(self):
        result = self.run_with_evaluator(REGIME_SIDEWAYS, STRATEGY_MEAN_REVERSION)

        self.assertEqual(result['selected_strategy'], STRATEGY_MEAN_REVERSION)
        self.assertEqual(result['evaluation_strategy'], STRATEGY_MEAN_REVERSION)

    @patch('backtest.strategy_evaluation_service.simulate_mean_reversion')
    @patch('backtest.strategy_evaluation_service.simulate_layered_strategy')
    @patch('backtest.strategy_evaluation_service.load_daily_backtest_bars')
    @patch('backtest.strategy_evaluation_service.get_market_regime')
    def test_high_volatility_returns_risk_off_without_loading_or_simulating(
        self,
        get_market_regime,
        load_daily_backtest_bars,
        simulate_layered_strategy,
        simulate_mean_reversion,
    ):
        get_market_regime.return_value = regime_payload(REGIME_HIGH_VOLATILITY)

        result = evaluate_selected_strategy(
            security=self.security,
            benchmark=self.benchmark,
        )

        self.assertEqual(result['selected_strategy'], STRATEGY_RISK_OFF)
        self.assertTrue(result['risk_off'])
        self.assertFalse(result['evaluation_available'])
        self.assertEqual(result['evaluation_status'], EVALUATION_STATUS_NOT_APPLICABLE)
        self.assertIn('defensive state', result['evaluation_unavailable_reason'])
        self.assertEqual(result['trades'], [])
        load_daily_backtest_bars.assert_not_called()
        simulate_layered_strategy.assert_not_called()
        simulate_mean_reversion.assert_not_called()

    @patch('backtest.strategy_evaluation_service.get_market_regime')
    def test_market_regime_unavailable_preserves_diagnostics_without_dispatching(self, get_market_regime):
        get_market_regime.return_value = regime_payload(available=False)
        active_evaluator = Mock()
        registry = {
            STRATEGY_TREND_FOLLOWING: StrategyEvaluatorRegistration(
                STRATEGY_TREND_FOLLOWING, active_evaluator, True,
            ),
            STRATEGY_MEAN_REVERSION: StrategyEvaluatorRegistration(
                STRATEGY_MEAN_REVERSION, active_evaluator, True,
            ),
            STRATEGY_RISK_OFF: StrategyEvaluatorRegistration(
                STRATEGY_RISK_OFF, None, False,
            ),
        }
        with patch.dict(STRATEGY_EVALUATOR_REGISTRY, registry, clear=True):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
            )

        self.assertFalse(result['strategy_selection_available'])
        self.assertFalse(result['evaluation_available'])
        self.assertEqual(result['evaluation_status'], EVALUATION_STATUS_UNAVAILABLE)
        self.assertEqual(result['market_regime_unavailable_reason'], 'insufficient_history')
        active_evaluator.assert_not_called()

    @patch('backtest.strategy_evaluation_service.select_strategy')
    @patch('backtest.strategy_evaluation_service.get_market_regime')
    def test_strategy_selection_unavailable_does_not_dispatch(self, get_market_regime, select_strategy):
        get_market_regime.return_value = regime_payload(REGIME_BULLISH)
        select_strategy.return_value = {
            'symbol': 'AAPL',
            'strategy_selection_available': False,
            'strategy_selection_unavailable_reason': 'unsupported_market_regime',
            'market_regime': 'future_regime',
            'selected_strategy': None,
        }

        active_evaluator = Mock()
        registry = {
            STRATEGY_TREND_FOLLOWING: StrategyEvaluatorRegistration(
                STRATEGY_TREND_FOLLOWING, active_evaluator, True,
            ),
            STRATEGY_MEAN_REVERSION: StrategyEvaluatorRegistration(
                STRATEGY_MEAN_REVERSION, active_evaluator, True,
            ),
            STRATEGY_RISK_OFF: StrategyEvaluatorRegistration(
                STRATEGY_RISK_OFF, None, False,
            ),
        }
        with patch.dict(STRATEGY_EVALUATOR_REGISTRY, registry, clear=True):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
            )

        self.assertFalse(result['evaluation_available'])
        self.assertEqual(result['evaluation_status'], EVALUATION_STATUS_UNAVAILABLE)
        self.assertEqual(result['evaluation_unavailable_reason'], 'unsupported_market_regime')
        active_evaluator.assert_not_called()

    @patch('backtest.strategy_evaluation_service.get_market_regime')
    def test_historical_end_date_cannot_precede_current_regime_date(self, get_market_regime):
        get_market_regime.return_value = regime_payload(REGIME_BULLISH)
        evaluator = Mock()
        registration = StrategyEvaluatorRegistration(
            STRATEGY_TREND_FOLLOWING,
            evaluator,
            True,
        )
        with patch.dict(
            STRATEGY_EVALUATOR_REGISTRY,
            {STRATEGY_TREND_FOLLOWING: registration},
            clear=True,
        ):
            with self.assertRaises(StrategyEvaluationContractError):
                evaluate_selected_strategy(
                    security=self.security,
                    benchmark=self.benchmark,
                    start_date=date(2025, 8, 13),
                    end_date=date(2026, 8, 13),
                )
        evaluator.assert_not_called()

    @patch('backtest.strategy_evaluation_service.get_market_regime')
    def test_provider_errors_propagate_without_fallback(self, get_market_regime):
        for error in (
            MarketRegimeDataRateLimited('rate limited'),
            MarketRegimeDataUnavailable('provider unavailable'),
        ):
            with self.subTest(error=type(error).__name__):
                get_market_regime.side_effect = error
                with self.assertRaises(type(error)):
                    evaluate_selected_strategy(
                        security=self.security,
                        benchmark=self.benchmark,
                    )


class TrendFollowingEvaluationTests(SimpleTestCase):
    """Run the real Core-only adapter with deterministic, provider-free bars."""

    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)
        self.end_date = date(2026, 8, 14)
        self.asset_bars = self.make_trending_bars(
            base=Decimal('100'),
            step=Decimal('0.50'),
        )
        self.benchmark_bars = self.make_trending_bars(
            base=Decimal('300'),
            step=Decimal('0.20'),
        )
        # The existing Core-only evaluator requires 220 trailing warm-up rows.
        self.start_date = self.asset_bars[220].date

    def make_trending_bars(self, *, base, step, count=300):
        first_date = self.end_date - timedelta(days=count - 1)
        bars = []
        for index in range(count):
            close = base + (step * Decimal(index))
            open_price = close - Decimal('0.25')
            bars.append(DailyBacktestBar(
                date=first_date + timedelta(days=index),
                open=open_price,
                high=close + ONE,
                low=open_price - ONE,
                close=close,
            ))
        return tuple(bars)

    def loader(self, security, *_args, requested_start_date, required_warmup_rows, **_kwargs):
        bars = self.asset_bars if security.pk == self.security.pk else self.benchmark_bars
        source = {
            'source': 'deterministic_test_fixture',
            'price_model': 'TEST_DAILY_OHLC',
            'requested_start_date': bars[0].date.isoformat(),
            'requested_end_date': bars[-1].date.isoformat(),
            'loaded_start_date': bars[0].date.isoformat(),
            'loaded_end_date': bars[-1].date.isoformat(),
            'record_count': len(bars),
            'warmup_record_count': sum(
                bar.date < requested_start_date for bar in bars
            ),
            'required_warmup_rows': required_warmup_rows,
            'fetched_from_provider': False,
            'provider_fetch': None,
            'upstream_error': None,
        }
        return bars, source

    def run_real_trend_evaluation(self, regime):
        upstream = regime_payload(regime)
        upstream.update({
            'latest_market_date': self.end_date.isoformat(),
            'confidence': 'high',
            'confidence_score': 0.8,
        })
        trend_evaluator = Mock(wraps=evaluate_trend_following)
        registration = StrategyEvaluatorRegistration(
            strategy_id=STRATEGY_TREND_FOLLOWING,
            evaluator=trend_evaluator,
            active_backtest=True,
        )
        with (
            patch(
                'backtest.strategy_evaluation_service.get_market_regime',
                return_value=upstream,
            ),
            patch(
                'backtest.strategy_evaluation_service.load_daily_backtest_bars',
                side_effect=self.loader,
            ),
            patch.dict(
                STRATEGY_EVALUATOR_REGISTRY,
                {STRATEGY_TREND_FOLLOWING: registration},
                clear=True,
            ),
        ):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
                start_date=self.start_date,
                end_date=self.end_date,
                initial_capital=Decimal('10000'),
                transaction_fee=Decimal('1'),
            )
        trend_evaluator.assert_called_once()
        return result, trend_evaluator

    def assert_completed_trend_schema(self, result):
        self.assertTrue(result['evaluation_available'])
        self.assertEqual(result['evaluation_status'], 'completed')
        self.assertEqual(result['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)
        for field in (
            'initial_capital', 'final_equity', 'total_return',
            'maximum_drawdown', 'annualized_volatility',
        ):
            self.assertIsNotNone(result[field], field)
            Decimal(result[field])
        self.assertIsInstance(result['executed_order_count'], int)
        self.assertGreaterEqual(result['executed_order_count'], 0)
        self.assertIsInstance(result['equity_curve'], list)
        self.assertTrue(result['equity_curve'])
        self.assertIsInstance(result['drawdown_curve'], list)
        self.assertEqual(
            len(result['drawdown_curve']),
            len(result['equity_curve']),
        )
        self.assertIsInstance(result['trades'], list)
        self.assertEqual(
            result['strategy_parameters']['strategy_id'],
            STRATEGY_TREND_FOLLOWING,
        )
        self.assertEqual(
            result['strategy_parameters']['adapter'],
            'existing_core_only',
        )
        self.assertEqual(result['evaluation_window'], {
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
        })
        self.assertEqual(
            result['data_source']['source'],
            'deterministic_test_fixture',
        )
        self.assertEqual(
            result['data_source']['actual_start_date'],
            self.start_date.isoformat(),
        )
        self.assertEqual(
            result['data_source']['actual_end_date'],
            self.end_date.isoformat(),
        )

    def test_bullish_trend_runs_real_trend_evaluator_and_returns_complete_schema(self):
        result, trend_evaluator = self.run_real_trend_evaluation(REGIME_BULLISH)

        self.assertEqual(result['market_regime'], REGIME_BULLISH)
        self.assertEqual(result['regime_confidence'], 'high')
        self.assertEqual(result['regime_confidence_score'], 0.8)
        self.assertEqual(result['selection_confidence'], 'high')
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertTrue(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assert_completed_trend_schema(result)
        self.assertNotIn('market_regime', trend_evaluator.call_args.kwargs)

    def test_bearish_trend_runs_same_historical_evaluator_and_preserves_constraint(self):
        result, trend_evaluator = self.run_real_trend_evaluation(REGIME_BEARISH)

        self.assertEqual(result['market_regime'], REGIME_BEARISH)
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(result['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertFalse(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assertNotEqual(result['selected_strategy'], STRATEGY_RISK_OFF)
        self.assertNotEqual(result['evaluation_strategy'], STRATEGY_MEAN_REVERSION)
        self.assert_completed_trend_schema(result)
        self.assertNotIn('market_regime', trend_evaluator.call_args.kwargs)

        # The current formal bearish regime is provenance only.  Historical
        # bars retain the evaluator's own causal benchmark regime rather than
        # being overwritten with the current classification.
        self.assertTrue(all(
            point['market_regime'] == REGIME_BULL
            for point in result['equity_curve']
        ))

    def test_trend_following_trades_execute_on_the_next_bar_open(self):
        result, _trend_evaluator = self.run_real_trend_evaluation(REGIME_BULLISH)

        self.assertTrue(result['trades'])
        date_to_index = {
            bar.date.isoformat(): index
            for index, bar in enumerate(self.asset_bars)
        }
        date_to_open = {
            bar.date.isoformat(): bar.open
            for bar in self.asset_bars
        }
        for trade in result['trades']:
            self.assertEqual(
                date_to_index[trade['execution_date']],
                date_to_index[trade['signal_date']] + 1,
            )
            self.assertEqual(
                trade['execution_price'],
                format_decimal(date_to_open[trade['execution_date']]),
            )

    def test_repeated_real_trend_evaluations_are_deterministic(self):
        first, _first_evaluator = self.run_real_trend_evaluation(REGIME_BULLISH)
        second, _second_evaluator = self.run_real_trend_evaluation(REGIME_BULLISH)

        for field in (
            'total_return', 'final_equity', 'maximum_drawdown',
            'annualized_volatility', 'executed_order_count', 'trades',
            'equity_curve', 'drawdown_curve', 'strategy_parameters',
        ):
            self.assertEqual(first[field], second[field], field)

    def test_future_bars_do_not_change_trend_decisions_inside_the_prefix(self):
        parameters = StrategyParameters()
        prefix_asset = self.asset_bars[:280]
        prefix_benchmark = self.benchmark_bars[:280]
        prefix_indicators = build_indicator_inputs(
            prefix_asset,
            prefix_benchmark,
            parameters,
        )
        extended_indicators = build_indicator_inputs(
            self.asset_bars,
            self.benchmark_bars,
            parameters,
        )

        prefix = simulate_layered_strategy(
            bars=prefix_asset,
            indicators=prefix_indicators,
            start_date=self.start_date,
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal('1'),
            parameters=parameters,
            enable_swing=False,
        )
        extended = simulate_layered_strategy(
            bars=self.asset_bars,
            indicators=extended_indicators,
            start_date=self.start_date,
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal('1'),
            parameters=parameters,
            enable_swing=False,
        )

        self.assertEqual(
            prefix['equity_curve'],
            extended['equity_curve'][:len(prefix['equity_curve'])],
        )
        prefix_end = prefix['equity_curve'][-1]['date']
        self.assertEqual(
            prefix['trades'],
            [
                trade
                for trade in extended['trades']
                if trade['execution_date'] <= prefix_end
            ],
        )


class MeanReversionEngineTests(SimpleTestCase):
    def make_inputs(self, extra_closes=()):
        closes = [Decimal('90'), Decimal('110'), Decimal('100'), Decimal('100')]
        closes.extend(Decimal(value) for value in extra_closes)
        opens = [Decimal('100'), Decimal('101'), Decimal('103'), Decimal('104')]
        opens.extend(Decimal('105') + Decimal(index) for index in range(len(extra_closes)))
        bars = tuple(
            DailyBacktestBar(
                date=date(2026, 1, 5) + timedelta(days=index),
                open=opens[index],
                high=max(opens[index], close) + ONE,
                low=min(opens[index], close) - ONE,
                close=close,
            )
            for index, close in enumerate(closes)
        )
        count = len(bars)
        ma20 = tuple(Decimal('100') for _ in range(count))
        rsi = [Decimal('30'), Decimal('60'), Decimal('50'), Decimal('50')]
        rsi.extend(Decimal('50') for _ in extra_closes)
        atr = tuple(Decimal('2') for _ in range(count))
        upper = tuple(Decimal('120') for _ in range(count))
        lower = tuple(Decimal('95') for _ in range(count))
        return bars, ma20, tuple(rsi), atr, upper, lower

    def run_engine(self, extra_closes=()):
        bars, ma20, rsi, atr, upper, lower = self.make_inputs(extra_closes)
        return simulate_mean_reversion(
            bars=bars,
            start_date=bars[0].date,
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal('1'),
            ma20=ma20,
            rsi14=rsi,
            atr14=atr,
            bollinger_upper=upper,
            bollinger_lower=lower,
        )

    def test_independent_mean_reversion_executes_signals_at_next_open(self):
        result = self.run_engine()

        self.assertEqual(len(result['trades']), 2)
        buy, sell = result['trades']
        self.assertEqual(buy['reason'], 'MEAN_REVERSION_ENTRY_OVERSOLD_LOWER_BAND')
        self.assertEqual(buy['signal_date'], '2026-01-05')
        self.assertEqual(buy['execution_date'], '2026-01-06')
        self.assertEqual(buy['execution_price'], '101.000000')
        self.assertEqual(sell['signal_date'], '2026-01-06')
        self.assertEqual(sell['execution_date'], '2026-01-07')
        self.assertEqual(sell['execution_price'], '103.000000')

    def test_appending_future_bars_does_not_change_prefix_decisions(self):
        prefix = self.run_engine()
        extended = self.run_engine(extra_closes=('1', '500'))

        self.assertEqual(
            prefix['equity_curve'],
            extended['equity_curve'][:len(prefix['equity_curve'])],
        )
        prefix_end = prefix['equity_curve'][-1]['date']
        self.assertEqual(
            prefix['trades'],
            [trade for trade in extended['trades'] if trade['execution_date'] <= prefix_end],
        )

    def test_repeated_mean_reversion_runs_are_deterministic(self):
        self.assertEqual(self.run_engine(), self.run_engine())

    def test_bollinger_lower_is_causal_when_future_prices_are_appended(self):
        prefix_bars, *_ = self.make_inputs(extra_closes=tuple('100' for _ in range(20)))
        extended_bars, *_ = self.make_inputs(
            extra_closes=tuple('100' for _ in range(20)) + ('1', '1000'),
        )

        self.assertEqual(
            calculate_bollinger_lower(prefix_bars),
            calculate_bollinger_lower(extended_bars)[:len(prefix_bars)],
        )

    @patch('backtest.strategy_evaluation_service.simulate_layered_strategy')
    @patch('backtest.strategy_evaluation_service._prepare_trend_following_data')
    def test_trend_adapter_reuses_core_only_simulator_without_hybrid_swing(
        self,
        prepare,
        simulate,
    ):
        security = fake_security('AAPL', 1)
        benchmark = fake_security('SPY', 2)
        bar = DailyBacktestBar(
            date=date(2026, 1, 5),
            open=Decimal('100'),
            high=Decimal('101'),
            low=Decimal('99'),
            close=Decimal('100'),
        )
        prepare.return_value = {
            'bars': (bar,),
            'indicators': {'sentinel': True},
            'data_source': {},
        }
        simulate.return_value = {
            'final_equity': Decimal('10000'),
            'total_return': Decimal('0'),
            'maximum_drawdown': Decimal('0'),
            'annualized_volatility': Decimal('0'),
            'total_fees': Decimal('0'),
            'executed_order_count': 0,
            'trades': [],
            'equity_curve': [{
                'date': '2026-01-05',
                'drawdown': '0.000000',
                'market_regime': 'BULL',
            }],
        }

        result = evaluate_trend_following(
            security=security,
            benchmark=benchmark,
            start_date=bar.date,
            end_date=bar.date + timedelta(days=1),
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal('1'),
        )

        self.assertEqual(result['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(result['strategy_parameters']['adapter'], 'existing_core_only')
        self.assertFalse(simulate.call_args.kwargs['enable_swing'])


class StrategyEvaluationApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='strategy-evaluation-user',
            password='password123',
        )
        self.client.force_authenticate(self.user)
        self.security = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )
        self.benchmark = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSE Arca',
            mic_code='ARCX',
        )

    @patch('backtest.views.evaluate_selected_strategy')
    def test_api_resolves_server_inputs_and_returns_unified_payload(self, evaluate):
        evaluate.return_value = {
            **completed_evaluation(STRATEGY_TREND_FOLLOWING),
            'symbol': 'AAPL',
            'strategy_selection_available': True,
            'market_regime': REGIME_BULLISH,
            'regime_confidence': 'medium',
            'selected_strategy': STRATEGY_TREND_FOLLOWING,
            'strategy_mode': 'active',
            'execution_mode': 'long_only',
            'allow_new_long': True,
            'risk_off': False,
            'selection_confidence': 'medium',
            'reason': ['Trend Following is selected.'],
            'strategy_parameters': {'strategy_id': STRATEGY_TREND_FOLLOWING},
            'security': {'symbol': 'AAPL'},
            'benchmark': {'symbol': 'SPY'},
            'data_source': {'source': 'database_cache'},
        }

        response = self.client.post(reverse('strategy-evaluation'), {'symbol': 'aapl'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(response.data['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)
        expected_fields = {
            'symbol', 'market_regime', 'regime_confidence', 'selected_strategy',
            'strategy_mode', 'execution_mode', 'allow_new_long', 'risk_off',
            'selection_confidence', 'reason', 'evaluation_available',
            'evaluation_status', 'evaluation_strategy', 'initial_capital',
            'final_equity', 'total_return', 'maximum_drawdown',
            'annualized_volatility', 'total_fees', 'executed_order_count',
            'equity_curve', 'drawdown_curve', 'trades', 'strategy_parameters',
            'security', 'benchmark', 'data_source',
        }
        self.assertTrue(expected_fields.issubset(response.data))
        evaluate.assert_called_once()
        kwargs = evaluate.call_args.kwargs
        self.assertEqual(kwargs['security'], self.security)
        self.assertEqual(kwargs['benchmark'], self.benchmark)
        self.assertEqual(kwargs['initial_capital'], Decimal('10000'))
        self.assertEqual(kwargs['transaction_fee'], Decimal('1.00'))

    @patch('backtest.views.evaluate_selected_strategy')
    def test_missing_or_unknown_symbol_returns_400_without_evaluation(self, evaluate):
        for payload in ({}, {'symbol': 'UNKNOWN'}):
            with self.subTest(payload=payload):
                response = self.client.post(reverse('strategy-evaluation'), payload, format='json')
                self.assertEqual(response.status_code, 400)
        evaluate.assert_not_called()

    @patch('backtest.views.evaluate_selected_strategy')
    def test_client_cannot_supply_selected_strategy(self, evaluate):
        response = self.client.post(
            reverse('strategy-evaluation'),
            {'symbol': 'AAPL', 'selected_strategy': STRATEGY_MEAN_REVERSION},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('selected_strategy', response.data)
        evaluate.assert_not_called()

    @patch('backtest.views.evaluate_selected_strategy')
    def test_provider_errors_map_to_429_and_503(self, evaluate):
        for error, expected_status in (
            (MarketRegimeDataRateLimited('rate limited'), 429),
            (MarketRegimeDataUnavailable('provider unavailable'), 503),
            (BacktestMarketDataRateLimited('backtest rate limited', {'symbol': 'AAPL'}), 429),
            (BacktestMarketDataUnavailable('backtest unavailable', {'symbol': 'AAPL'}), 503),
        ):
            with self.subTest(expected_status=expected_status):
                evaluate.side_effect = error
                response = self.client.post(
                    reverse('strategy-evaluation'),
                    {'symbol': 'AAPL'},
                    format='json',
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data['detail'], str(error))

    @patch('backtest.views.evaluate_selected_strategy')
    def test_business_unavailable_payload_remains_http_200(self, evaluate):
        evaluate.return_value = {
            'symbol': 'AAPL',
            'strategy_selection_available': False,
            'selected_strategy': None,
            'evaluation_available': False,
            'evaluation_status': EVALUATION_STATUS_UNAVAILABLE,
            'evaluation_unavailable_reason': 'market_regime_unavailable',
            'trades': [],
        }

        response = self.client.post(
            reverse('strategy-evaluation'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['evaluation_available'])
        self.assertEqual(response.data['trades'], [])

    @patch('backtest.views.evaluate_selected_strategy')
    @patch('backtest.views.run_market_regime_core_swing_backtest', return_value={})
    def test_existing_backtest_endpoint_still_uses_legacy_hybrid_runner(
        self,
        legacy_runner,
        evaluate_selected,
    ):
        response = self.client.post(reverse('backtest-run'), {
            'symbol': 'AAPL',
            'benchmark': 'SPY',
            'start_date': '2025-08-14',
            'end_date': '2026-08-14',
            'initial_capital': '10000',
            'transaction_fee': '1',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        legacy_runner.assert_called_once()
        evaluate_selected.assert_not_called()
        self.assertIn('security_resolution', response.data)
