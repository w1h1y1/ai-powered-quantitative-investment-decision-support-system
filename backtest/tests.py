from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security, SecurityDailyPrice
from market.services import MarketDataRateLimited
from market.twelve_data import TwelveDataError, TwelveDataRateLimitError

from .services import (
    DailyBacktestBar,
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_NEUTRAL,
    StrategyParameters,
    TREND_BEAR,
    TREND_BULL,
    TREND_REVERSAL_SETUP,
    TREND_STRONG_BULL,
    TREND_WEAK_BULL,
    calculate_atr,
    calculate_bollinger_upper,
    calculate_exponential_moving_average,
    calculate_market_regimes,
    calculate_macd,
    calculate_required_warmup_trading_days,
    calculate_rsi,
    calculate_simple_moving_average,
    calculate_trend_states,
    calculate_warmup_calendar_days,
    calculate_warmup_start_date,
    build_indicator_inputs,
    simulate_layered_strategy,
)


class LayeredStrategyEngineTests(SimpleTestCase):
    def make_bars(self, count=7, closes=None, opens=None):
        closes = closes or [Decimal('120')] * count
        opens = opens or [Decimal('100')] * count
        return tuple(
            DailyBacktestBar(
                date=date(2026, 1, 1) + timedelta(days=index),
                open=Decimal(opens[index]),
                high=max(Decimal(opens[index]), Decimal(closes[index])) + Decimal('1'),
                low=min(Decimal(opens[index]), Decimal(closes[index])) - Decimal('1'),
                close=Decimal(closes[index]),
            )
            for index in range(count)
        )

    def make_indicators(self, count, regimes=None, rsi=None, ma20=None, ma60=None, trend_states=None, macd_histogram=None):
        swing_average = tuple(Decimal('105') for _ in range(count))
        histogram = tuple(macd_histogram or [Decimal('1')] * count)
        return {
            'ma10': swing_average,
            'ema10': swing_average,
            'swing_average': swing_average,
            'ma20': tuple(ma20 or [Decimal('110')] * count),
            'ma60': tuple(ma60 or [Decimal('100') + Decimal(index) for index in range(count)]),
            'rsi14': tuple(rsi or [Decimal('50')] * count),
            'atr14': tuple(Decimal('2') for _ in range(count)),
            'macd': tuple(Decimal('1') for _ in range(count)),
            'macd_signal': tuple(Decimal('0') for _ in range(count)),
            'macd_histogram': histogram,
            'bollinger_upper': tuple(Decimal('999') for _ in range(count)),
            'market_regime': tuple(regimes or [REGIME_NEUTRAL] * count),
            'trend_state': tuple(trend_states or [TREND_BULL] * count),
            'trend_bear_score': tuple(0 for _ in range(count)),
            'trend_reversal_score': tuple(0 for _ in range(count)),
        }

    def run_engine(self, *, bars=None, indicators=None, enable_swing=True, fee='1', parameters=None):
        bars = bars or self.make_bars()
        indicators = indicators or self.make_indicators(len(bars))
        return simulate_layered_strategy(
            bars=bars,
            indicators=indicators,
            start_date=bars[0].date,
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal(fee),
            parameters=parameters or StrategyParameters(),
            enable_swing=enable_swing,
        )

    def test_bear_market_does_not_open_core(self):
        bars = self.make_bars()
        indicators = self.make_indicators(len(bars), regimes=[REGIME_BEAR] * len(bars))

        result = self.run_engine(bars=bars, indicators=indicators)

        self.assertEqual(result['trades'], [])
        self.assertEqual(result['core_entry_count'], 0)

    def test_warmup_window_uses_largest_requested_indicator_period(self):
        default_parameters = StrategyParameters()
        long_parameters = StrategyParameters(core_slow_ma=300, swing_rsi_lookback=350)

        self.assertEqual(calculate_required_warmup_trading_days(default_parameters), 220)
        self.assertEqual(calculate_required_warmup_trading_days(long_parameters), 370)
        self.assertEqual(calculate_warmup_calendar_days(220), 349)
        self.assertEqual(
            calculate_warmup_start_date(date(2025, 7, 1), 220),
            date(2024, 7, 17),
        )

    def test_bull_or_neutral_trend_opens_core_on_next_open(self):
        bars = self.make_bars(opens=[100, 101, 123, 100, 100, 100, 100])
        indicators = self.make_indicators(
            len(bars),
            regimes=[REGIME_BULL, REGIME_NEUTRAL, REGIME_NEUTRAL, REGIME_NEUTRAL, REGIME_NEUTRAL, REGIME_NEUTRAL, REGIME_NEUTRAL],
        )

        result = self.run_engine(bars=bars, indicators=indicators)

        core_buy = result['trades'][0]
        self.assertEqual(core_buy['position_layer'], 'CORE')
        self.assertEqual(core_buy['reason'], 'CORE_ENTRY_BULL')
        self.assertEqual(core_buy['signal_date'], bars[1].date.isoformat())
        self.assertEqual(core_buy['execution_date'], bars[2].date.isoformat())
        self.assertEqual(core_buy['execution_price'], '123.000000')

    def test_core_quantity_uses_atr_risk_not_fixed_half(self):
        bars = self.make_bars()
        result = self.run_engine(bars=bars)

        core_buy = result['trades'][0]

        self.assertEqual(core_buy['quantity'], '40.00000000')
        self.assertNotEqual(Decimal(core_buy['quantity']) * Decimal(core_buy['execution_price']), Decimal('5000'))

    def test_profitable_core_pullback_does_not_trigger_atr_stop(self):
        bars = self.make_bars(
            closes=[Decimal('120'), Decimal('120'), Decimal('120'), Decimal('110'), Decimal('110'), Decimal('110'), Decimal('110')],
        )

        result = self.run_engine(bars=bars, enable_swing=False)
        core_sells = [
            trade
            for trade in result['trades']
            if trade['position_layer'] == 'CORE' and trade['type'] == 'SELL'
        ]

        self.assertEqual(core_sells, [])
        self.assertGreater(Decimal(result['equity_curve'][-1]['core_quantity']), Decimal('0'))

    def test_atr_risk_reduces_losing_core_without_full_exit(self):
        bars = self.make_bars(
            closes=[Decimal('120'), Decimal('120'), Decimal('94'), Decimal('94'), Decimal('94'), Decimal('94'), Decimal('94')],
            opens=[Decimal('100'), Decimal('100'), Decimal('100'), Decimal('94'), Decimal('94'), Decimal('94'), Decimal('94')],
        )

        result = self.run_engine(bars=bars, enable_swing=False)
        core_sell = next(
            trade
            for trade in result['trades']
            if trade['position_layer'] == 'CORE' and trade['type'] == 'SELL'
        )

        self.assertEqual(core_sell['reason'], 'CORE_REDUCE_ATR_RISK')
        self.assertLess(Decimal(core_sell['realized_profit_loss']), Decimal('0'))
        self.assertGreater(Decimal(core_sell['core_quantity_after']), Decimal('0'))
        self.assertEqual(result['core_reduce_count'], 1)
        self.assertEqual(result['core_full_exit_count'], 0)

    def test_confirmed_bear_full_exit_does_not_depend_on_current_profit(self):
        bars = self.make_bars(
            count=8,
            closes=[120, 120, 130, 140, 150, 150, 150, 150],
            opens=[100, 100, 100, 140, 150, 150, 150, 150],
        )
        indicators = self.make_indicators(
            len(bars),
            trend_states=[
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_BEAR,
                TREND_BEAR, TREND_BEAR, TREND_BEAR, TREND_BEAR,
            ],
        )

        result = self.run_engine(bars=bars, indicators=indicators, enable_swing=False)
        full_exit = next(trade for trade in result['trades'] if trade['type'] == 'SELL')

        self.assertEqual(full_exit['reason'], 'CORE_FULL_EXIT_BEAR_TREND')
        self.assertGreater(Decimal(full_exit['realized_profit_loss']), Decimal('0'))
        self.assertEqual(full_exit['core_quantity_after'], '0.00000000')
        self.assertEqual(result['core_full_exit_count'], 1)

    def test_weak_bull_reduces_core_by_configured_fraction_once(self):
        bars = self.make_bars(count=8)
        indicators = self.make_indicators(
            len(bars),
            trend_states=[
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_WEAK_BULL,
                TREND_WEAK_BULL, TREND_WEAK_BULL, TREND_WEAK_BULL, TREND_WEAK_BULL,
            ],
        )

        result = self.run_engine(
            bars=bars,
            indicators=indicators,
            enable_swing=False,
            parameters=StrategyParameters(core_reduce_fraction=Decimal('0.25')),
        )
        reduce_trade = next(trade for trade in result['trades'] if trade['reason'] == 'CORE_REDUCE_WEAK_TREND')

        self.assertEqual(Decimal(reduce_trade['quantity']), Decimal('10'))
        self.assertEqual(Decimal(reduce_trade['core_quantity_after']), Decimal('30'))
        self.assertEqual(result['core_reduce_count'], 1)
        self.assertEqual(result['core_full_exit_count'], 0)

    def test_strong_bull_transition_adds_core_without_replacing_existing_units(self):
        bars = self.make_bars(count=8)
        indicators = self.make_indicators(
            len(bars),
            trend_states=[
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_STRONG_BULL,
                TREND_STRONG_BULL, TREND_STRONG_BULL, TREND_STRONG_BULL, TREND_STRONG_BULL,
            ],
        )

        result = self.run_engine(bars=bars, indicators=indicators, enable_swing=False)
        core_buys = [trade for trade in result['trades'] if trade['position_layer'] == 'CORE' and trade['type'] == 'BUY']

        self.assertEqual([trade['reason'] for trade in core_buys], ['CORE_ENTRY_BULL', 'CORE_ADD_STRONG_BULL'])
        self.assertEqual(result['core_entry_count'], 1)
        self.assertEqual(result['core_add_count'], 1)
        self.assertGreater(Decimal(core_buys[1]['core_quantity_after']), Decimal(core_buys[0]['core_quantity_after']))

    def test_full_exit_blocks_same_bar_reentry_but_next_bar_can_confirm(self):
        bars = self.make_bars(count=9)
        indicators = self.make_indicators(
            len(bars),
            trend_states=[
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_BEAR,
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_BULL, TREND_BULL,
            ],
        )

        result = self.run_engine(bars=bars, indicators=indicators, enable_swing=False)
        full_exit = next(trade for trade in result['trades'] if trade['reason'] == 'CORE_FULL_EXIT_BEAR_TREND')
        reentry = next(trade for trade in result['trades'] if trade['reason'] == 'CORE_REENTRY_BULL')

        self.assertNotEqual(reentry['signal_date'], full_exit['execution_date'])
        self.assertEqual(reentry['signal_date'], bars[5].date.isoformat())
        self.assertEqual(reentry['execution_date'], bars[6].date.isoformat())
        self.assertEqual(result['full_exit_to_next_buy_minimum_gap'], 2)

    def test_reversal_setup_requires_bull_confirmation_before_reentry(self):
        bars = self.make_bars(count=10)
        indicators = self.make_indicators(
            len(bars),
            trend_states=[
                TREND_BULL, TREND_BULL, TREND_BULL, TREND_BEAR,
                TREND_REVERSAL_SETUP, TREND_REVERSAL_SETUP, TREND_BULL,
                TREND_BULL, TREND_BULL, TREND_BULL,
            ],
            macd_histogram=[Decimal(index) for index in range(10)],
        )

        result = self.run_engine(bars=bars, indicators=indicators, enable_swing=False)
        reentry = next(trade for trade in result['trades'] if trade['reason'] == 'CORE_REENTRY_REVERSAL')

        self.assertEqual(reentry['signal_date'], bars[6].date.isoformat())
        self.assertEqual(reentry['execution_date'], bars[7].date.isoformat())
        self.assertEqual(result['core_strategy_diagnostics']['reentry_reasons'], {'CORE_REENTRY_REVERSAL': 1})

    def test_trend_state_classifier_uses_multi_indicator_confirmation(self):
        def classify(*, closes, ema10, ma20, ma60, rsi, atr, macd, signal, histogram):
            bars = self.make_bars(count=2, closes=closes, opens=closes)
            states, _, _ = calculate_trend_states(
                bars,
                ema10=tuple(ema10),
                ma20=tuple(ma20),
                ma60=tuple(ma60),
                rsi=tuple(rsi),
                atr=tuple(atr),
                macd=tuple(macd),
                macd_signal=tuple(signal),
                macd_histogram=tuple(histogram),
            )
            return states[-1]

        self.assertEqual(classify(
            closes=[110, 120], ema10=[105, 115], ma20=[100, 110], ma60=[90, 95],
            rsi=[55, 60], atr=[3, 3], macd=[1, 2], signal=[0, 1], histogram=[1, 1],
        ), TREND_STRONG_BULL)
        self.assertEqual(classify(
            closes=[108, 110], ema10=[103, 104], ma20=[100, 101], ma60=[90, 91],
            rsi=[52, 54], atr=[3, 3], macd=[1, 1], signal=[1, 1], histogram=[0, 0],
        ), TREND_BULL)
        self.assertEqual(classify(
            closes=[102, 100], ema10=[104, 105], ma20=[101, 102], ma60=[99, 100],
            rsi=[50, 48], atr=[3, 3], macd=[1, 0], signal=[0, 0], histogram=[1, 0],
        ), TREND_WEAK_BULL)
        self.assertEqual(classify(
            closes=[90, 80], ema10=[100, 90], ma20=[105, 100], ma60=[110, 108],
            rsi=[40, 30], atr=[3, 3], macd=[-1, -2], signal=[0, 0], histogram=[-1, -2],
        ), TREND_BEAR)
        self.assertEqual(classify(
            closes=[90, 99], ema10=[95, 98], ma20=[105, 101], ma60=[110, 108],
            rsi=[30, 40], atr=[3, 3], macd=[-2, -1], signal=[0, 0], histogram=[-2, -1],
        ), TREND_REVERSAL_SETUP)

    def test_core_risk_atr_and_exposure_parameters_change_executed_quantity(self):
        bars = self.make_bars()
        baseline = self.run_engine(bars=bars)
        lower_risk = self.run_engine(
            bars=bars,
            parameters=StrategyParameters(core_risk_percentage=Decimal('0.005')),
        )
        wider_atr = self.run_engine(
            bars=bars,
            parameters=StrategyParameters(core_atr_multiplier=Decimal('4.0')),
        )
        capped_exposure = self.run_engine(
            bars=bars,
            parameters=StrategyParameters(max_core_exposure=Decimal('0.20')),
        )

        baseline_quantity = Decimal(baseline['trades'][0]['quantity'])
        self.assertEqual(baseline_quantity, Decimal('40'))
        self.assertEqual(Decimal(lower_risk['trades'][0]['quantity']), Decimal('10'))
        self.assertEqual(Decimal(wider_atr['trades'][0]['quantity']), Decimal('25'))
        self.assertEqual(Decimal(capped_exposure['trades'][0]['quantity']), Decimal('20'))
        self.assertLessEqual(
            Decimal(capped_exposure['trades'][0]['quantity']) * Decimal(capped_exposure['trades'][0]['execution_price']),
            Decimal('10000') * Decimal('0.20'),
        )

    def test_swing_risk_and_atr_parameters_change_only_swing_sizing(self):
        bars = self.make_bars(opens=[100, 100, 100, 110, 110, 110, 110])
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50')],
        )
        baseline = self.run_engine(bars=bars, indicators=indicators)
        lower_risk = self.run_engine(
            bars=bars,
            indicators=indicators,
            parameters=StrategyParameters(swing_risk_percentage=Decimal('0.005')),
        )
        wider_atr = self.run_engine(
            bars=bars,
            indicators=indicators,
            parameters=StrategyParameters(swing_atr_multiplier=Decimal('3.0')),
        )

        def quantities(result):
            core = next(Decimal(trade['quantity']) for trade in result['trades'] if trade['position_layer'] == 'CORE')
            swing = next(Decimal(trade['quantity']) for trade in result['trades'] if trade['position_layer'] == 'SWING')
            return core, swing

        baseline_core, baseline_swing = quantities(baseline)
        lower_core, lower_swing = quantities(lower_risk)
        wider_core, wider_swing = quantities(wider_atr)
        self.assertEqual(baseline_core, lower_core)
        self.assertEqual(baseline_core, wider_core)
        self.assertLess(abs(lower_swing - baseline_swing / Decimal('2')), Decimal('0.00000001'))
        self.assertLess(abs(wider_swing - baseline_swing / Decimal('2')), Decimal('0.00000001'))

    def test_fast_and_slow_periods_rebuild_moving_average_series(self):
        bars = self.make_bars(
            count=80,
            closes=[Decimal('100') + Decimal(index) / Decimal('2') + Decimal(index % 7) for index in range(80)],
            opens=[Decimal('100') + Decimal(index) / Decimal('2') for index in range(80)],
        )
        baseline = build_indicator_inputs(bars, bars, StrategyParameters())
        shorter = build_indicator_inputs(bars, bars, StrategyParameters(core_fast_ma=5, core_slow_ma=10))

        self.assertIsNone(baseline['ma20'][18])
        self.assertIsNotNone(baseline['ma20'][19])
        self.assertIsNone(baseline['ma60'][58])
        self.assertIsNotNone(baseline['ma60'][59])
        self.assertIsNone(shorter['ma20'][3])
        self.assertIsNotNone(shorter['ma20'][4])
        self.assertIsNone(shorter['ma60'][8])
        self.assertIsNotNone(shorter['ma60'][9])
        self.assertNotEqual(baseline['ma20'][-1], shorter['ma20'][-1])
        self.assertNotEqual(baseline['ma60'][-1], shorter['ma60'][-1])

    def test_core_and_swing_costs_are_independent(self):
        bars = self.make_bars(opens=[100, 100, 100, 110, 110, 110, 110])
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        point_after_swing_buy = result['equity_curve'][3]

        self.assertGreater(Decimal(point_after_swing_buy['core_quantity']), Decimal('0'))
        self.assertGreater(Decimal(point_after_swing_buy['swing_quantity']), Decimal('0'))
        self.assertNotEqual(point_after_swing_buy['core_average_cost'], point_after_swing_buy['swing_average_cost'])

    def test_swing_exit_does_not_reduce_core_and_counts_one_cycle(self):
        bars = self.make_bars(opens=[100, 100, 100, 110, 120, 120, 120])
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('65'), Decimal('65'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_sell = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'SELL')

        self.assertEqual(swing_sell['reason'], 'SWING_EXIT_REBOUND_TARGET')
        self.assertEqual(swing_sell['swing_quantity_after'], '0.00000000')
        self.assertGreater(Decimal(swing_sell['core_quantity_after']), Decimal('0'))
        self.assertEqual(result['swing_cycle_count'], 1)
        self.assertEqual(result['profitable_swing_cycle_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_entry_signal_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_exit_signal_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_entry_order_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_entry_execution_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_entry_execution_blocked_count'], 0)
        self.assertEqual(result['swing_signal_diagnostics']['swing_exit_order_count'], 1)
        self.assertEqual(result['swing_signal_diagnostics']['swing_exit_execution_count'], 1)
        self.assertEqual(result['swing_holding_period_diagnostics']['holding_2_bars_count'], 1)
        self.assertEqual(
            result['swing_holding_period_diagnostics']['round_trips'][0]['exit_reason'],
            'SWING_EXIT_REBOUND_TARGET',
        )

    def test_core_exit_forces_swing_exit_without_mixing_layers(self):
        bars = self.make_bars(opens=[100, 100, 100, 110, 120, 120, 120])
        ma20 = [Decimal('110'), Decimal('110'), Decimal('110'), Decimal('90'), Decimal('90'), Decimal('90'), Decimal('90')]
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50')],
            ma20=ma20,
            trend_states=[TREND_BULL, TREND_BULL, TREND_BULL, TREND_BEAR, TREND_BEAR, TREND_BEAR, TREND_BEAR],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        sells = [trade for trade in result['trades'] if trade['type'] == 'SELL']

        self.assertEqual([trade['position_layer'] for trade in sells[:2]], ['SWING', 'CORE'])
        self.assertEqual(sells[0]['reason'], 'SWING_EXIT_TREND_FAILURE')
        self.assertEqual(sells[1]['reason'], 'CORE_FULL_EXIT_BEAR_TREND')
        swing_buy = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY')
        self.assertEqual(sells[0]['signal_date'], swing_buy['execution_date'])
        self.assertEqual(sells[1]['core_quantity_after'], '0.00000000')
        self.assertEqual(sells[1]['swing_quantity_after'], '0.00000000')

    def test_persistent_conditions_do_not_repeat_swing_entry(self):
        bars = self.make_bars(count=9)
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('35'), Decimal('51'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_buys = [trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY']

        self.assertEqual(len(swing_buys), 1)

    def test_normal_swing_exit_is_not_generated_on_entry_execution_bar(self):
        bars = self.make_bars(
            count=8,
            opens=[100, 100, 100, 110, 120, 120, 120, 120],
            closes=[120, 120, 120, 120, 130, 130, 130, 130],
        )
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('65'), Decimal('65'), Decimal('65'), Decimal('65'), Decimal('65')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_buy = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY')
        swing_sell = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'SELL')

        self.assertNotEqual(swing_sell['signal_date'], swing_buy['execution_date'])
        self.assertEqual(swing_sell['reason'], 'SWING_EXIT_REBOUND_TARGET')
        self.assertEqual(swing_sell['signal_date'], bars[4].date.isoformat())
        self.assertEqual(swing_sell['execution_date'], bars[5].date.isoformat())

    def test_swing_position_holds_and_exposure_remains_continuous_without_exit_signal(self):
        bars = self.make_bars(count=8, opens=[100] * 8, closes=[120] * 8)
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50')],
            macd_histogram=[Decimal(index) for index in range(8)],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_trades = [trade for trade in result['trades'] if trade['position_layer'] == 'SWING']
        buy_index = next(
            index
            for index, point in enumerate(result['equity_curve'])
            if Decimal(point['swing_quantity']) > Decimal('0')
        )

        self.assertEqual([trade['type'] for trade in swing_trades], ['BUY'])
        self.assertTrue(all(
            Decimal(point['swing_quantity']) > Decimal('0')
            and Decimal(point['swing_exposure']) > Decimal('0')
            for point in result['equity_curve'][buy_index:]
        ))

    def test_explicit_rebound_failure_can_exit_on_entry_execution_bar(self):
        bars = self.make_bars(
            count=8,
            opens=[100] * 8,
            closes=[120, 120, 120, 104, 104, 104, 104, 104],
        )
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('40'), Decimal('40'), Decimal('40'), Decimal('40'), Decimal('40')],
            ma20=[Decimal('110')] * 8,
            macd_histogram=[Decimal('1'), Decimal('1'), Decimal('1'), Decimal('-1'), Decimal('-1'), Decimal('-1'), Decimal('-1'), Decimal('-1')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_buy = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY')
        swing_sell = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'SELL')

        self.assertEqual(swing_sell['signal_date'], swing_buy['execution_date'])
        self.assertEqual(swing_sell['reason'], 'SWING_EXIT_REBOUND_FAILURE')

    def test_same_core_position_allows_repeated_swing_cycles_without_waiting_period(self):
        bars = self.make_bars(count=11)
        indicators = self.make_indicators(
            len(bars),
            rsi=[
                Decimal('50'), Decimal('35'), Decimal('51'), Decimal('60'), Decimal('60'),
                Decimal('35'), Decimal('51'), Decimal('60'), Decimal('60'), Decimal('50'),
                Decimal('50'),
            ],
        )

        result = self.run_engine(bars=bars, indicators=indicators)

        swing_trades = [trade for trade in result['trades'] if trade['position_layer'] == 'SWING']
        self.assertEqual([trade['type'] for trade in swing_trades], ['BUY', 'SELL', 'BUY', 'SELL'])
        self.assertEqual(result['swing_cycle_count'], 2)
        self.assertEqual(result['swing_entry_count'], 2)
        self.assertEqual(result['swing_exit_count'], 2)
        self.assertEqual(result['average_days_per_swing_cycle'], Decimal('2'))
        self.assertTrue(all(Decimal(trade['core_quantity_after']) > Decimal('0') for trade in swing_trades))
        self.assertEqual(result['swing_signal_diagnostics']['swing_entry_signal_count'], 2)
        self.assertEqual(result['swing_signal_diagnostics']['swing_exit_signal_count'], 2)
        self.assertEqual(swing_trades[2]['signal_date'], bars[6].date.isoformat())

    def test_completed_cycle_cannot_reuse_an_old_pullback_setup(self):
        bars = self.make_bars(count=9)
        indicators = self.make_indicators(
            len(bars),
            rsi=[
                Decimal('50'), Decimal('35'), Decimal('51'), Decimal('60'), Decimal('60'),
                Decimal('52'), Decimal('53'), Decimal('54'), Decimal('55'),
            ],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        swing_buys = [
            trade
            for trade in result['trades']
            if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY'
        ]

        self.assertEqual(len(swing_buys), 1)
        self.assertEqual(result['swing_cycle_count'], 1)

    def test_swing_diagnostics_explain_why_entries_are_blocked(self):
        bars = self.make_bars(count=8)
        indicators = self.make_indicators(
            len(bars),
            regimes=[REGIME_BEAR] * len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        diagnostics = result['swing_signal_diagnostics']

        self.assertEqual(diagnostics['eligible_core_days'], 0)
        self.assertGreater(diagnostics['market_bear_days'], 0)
        self.assertGreater(diagnostics['rsi_pullback_detected_days'], 0)
        self.assertEqual(diagnostics['rsi_upward_cross_days'], 1)
        self.assertEqual(diagnostics['swing_entry_signal_count'], 0)
        self.assertEqual(diagnostics['primary_block_reason_counts']['NO_CORE_POSITION'], len(bars) - 1)

    def test_configurable_swing_rsi_levels_control_entry_and_exit(self):
        bars = self.make_bars(count=8)
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('55'), Decimal('45'), Decimal('51'), Decimal('58'), Decimal('58'), Decimal('55'), Decimal('55'), Decimal('55')],
        )
        parameters = StrategyParameters(
            swing_rsi_entry_level=Decimal('50'),
            swing_rsi_exit_level=Decimal('58'),
        )

        result = self.run_engine(bars=bars, indicators=indicators, parameters=parameters)
        swing_trades = [trade for trade in result['trades'] if trade['position_layer'] == 'SWING']

        self.assertEqual([trade['type'] for trade in swing_trades], ['BUY', 'SELL'])
        self.assertEqual(swing_trades[0]['signal_date'], bars[2].date.isoformat())
        self.assertEqual(swing_trades[1]['signal_date'], bars[4].date.isoformat())

    def test_ema10_uses_only_current_and_prior_closes(self):
        bars = self.make_bars(
            count=20,
            closes=[Decimal('100') + Decimal(index) for index in range(20)],
        )
        prefix = bars[:15]

        full = calculate_exponential_moving_average(bars, 10)
        prefix_values = calculate_exponential_moving_average(prefix, 10)

        self.assertTrue(all(value is None for value in full[:9]))
        self.assertIsNotNone(full[9])
        self.assertEqual(full[:15], prefix_values)

    def test_fees_affect_layer_profit_and_total_metrics(self):
        bars = self.make_bars(opens=[100, 100, 100, 110, 120, 120, 120])
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('65'), Decimal('65'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators, fee='1')
        swing_buy = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'BUY')
        swing_sell = next(trade for trade in result['trades'] if trade['position_layer'] == 'SWING' and trade['type'] == 'SELL')
        expected_profit = (
            Decimal(swing_sell['quantity']) * Decimal('120')
            - Decimal('1')
            - (Decimal(swing_buy['quantity']) * Decimal(swing_buy['execution_price']) + Decimal('1'))
        )

        self.assertEqual(Decimal(swing_sell['realized_profit_loss']), expected_profit.quantize(Decimal('0.000001')))
        self.assertEqual(result['swing_fees'], Decimal('2'))
        self.assertEqual(result['total_fees'], Decimal('3'))

    def test_every_order_executes_on_next_trading_day_open(self):
        bars = self.make_bars(opens=[100, 101, 123, 111, 119, 118, 117])
        indicators = self.make_indicators(
            len(bars),
            rsi=[Decimal('50'), Decimal('35'), Decimal('51'), Decimal('65'), Decimal('50'), Decimal('50'), Decimal('50')],
        )

        result = self.run_engine(bars=bars, indicators=indicators)
        date_to_open = {bar.date.isoformat(): bar.open for bar in bars}

        for trade in result['trades']:
            self.assertLess(trade['signal_date'], trade['execution_date'])
            self.assertEqual(Decimal(trade['execution_price']), date_to_open[trade['execution_date']])

    def test_indicator_calculations_do_not_change_when_future_bars_are_added(self):
        prefix = self.make_bars(
            count=220,
            closes=[Decimal('100') + Decimal(index) / Decimal('10') for index in range(220)],
        )
        future = tuple(
            DailyBacktestBar(
                date=prefix[-1].date + timedelta(days=index + 1),
                open=Decimal('500'),
                high=Decimal('510'),
                low=Decimal('490'),
                close=Decimal('500') + Decimal(index),
            )
            for index in range(10)
        )
        extended = prefix + future

        self.assertEqual(calculate_simple_moving_average(prefix, 60), calculate_simple_moving_average(extended, 60)[:220])
        self.assertEqual(calculate_exponential_moving_average(prefix, 10), calculate_exponential_moving_average(extended, 10)[:220])
        self.assertEqual(calculate_rsi(prefix), calculate_rsi(extended)[:220])
        self.assertEqual(calculate_atr(prefix), calculate_atr(extended)[:220])
        self.assertEqual(calculate_bollinger_upper(prefix), calculate_bollinger_upper(extended)[:220])
        self.assertEqual(calculate_market_regimes(prefix, prefix), calculate_market_regimes(extended, extended)[:220])


class MarketRegimeBacktestApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='hybrid-user', password='pass')
        self.other_user = get_user_model().objects.create_user(username='hybrid-other', password='pass')
        self.security = Security.objects.create(
            symbol='TEST',
            name='Test Security',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        self.benchmark = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NYSE Arca',
            mic_code='ARCX',
            country='United States',
            currency='USD',
        )
        self.url = reverse('backtest-run')
        self.start_date = date(2026, 1, 1)
        self.end_date = date(2026, 1, 10)

    def create_price_history(self, security, *, bearish=False):
        first_date = self.start_date - timedelta(days=400)
        count = (self.end_date - first_date).days + 1
        for index in range(count):
            trend = Decimal(index) / Decimal('10')
            close = Decimal('300') - trend if bearish else Decimal('100') + trend
            SecurityDailyPrice.objects.create(
                security=security,
                date=first_date + timedelta(days=index),
                open=close,
                high=close + Decimal('1'),
                low=close - Decimal('1'),
                close=close,
                volume=1000000 + index,
            )

    def replace_with_requested_history(self, security, first_date, end_date):
        SecurityDailyPrice.objects.filter(security=security).delete()
        symbol_offset = Decimal(security.id)
        SecurityDailyPrice.objects.bulk_create([
            SecurityDailyPrice(
                security=security,
                date=first_date + timedelta(days=index),
                open=Decimal('100') + symbol_offset + (Decimal(index) / Decimal('10')),
                high=Decimal('101') + symbol_offset + (Decimal(index) / Decimal('10')),
                low=Decimal('99') + symbol_offset + (Decimal(index) / Decimal('10')),
                close=Decimal('100') + symbol_offset + (Decimal(index) / Decimal('10')),
                volume=1000000 + index,
            )
            for index in range((end_date - first_date).days + 1)
        ])

    def payload(self, **overrides):
        data = {
            'security': self.security.id,
            'benchmark': 'SPY',
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'initial_capital': '10000.00',
            'transaction_fee': '1.00',
        }
        data.update(overrides)
        return data

    def run_backtest(self, **overrides):
        self.client.force_authenticate(self.user)
        return self.client.post(self.url, self.payload(**overrides), format='json')

    def remote_security_payload(self):
        payload = self.payload()
        payload.pop('security')
        payload.update({
            'symbol': 'TSLA',
            'security_selection': {
                'id': None,
                'symbol': 'TSLA',
                'name': 'Tesla Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
                'search_query': 'Tesla',
            },
        })
        return payload

    @patch('backtest.views.run_market_regime_core_swing_backtest', side_effect=lambda **_kwargs: {})
    @patch('market.services.search_security_symbols')
    def test_remote_security_is_verified_and_created_only_when_backtest_is_submitted(self, search, run_service):
        search.return_value = {
            'query': 'Tesla',
            'items': [{
                'id': None,
                'symbol': 'TSLA',
                'name': 'Tesla Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
                'is_local': False,
                'source': 'remote',
            }],
            'metadata': {'count': 1},
        }
        self.assertFalse(Security.objects.filter(symbol='TSLA').exists())
        self.client.force_authenticate(self.user)

        first = self.client.post(self.url, self.remote_security_payload(), format='json')
        second = self.client.post(self.url, self.remote_security_payload(), format='json')

        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data['security_resolution']['created'])
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data['security_resolution']['created'])
        self.assertEqual(Security.objects.filter(symbol='TSLA', mic_code='XNAS').count(), 1)
        created_security = Security.objects.get(symbol='TSLA', mic_code='XNAS')
        self.assertEqual(created_security.name, 'Tesla Inc.')
        self.assertEqual(run_service.call_args.kwargs['security'], created_security)

    @patch('backtest.views.run_market_regime_core_swing_backtest', return_value={})
    def test_backtest_api_propagates_asset_and_benchmark_separately(self, run_service):
        response = self.run_backtest()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_service.call_args.kwargs['security'], self.security)
        self.assertEqual(run_service.call_args.kwargs['benchmark'], self.benchmark)
        self.assertNotEqual(run_service.call_args.kwargs['security'], run_service.call_args.kwargs['benchmark'])

    @patch('backtest.views.run_market_regime_core_swing_backtest', return_value={})
    def test_backtest_api_propagates_selected_qqq_benchmark(self, run_service):
        qqq = Security.objects.create(
            symbol='QQQ',
            name='Invesco QQQ ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )

        response = self.run_backtest(benchmark='QQQ')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_service.call_args.kwargs['security'], self.security)
        self.assertEqual(run_service.call_args.kwargs['benchmark'], qqq)
        self.assertEqual(run_service.call_args.kwargs['start_date'], self.start_date)
        self.assertEqual(run_service.call_args.kwargs['end_date'], self.end_date)

    @patch('market.services.search_security_symbols', side_effect=MarketDataRateLimited('limit reached'))
    def test_remote_security_rate_limit_returns_429_without_creating_security(self, _search):
        self.client.force_authenticate(self.user)

        response = self.client.post(self.url, self.remote_security_payload(), format='json')

        self.assertEqual(response.status_code, 429)
        self.assertIn('limit reached', response.data['detail'])
        self.assertFalse(Security.objects.filter(symbol='TSLA').exists())

    def test_real_daily_prices_drive_hybrid_and_all_three_comparisons(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['strategy_parameters']['strategy_id'], 'market-regime-core-swing')
        self.assertEqual(response.data['strategy_parameters']['core_risk_fraction'], '0.020000')
        self.assertEqual(response.data['strategy_parameters']['core_reduce_fraction'], '0.250000')
        self.assertEqual(response.data['strategy_parameters']['swing_risk_fraction'], '0.010000')
        self.assertEqual(response.data['strategy_parameters']['swing_rsi_lookback'], 10)
        self.assertEqual(response.data['strategy_parameters']['swing_rsi_entry_level'], '45.000000')
        self.assertEqual(response.data['strategy_parameters']['swing_rsi_exit_level'], '60.000000')
        self.assertEqual(response.data['strategy_parameters']['swing_atr_multiplier'], '1.500000')
        self.assertNotIn('swing_cooldown_days', response.data['strategy_parameters'])
        self.assertEqual(response.data['strategy_parameters']['swing_trend_average'], 'EMA10')
        self.assertEqual(response.data['strategy_parameters']['swing_average_type'], 'EMA10')
        self.assertIn('swing_entry_count', response.data)
        self.assertIn('swing_exit_count', response.data)
        self.assertIn('average_days_per_swing_cycle', response.data)
        self.assertIn('swing_total_fees', response.data)
        self.assertIn('swing_signal_diagnostics', response.data)
        self.assertIn('swing_holding_period_diagnostics', response.data)
        self.assertIn('round_trips', response.data['swing_holding_period_diagnostics'])
        self.assertIn('primary_block_reason_counts', response.data['swing_signal_diagnostics'])
        for field in ('core_add_count', 'core_reduce_count', 'core_full_exit_count'):
            self.assertIn(field, response.data)
        self.assertIn('trend_state_counts', response.data['core_strategy_diagnostics'])
        self.assertIn('full_exit_reasons', response.data['core_strategy_diagnostics'])
        self.assertEqual(response.data['benchmark']['symbol'], 'SPY')
        self.assertEqual(len(response.data['comparisons']), 3)
        self.assertEqual(
            [item['strategy_id'] for item in response.data['comparisons']],
            ['buy-and-hold', 'core-only', 'core-swing-hybrid'],
        )
        self.assertTrue(all(point['market_regime'] == REGIME_BULL for point in response.data['equity_curve']))
        self.assertEqual(response.data['data_source']['source'], 'database_cache')
        self.assertEqual(response.data['data_source']['benchmark']['source'], 'database_cache')
        self.assertEqual(response.data['data_source']['actual_start_date'], self.start_date.isoformat())
        self.assertEqual(response.data['data_source']['actual_end_date'], self.end_date.isoformat())
        equity_curve = response.data['equity_curve']
        drawdown_curve = response.data['drawdown_curve']
        self.assertEqual(len(equity_curve), len(drawdown_curve))
        self.assertEqual(equity_curve[0]['date'], drawdown_curve[0]['date'])
        self.assertEqual(equity_curve[-1]['date'], self.end_date.isoformat())
        self.assertEqual(drawdown_curve[-1]['date'], self.end_date.isoformat())
        self.assertIn('core_exposure', equity_curve[-1])
        self.assertIn('swing_exposure', equity_curve[-1])
        self.assertIn('total_exposure', equity_curve[-1])
        self.assertEqual(response.data['data_source']['warmup_trading_days'], 220)
        first_point = equity_curve[0]
        self.assertEqual(first_point['date'], self.start_date.isoformat())
        for field in (
            'ma20',
            'ma60',
            'rsi14',
            'atr14',
            'macd',
            'macd_signal',
            'macd_histogram',
            'bollinger_upper',
            'market_regime',
            'trend_state',
        ):
            self.assertIsNotNone(first_point[field])
        self.assertTrue(all(trade['signal_date'] >= self.start_date.isoformat() for trade in response.data['trades']))
        self.assertNotIn('win_rate', response.data)
        self.assertIn('swing_win_rate', response.data)
        self.assertIn('executed_order_count', response.data)
        self.assertIn('total_return', response.data)
        self.assertIn('maximum_drawdown', response.data)
        self.assertIn('annualized_volatility', response.data)

    @patch('backtest.services.fetch_and_cache_daily_prices')
    def test_each_selected_symbol_fills_its_own_warmup_history(self, fetch_prices):
        self.create_price_history(self.benchmark)
        securities = []
        for symbol in ('AAPL', 'MSFT', 'NVDA', 'MU', 'AVGO'):
            security = Security.objects.create(
                symbol=symbol,
                name=f'{symbol} Test',
                asset_type=Security.AssetType.STOCK,
                exchange='NASDAQ',
                mic_code='XNAS',
                country='United States',
                currency='USD',
            )
            securities.append(security)
            self.replace_with_requested_history(security, self.start_date, self.end_date)

        fetched_symbols = []

        def fill_history(security, first_date, end_date, **_kwargs):
            fetched_symbols.append(security.symbol)
            self.replace_with_requested_history(security, first_date, end_date)

        fetch_prices.side_effect = fill_history
        self.client.force_authenticate(self.user)

        for security in securities:
            response = self.client.post(
                self.url,
                self.payload(security=security.id),
                format='json',
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['security']['symbol'], security.symbol)
            self.assertEqual(response.data['benchmark']['symbol'], 'SPY')
            self.assertGreaterEqual(response.data['data_source']['warmup_record_count'], 220)
            self.assertTrue(all(point['date'] >= self.start_date.isoformat() for point in response.data['equity_curve']))

        self.assertEqual(fetched_symbols, ['AAPL', 'MSFT', 'NVDA', 'MU', 'AVGO'])
        self.assertTrue(all(
            call.kwargs.get('require_exact_window') is True
            for call in fetch_prices.call_args_list
        ))

    @patch('backtest.services.fetch_and_cache_daily_prices')
    def test_insufficient_history_error_reports_asset_and_benchmark_coverage(self, fetch_prices):
        self.replace_with_requested_history(self.security, self.start_date, self.end_date)
        self.create_price_history(self.benchmark)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['required_warmup_rows'], 220)
        self.assertEqual(response.data['requested_start_date'], self.start_date.isoformat())
        self.assertEqual(response.data['asset']['symbol'], 'TEST')
        self.assertEqual(response.data['asset']['available_rows'], 0)
        self.assertGreaterEqual(response.data['benchmark']['available_rows'], 220)
        self.assertEqual(response.data['symbol'], 'TEST')
        self.assertEqual(response.data['required_rows'], 220)
        self.assertEqual(response.data['available_rows'], 0)
        self.assertEqual(response.data['requested_warmup_start'], (self.start_date - timedelta(days=349)).isoformat())
        self.assertEqual(response.data['upstream_error'], 'Provider returned insufficient historical rows.')
        self.assertIn('after attempting to fill', response.data['detail'])
        fetch_prices.assert_called_once()

    def test_bear_benchmark_prevents_core_entry_through_api(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark, bearish=True)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['core_entry_count'], 0)
        self.assertEqual(response.data['trades'], [])
        self.assertEqual(
            response.data['signal_message'],
            'No qualifying Core or Swing signals under the selected parameters.',
        )
        self.assertTrue(all(point['market_regime'] == REGIME_BEAR for point in response.data['equity_curve']))

    def test_bull_vs_bear_benchmark_changes_core_decision_path(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark, bearish=False)

        bull_response = self.run_backtest()

        self.assertEqual(bull_response.status_code, 200)
        self.assertGreater(bull_response.data['core_entry_count'], 0)

        SecurityDailyPrice.objects.filter(security=self.benchmark).delete()
        self.create_price_history(self.benchmark, bearish=True)

        bear_response = self.run_backtest()

        self.assertEqual(bear_response.status_code, 200)
        self.assertEqual(bear_response.data['core_entry_count'], 0)
        self.assertGreater(
            bull_response.data['executed_order_count'],
            bear_response.data['executed_order_count'],
        )
        self.assertTrue(all(
            point['market_regime'] == REGIME_BEAR
            for point in bear_response.data['equity_curve']
        ))

    def test_benchmark_dataframes_are_symbol_specific(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark, bearish=False)
        qqq = Security.objects.create(
            symbol='QQQ',
            name='Invesco QQQ ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        self.create_price_history(qqq, bearish=True)

        spy_response = self.run_backtest()
        qqq_response = self.run_backtest(benchmark='QQQ')

        self.assertEqual(spy_response.data['benchmark']['symbol'], 'SPY')
        self.assertEqual(qqq_response.data['benchmark']['symbol'], 'QQQ')
        self.assertEqual(spy_response.data['security']['symbol'], 'TEST')
        self.assertEqual(qqq_response.data['security']['symbol'], 'TEST')
        self.assertNotEqual(
            spy_response.data['equity_curve'],
            qqq_response.data['equity_curve'],
        )
        self.assertNotEqual(
            spy_response.data['core_entry_count'],
            qqq_response.data['core_entry_count'],
        )

    def test_asset_execution_and_pl_use_asset_prices_only(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark, bearish=False)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 200)
        asset_prices = {
            item.date: (item.open, item.close)
            for item in SecurityDailyPrice.objects.filter(security=self.security)
        }
        for trade in response.data['trades']:
            execution_date = date.fromisoformat(trade['execution_date'])
            self.assertEqual(Decimal(trade['execution_price']), asset_prices[execution_date][0])
        for point in response.data['equity_curve']:
            point_date = date.fromisoformat(point['date'])
            self.assertEqual(Decimal(point['close']), asset_prices[point_date][1])

    @patch('backtest.services.fetch_and_cache_daily_prices')
    def test_exact_backtest_window_refetches_when_requested_end_date_is_missing(self, fetch_prices):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)
        SecurityDailyPrice.objects.filter(security=self.security, date=self.end_date).delete()

        def fill_requested_end(security, _first_date, requested_end, **_kwargs):
            SecurityDailyPrice.objects.create(
                security=security,
                date=requested_end,
                open=Decimal('140'),
                high=Decimal('142'),
                low=Decimal('139'),
                close=Decimal('141'),
                volume=1200000,
            )

        fetch_prices.side_effect = fill_requested_end

        response = self.run_backtest()

        self.assertEqual(response.status_code, 200, response.data)
        fetch_prices.assert_called_once()
        self.assertEqual(fetch_prices.call_args.args[0], self.security)
        self.assertEqual(fetch_prices.call_args.args[2], self.end_date)
        self.assertTrue(fetch_prices.call_args.kwargs['require_exact_window'])
        self.assertEqual(response.data['data_source']['requested_end_date'], self.end_date.isoformat())
        self.assertEqual(response.data['data_source']['actual_end_date'], self.end_date.isoformat())
        self.assertEqual(response.data['equity_curve'][-1]['date'], self.end_date.isoformat())

    @patch('backtest.services.fetch_and_cache_daily_prices')
    def test_non_trading_warmup_boundary_does_not_refetch_covered_cache(self, fetch_prices):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)
        warmup_start = self.start_date - timedelta(days=400)
        SecurityDailyPrice.objects.filter(
            security__in=[self.security, self.benchmark],
            date__lte=warmup_start + timedelta(days=2),
        ).delete()

        response = self.run_backtest()

        self.assertEqual(response.status_code, 200)
        fetch_prices.assert_not_called()
        self.assertEqual(response.data['data_source']['source'], 'database_cache')

    def test_missing_benchmark_security_returns_clear_400(self):
        response = self.run_backtest(benchmark='ZZZZ')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['benchmark'][0], 'Benchmark security must exist in the system.')

    @patch('backtest.services.fetch_and_cache_daily_prices', side_effect=TwelveDataError('offline'))
    def test_missing_benchmark_prices_return_clear_error(self, _fetch):
        self.create_price_history(self.security)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['detail'], 'Market data is temporarily unavailable for the benchmark.')
        self.assertEqual(response.data['symbol'], 'SPY')
        self.assertEqual(response.data['required_rows'], 220)
        self.assertEqual(response.data['available_rows'], 0)
        self.assertEqual(response.data['upstream_error'], 'offline')

    @patch(
        'backtest.services.fetch_and_cache_daily_prices',
        side_effect=TwelveDataRateLimitError('Market data provider rate limit reached.'),
    )
    def test_rate_limit_keeps_429_and_reports_warmup_coverage(self, _fetch):
        self.create_price_history(self.benchmark)

        response = self.run_backtest()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['symbol'], 'TEST')
        self.assertEqual(response.data['required_rows'], 220)
        self.assertEqual(response.data['available_rows'], 0)
        self.assertIn('rate limit reached', response.data['upstream_error'])

    def test_core_fast_ma_must_be_smaller_than_core_slow_ma(self):
        response = self.run_backtest(core_fast_ma=60, core_slow_ma=60)

        self.assertEqual(response.status_code, 400)
        self.assertIn('core_fast_ma', response.data)

    def test_swing_rsi_entry_must_be_lower_than_exit(self):
        response = self.run_backtest(swing_rsi_entry_level='60', swing_rsi_exit_level='58')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['swing_rsi_entry_level'][0],
            'Swing RSI Entry Level must be lower than Swing RSI Exit Level.',
        )

    def test_risk_fraction_limits_are_enforced_by_api(self):
        core_response = self.run_backtest(core_risk_percentage='0.051')
        swing_response = self.run_backtest(swing_risk_percentage='0.021')

        self.assertEqual(core_response.status_code, 400)
        self.assertIn('core_risk_percentage', core_response.data)
        self.assertEqual(swing_response.status_code, 400)
        self.assertIn('swing_risk_percentage', swing_response.data)

        core_minimum = self.run_backtest(core_risk_fraction='0.0005')
        swing_minimum = self.run_backtest(swing_risk_fraction='0.0005')
        exposure_minimum = self.run_backtest(max_core_exposure='0.09')
        core_atr_minimum = self.run_backtest(core_atr_multiplier='0.4')
        swing_atr_maximum = self.run_backtest(swing_atr_multiplier='5.1')
        reduce_fraction_minimum = self.run_backtest(core_reduce_fraction='0.04')
        reduce_fraction_maximum = self.run_backtest(core_reduce_fraction='0.91')
        self.assertEqual(core_minimum.data['core_risk_fraction'][0], 'Core Risk must be between 0.1% and 5%.')
        self.assertEqual(swing_minimum.data['swing_risk_fraction'][0], 'Swing Risk must be between 0.1% and 2%.')
        self.assertEqual(exposure_minimum.data['max_core_exposure'][0], 'Max Core Exposure must be between 10% and 100%.')
        self.assertEqual(core_atr_minimum.data['core_atr_multiplier'][0], 'Core ATR Multiplier must be between 0.5 and 8.0.')
        self.assertEqual(swing_atr_maximum.data['swing_atr_multiplier'][0], 'Swing ATR Multiplier must be between 0.5 and 5.0.')
        self.assertIn('core_reduce_fraction', reduce_fraction_minimum.data)
        self.assertIn('core_reduce_fraction', reduce_fraction_maximum.data)

    def test_formatted_api_parameters_can_be_submitted_again(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)

        response = self.run_backtest(
            core_atr_multiplier='2.000000',
            swing_atr_multiplier='1.500000',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['strategy_parameters']['core_atr_multiplier'], '2.000000')
        self.assertEqual(response.data['strategy_parameters']['swing_atr_multiplier'], '1.500000')

    def test_entry_orders_explain_risk_cash_and_exposure_caps(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)

        exposure_response = self.run_backtest(max_core_exposure='0.20')
        cash_response = self.run_backtest(
            core_risk_fraction='0.05',
            core_atr_multiplier='0.5',
            max_core_exposure='1.0',
        )

        exposure_buy = next(trade for trade in exposure_response.data['trades'] if trade['type'] == 'BUY')
        cash_buy = next(trade for trade in cash_response.data['trades'] if trade['type'] == 'BUY')
        sizing_fields = {
            'equity_before',
            'risk_fraction',
            'risk_amount',
            'atr',
            'stop_distance',
            'raw_quantity',
            'affordable_quantity',
            'exposure_capped_quantity',
            'final_quantity',
            'raw_exposure',
            'final_exposure',
            'exposure_cap_applied',
            'cash_cap_applied',
        }
        self.assertTrue(sizing_fields.issubset(exposure_buy))
        self.assertTrue(exposure_buy['exposure_cap_applied'])
        self.assertFalse(exposure_buy['cash_cap_applied'])
        self.assertTrue(cash_buy['cash_cap_applied'])
        self.assertFalse(cash_buy['exposure_cap_applied'])
        self.assertEqual(exposure_buy['final_quantity'], exposure_buy['quantity'])

        lower_risk_response = self.run_backtest(core_risk_fraction='0.01')
        lower_risk_buy = next(trade for trade in lower_risk_response.data['trades'] if trade['type'] == 'BUY')
        self.assertEqual(exposure_buy['risk_fraction'], '0.020000')
        self.assertEqual(lower_risk_buy['risk_fraction'], '0.010000')
        self.assertLess(Decimal(lower_risk_buy['risk_amount']), Decimal(exposure_buy['risk_amount']))

    def test_parameters_change_real_curve_and_repeated_runs_are_deterministic(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)

        baseline = self.run_backtest()
        shorter_ma = self.run_backtest(core_fast_ma=5, core_slow_ma=10)
        capped_exposure = self.run_backtest(max_core_exposure='0.20')
        wider_atr = self.run_backtest(core_atr_multiplier='4.0')
        repeated = self.run_backtest()

        for response in (baseline, shorter_ma, capped_exposure, wider_atr, repeated):
            self.assertEqual(response.status_code, 200)

        self.assertNotEqual(baseline.data['equity_curve'], shorter_ma.data['equity_curve'])
        self.assertEqual(shorter_ma.data['strategy_parameters']['core_fast_ma'], 5)
        self.assertEqual(shorter_ma.data['strategy_parameters']['core_slow_ma'], 10)

        baseline_buy = next(trade for trade in baseline.data['trades'] if trade['type'] == 'BUY')
        capped_buy = next(trade for trade in capped_exposure.data['trades'] if trade['type'] == 'BUY')
        wider_atr_buy = next(trade for trade in wider_atr.data['trades'] if trade['type'] == 'BUY')
        self.assertLess(Decimal(capped_buy['quantity']), Decimal(baseline_buy['quantity']))
        self.assertLess(Decimal(wider_atr_buy['quantity']), Decimal(baseline_buy['quantity']))
        self.assertGreater(Decimal(wider_atr_buy['stop_distance']), Decimal(baseline_buy['stop_distance']))
        self.assertNotEqual(capped_exposure.data['final_equity'], baseline.data['final_equity'])
        self.assertNotEqual(wider_atr.data['final_equity'], baseline.data['final_equity'])

        deterministic_fields = (
            'final_equity',
            'total_return',
            'maximum_drawdown',
            'annualized_volatility',
            'total_fees',
            'executed_order_count',
            'equity_curve',
            'drawdown_curve',
            'trades',
        )
        for field in deterministic_fields:
            self.assertEqual(baseline.data[field], repeated.data[field])

    def test_unauthenticated_user_cannot_run_backtest(self):
        response = self.client.post(self.url, self.payload(), format='json')

        self.assertIn(response.status_code, {401, 403})

    def test_requests_do_not_persist_or_cross_user_boundaries(self):
        self.create_price_history(self.security)
        self.create_price_history(self.benchmark)
        first_response = self.run_backtest()
        self.client.force_authenticate(self.other_user)
        second_response = self.client.post(self.url, self.payload(), format='json')

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertNotIn('history', first_response.data)
        self.assertNotIn('history', second_response.data)
