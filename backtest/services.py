from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN
from math import ceil

from django.utils import timezone

from market.models import Security, SecurityDailyPrice
from market.services import fetch_and_cache_daily_prices, get_cached_daily_prices
from market.twelve_data import (
    TwelveDataError,
    TwelveDataInvalidSymbolError,
    TwelveDataRateLimitError,
)


ZERO = Decimal('0')
ONE = Decimal('1')
HUNDRED = Decimal('100')
TRADING_DAYS_PER_YEAR = Decimal('252')
MONEY_QUANT = Decimal('0.000001')
QUANTITY_QUANT = Decimal('0.00000001')
BENCHMARK_LONG_MA_PERIOD = 200
BENCHMARK_SLOPE_PERIOD = 50
ATR_PERIOD = 14
RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
SWING_TREND_AVERAGE_PERIOD = 10
WARMUP_SAFETY_BUFFER_TRADING_DAYS = 20
WARMUP_CALENDAR_BUFFER_DAYS = 30

REGIME_BULL = 'BULL'
REGIME_NEUTRAL = 'NEUTRAL'
REGIME_BEAR = 'BEAR'

LAYER_CORE = 'CORE'
LAYER_SWING = 'SWING'


class BacktestError(Exception):
    pass


class BacktestDataError(BacktestError):
    pass


class BacktestInsufficientHistoryError(BacktestDataError):
    def __init__(self, *, asset, benchmark, required_warmup_rows, requested_start_date, warmup_start_date):
        deficient_history = (
            asset
            if asset['available_rows'] < required_warmup_rows
            else benchmark
        )
        self.details = {
            'symbol': deficient_history['symbol'],
            'required_rows': required_warmup_rows,
            'available_rows': deficient_history['available_rows'],
            'first_available_date': deficient_history['first_available_date'],
            'requested_warmup_start': warmup_start_date.isoformat(),
            'upstream_error': 'Provider returned insufficient historical rows.',
            'required_warmup_rows': required_warmup_rows,
            'requested_start_date': requested_start_date.isoformat(),
            'warmup_start_date': warmup_start_date.isoformat(),
            'asset': asset,
            'benchmark': benchmark,
        }
        message = (
            'Not enough warm-up history after attempting to fill the market-data cache. '
            f'Asset {asset["symbol"]}: {asset["available_rows"]} available rows before '
            f'{requested_start_date.isoformat()}, first available date '
            f'{asset["first_available_date"] or "unavailable"}. '
            f'Benchmark {benchmark["symbol"]}: {benchmark["available_rows"]} available rows before '
            f'{requested_start_date.isoformat()}, first available date '
            f'{benchmark["first_available_date"] or "unavailable"}. '
            f'Required warm-up rows: {required_warmup_rows}; '
            f'requested start date: {requested_start_date.isoformat()}.'
        )
        super().__init__(message)


class BacktestMarketDataRateLimited(BacktestError):
    def __init__(self, message, details=None):
        self.details = details or {}
        super().__init__(message)


class BacktestMarketDataUnavailable(BacktestError):
    def __init__(self, message, details=None):
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class DailyBacktestBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class StrategyParameters:
    core_fast_ma: int = 20
    core_slow_ma: int = 60
    core_risk_percentage: Decimal = Decimal('0.02')
    core_atr_multiplier: Decimal = Decimal('2.5')
    max_core_exposure: Decimal = Decimal('0.80')
    swing_risk_percentage: Decimal = Decimal('0.01')
    swing_atr_multiplier: Decimal = Decimal('1.2')
    swing_rsi_lookback: int = 10
    swing_rsi_entry_level: Decimal = Decimal('45')
    swing_rsi_exit_level: Decimal = Decimal('60')
    swing_cooldown_days: int = 2
    swing_average_type: str = 'EMA10'


def quantize_money(value):
    return Decimal(value).quantize(MONEY_QUANT)


def quantize_quantity(value):
    return Decimal(value).quantize(QUANTITY_QUANT, rounding=ROUND_DOWN)


def format_decimal(value):
    if value is None:
        return None
    return f'{quantize_money(value):f}'


def format_quantity(value):
    return f'{quantize_quantity(value):f}'


def format_optional_quantity(value):
    return None if value is None else format_quantity(value)


def get_price_source(cached_before_fetch, fetched_from_provider):
    return 'twelve_data' if fetched_from_provider else 'database_cache'


def calculate_required_warmup_trading_days(parameters):
    indicator_period = max(
        BENCHMARK_LONG_MA_PERIOD,
        BENCHMARK_SLOPE_PERIOD + 1,
        parameters.core_slow_ma,
        ATR_PERIOD,
        RSI_PERIOD,
        BOLLINGER_PERIOD,
        SWING_TREND_AVERAGE_PERIOD,
        parameters.swing_rsi_lookback,
    )
    return indicator_period + WARMUP_SAFETY_BUFFER_TRADING_DAYS


def calculate_warmup_calendar_days(required_warmup_rows):
    return ceil(required_warmup_rows * 365 / 252) + WARMUP_CALENDAR_BUFFER_DAYS


def calculate_warmup_start_date(start_date, required_warmup_rows):
    return start_date - timedelta(days=calculate_warmup_calendar_days(required_warmup_rows))


def prices_to_backtest_bars(prices):
    return tuple(
        DailyBacktestBar(
            date=price.date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.close,
        )
        for price in prices
        if (
            price.open is not None
            and price.high is not None
            and price.low is not None
            and price.close is not None
            and price.open > ZERO
            and price.high > ZERO
            and price.low > ZERO
            and price.close > ZERO
        )
    )


def count_warmup_rows(bars, requested_start_date):
    return sum(1 for bar in bars if bar.date < requested_start_date)


def build_market_data_failure_details(
    security,
    bars,
    requested_start_date,
    requested_warmup_start,
    required_warmup_rows,
    upstream_error,
):
    return {
        'symbol': security.symbol,
        'required_rows': required_warmup_rows,
        'available_rows': count_warmup_rows(bars, requested_start_date),
        'first_available_date': bars[0].date.isoformat() if bars else None,
        'requested_warmup_start': requested_warmup_start.isoformat(),
        'upstream_error': upstream_error,
    }


def load_daily_backtest_bars(
    security,
    start_date,
    end_date,
    *,
    requested_start_date,
    required_warmup_rows,
    data_label='security',
):
    cached_before_fetch = get_cached_daily_prices(security, start_date, end_date)
    cached_bars = prices_to_backtest_bars(cached_before_fetch)
    cached_warmup_rows = count_warmup_rows(cached_bars, requested_start_date)
    fetched_from_provider = False
    trading_calendar_tolerance = timedelta(days=7)
    needs_fetch = (
        not cached_before_fetch
        or cached_before_fetch[0].date > start_date + trading_calendar_tolerance
        or cached_before_fetch[-1].date < end_date - trading_calendar_tolerance
        or cached_warmup_rows < required_warmup_rows
    )

    if needs_fetch:
        try:
            fetch_and_cache_daily_prices(security, start_date, end_date)
            fetched_from_provider = True
        except TwelveDataRateLimitError as exc:
            if not cached_before_fetch or cached_warmup_rows < required_warmup_rows:
                raise BacktestMarketDataRateLimited(
                    f'Market data provider rate limit reached while loading the {data_label}. '
                    'Please try again later.',
                    build_market_data_failure_details(
                        security,
                        cached_bars,
                        requested_start_date,
                        start_date,
                        required_warmup_rows,
                        str(exc),
                    ),
                ) from exc
        except TwelveDataInvalidSymbolError as exc:
            raise BacktestMarketDataUnavailable(
                f'Market data is not available for the {data_label}.',
                build_market_data_failure_details(
                    security,
                    cached_bars,
                    requested_start_date,
                    start_date,
                    required_warmup_rows,
                    str(exc),
                ),
            ) from exc
        except TwelveDataError as exc:
            if not cached_before_fetch or cached_warmup_rows < required_warmup_rows:
                raise BacktestMarketDataUnavailable(
                    f'Market data is temporarily unavailable for the {data_label}.',
                    build_market_data_failure_details(
                        security,
                        cached_bars,
                        requested_start_date,
                        start_date,
                        required_warmup_rows,
                        str(exc),
                    ),
                ) from exc

    prices = get_cached_daily_prices(security, start_date, end_date)
    if not prices:
        raise BacktestMarketDataUnavailable(
            f'No historical daily prices are available for the {data_label}.',
            build_market_data_failure_details(
                security,
                (),
                requested_start_date,
                start_date,
                required_warmup_rows,
                'Provider returned no historical daily prices.',
            ),
        )

    bars = prices_to_backtest_bars(prices)
    if not bars:
        raise BacktestMarketDataUnavailable(
            f'No valid historical OHLCV prices are available for the {data_label}.',
            build_market_data_failure_details(
                security,
                (),
                requested_start_date,
                start_date,
                required_warmup_rows,
                'Provider returned no valid positive OHLCV rows.',
            ),
        )

    return bars, {
        'source': get_price_source(bool(cached_before_fetch), fetched_from_provider),
        'price_model': SecurityDailyPrice.SOURCE_TWELVE_DATA,
        'requested_start_date': start_date.isoformat(),
        'requested_end_date': end_date.isoformat(),
        'loaded_start_date': bars[0].date.isoformat(),
        'loaded_end_date': bars[-1].date.isoformat(),
        'record_count': len(bars),
        'warmup_record_count': count_warmup_rows(bars, requested_start_date),
        'required_warmup_rows': required_warmup_rows,
        'fetched_from_provider': fetched_from_provider,
    }


def calculate_simple_moving_average(bars, period):
    values = []
    rolling_sum = ZERO
    for index, bar in enumerate(bars):
        rolling_sum += bar.close
        if index >= period:
            rolling_sum -= bars[index - period].close
        values.append(None if index + 1 < period else rolling_sum / Decimal(period))
    return tuple(values)


def calculate_exponential_moving_average(bars, period):
    values = [None] * len(bars)
    if len(bars) < period:
        return tuple(values)
    multiplier = Decimal('2') / Decimal(period + 1)
    ema = sum((bar.close for bar in bars[:period]), ZERO) / Decimal(period)
    values[period - 1] = ema
    for index in range(period, len(bars)):
        ema = ((bars[index].close - ema) * multiplier) + ema
        values[index] = ema
    return tuple(values)


def calculate_rsi(bars, period=RSI_PERIOD):
    values = [None] * len(bars)
    if len(bars) <= period:
        return tuple(values)

    gains = []
    losses = []
    for index in range(1, period + 1):
        change = bars[index].close - bars[index - 1].close
        gains.append(max(change, ZERO))
        losses.append(max(-change, ZERO))

    average_gain = sum(gains, ZERO) / Decimal(period)
    average_loss = sum(losses, ZERO) / Decimal(period)

    def rsi_value(gain, loss):
        if gain == ZERO and loss == ZERO:
            return Decimal('50')
        if loss == ZERO:
            return HUNDRED
        if gain == ZERO:
            return ZERO
        relative_strength = gain / loss
        return HUNDRED - (HUNDRED / (ONE + relative_strength))

    values[period] = rsi_value(average_gain, average_loss)
    for index in range(period + 1, len(bars)):
        change = bars[index].close - bars[index - 1].close
        gain = max(change, ZERO)
        loss = max(-change, ZERO)
        average_gain = ((average_gain * Decimal(period - 1)) + gain) / Decimal(period)
        average_loss = ((average_loss * Decimal(period - 1)) + loss) / Decimal(period)
        values[index] = rsi_value(average_gain, average_loss)
    return tuple(values)


def calculate_atr(bars, period=ATR_PERIOD):
    values = [None] * len(bars)
    if len(bars) < period:
        return tuple(values)

    true_ranges = []
    for index, bar in enumerate(bars):
        if index == 0:
            true_range = bar.high - bar.low
        else:
            previous_close = bars[index - 1].close
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        true_ranges.append(true_range)

    atr = sum(true_ranges[:period], ZERO) / Decimal(period)
    values[period - 1] = atr
    for index in range(period, len(bars)):
        atr = ((atr * Decimal(period - 1)) + true_ranges[index]) / Decimal(period)
        values[index] = atr
    return tuple(values)


def calculate_bollinger_upper(bars, period=BOLLINGER_PERIOD, multiplier=Decimal('2')):
    values = [None] * len(bars)
    for index in range(period - 1, len(bars)):
        sample = [bar.close for bar in bars[index - period + 1:index + 1]]
        mean = sum(sample, ZERO) / Decimal(period)
        variance = sum(((value - mean) ** 2 for value in sample), ZERO) / Decimal(period)
        values[index] = mean + (variance.sqrt() * multiplier)
    return tuple(values)


def calculate_market_regimes(asset_bars, benchmark_bars):
    benchmark_ma50 = calculate_simple_moving_average(benchmark_bars, BENCHMARK_SLOPE_PERIOD)
    benchmark_ma200 = calculate_simple_moving_average(benchmark_bars, BENCHMARK_LONG_MA_PERIOD)
    benchmark_regimes = []
    for index, bar in enumerate(benchmark_bars):
        ma50 = benchmark_ma50[index]
        ma200 = benchmark_ma200[index]
        previous_ma50 = benchmark_ma50[index - 1] if index else None
        if ma50 is None or ma200 is None or previous_ma50 is None:
            benchmark_regimes.append(None)
        elif bar.close < ma200:
            benchmark_regimes.append(REGIME_BEAR)
        elif bar.close > ma200 and ma50 > previous_ma50:
            benchmark_regimes.append(REGIME_BULL)
        else:
            benchmark_regimes.append(REGIME_NEUTRAL)

    regimes = []
    benchmark_index = -1
    for bar in asset_bars:
        while (
            benchmark_index + 1 < len(benchmark_bars)
            and benchmark_bars[benchmark_index + 1].date <= bar.date
        ):
            benchmark_index += 1
        regimes.append(benchmark_regimes[benchmark_index] if benchmark_index >= 0 else None)
    return tuple(regimes)


def build_indicator_inputs(asset_bars, benchmark_bars, parameters):
    sma10 = calculate_simple_moving_average(asset_bars, SWING_TREND_AVERAGE_PERIOD)
    ema10 = calculate_exponential_moving_average(asset_bars, SWING_TREND_AVERAGE_PERIOD)
    return {
        'ma10': sma10,
        'ema10': ema10,
        'swing_average': ema10 if parameters.swing_average_type == 'EMA10' else sma10,
        'ma20': calculate_simple_moving_average(asset_bars, parameters.core_fast_ma),
        'ma60': calculate_simple_moving_average(asset_bars, parameters.core_slow_ma),
        'rsi14': calculate_rsi(asset_bars, RSI_PERIOD),
        'atr14': calculate_atr(asset_bars, ATR_PERIOD),
        'bollinger_upper': calculate_bollinger_upper(asset_bars, BOLLINGER_PERIOD, Decimal('2')),
        'market_regime': calculate_market_regimes(asset_bars, benchmark_bars),
    }


def calculate_annualized_volatility(equity_values):
    returns = []
    for previous, current in zip(equity_values, equity_values[1:]):
        if previous > ZERO:
            returns.append((current / previous) - ONE)
    if not returns:
        return ZERO
    mean = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(len(returns))
    return variance.sqrt() * TRADING_DAYS_PER_YEAR.sqrt() * HUNDRED


def calculate_curve_metrics(equity_values, initial_capital):
    running_peak = Decimal(initial_capital)
    maximum_drawdown = ZERO
    drawdowns = []
    for equity in equity_values:
        running_peak = max(running_peak, equity)
        drawdown = ZERO if running_peak <= ZERO else ((equity - running_peak) / running_peak) * HUNDRED
        maximum_drawdown = max(maximum_drawdown, abs(drawdown))
        drawdowns.append(drawdown)
    final_equity = equity_values[-1]
    return {
        'final_equity': final_equity,
        'total_return': ((final_equity - Decimal(initial_capital)) / Decimal(initial_capital)) * HUNDRED,
        'maximum_drawdown': maximum_drawdown,
        'annualized_volatility': calculate_annualized_volatility(equity_values),
        'drawdowns': drawdowns,
    }


def build_trade(
    *,
    index,
    signal_date,
    execution_bar,
    trade_type,
    position_layer,
    reason,
    quantity,
    execution_price,
    fee,
    cash_after,
    core_quantity_after,
    swing_quantity_after,
    realized_profit_loss,
    sizing=None,
):
    sizing = sizing or {}
    total_quantity = core_quantity_after + swing_quantity_after
    return {
        'id': f'trade-{index}',
        'position_layer': position_layer,
        'reason': reason,
        'signal_date': signal_date.isoformat(),
        'execution_date': execution_bar.date.isoformat(),
        'type': trade_type,
        'execution_price': format_decimal(execution_price),
        'quantity': format_quantity(quantity),
        'fee': format_decimal(fee),
        'cash_after': format_decimal(cash_after),
        'core_quantity_after': format_quantity(core_quantity_after),
        'swing_quantity_after': format_quantity(swing_quantity_after),
        'total_quantity_after': format_quantity(total_quantity),
        'position_after': format_quantity(total_quantity),
        'realized_profit_loss': format_decimal(realized_profit_loss),
        'equity_before': format_decimal(sizing.get('equity_before')),
        'risk_fraction': format_decimal(sizing.get('risk_fraction')),
        'risk_amount': format_decimal(sizing.get('risk_amount')),
        'atr': format_decimal(sizing.get('atr')),
        'stop_distance': format_decimal(sizing.get('stop_distance')),
        'raw_quantity': format_optional_quantity(sizing.get('raw_quantity')),
        'affordable_quantity': format_optional_quantity(sizing.get('affordable_quantity')),
        'exposure_capped_quantity': format_optional_quantity(sizing.get('exposure_capped_quantity')),
        'final_quantity': format_quantity(sizing.get('final_quantity', quantity)),
        'raw_exposure': format_decimal(sizing.get('raw_exposure')),
        'final_exposure': format_decimal(sizing.get('final_exposure')),
        'exposure_cap_applied': bool(sizing.get('exposure_cap_applied', False)),
        'cash_cap_applied': bool(sizing.get('cash_cap_applied', False)),
    }


def simulate_layered_strategy(
    *,
    bars,
    indicators,
    start_date,
    initial_capital,
    transaction_fee,
    parameters,
    enable_swing=True,
):
    start_index = next((index for index, bar in enumerate(bars) if bar.date >= start_date), None)
    if start_index is None:
        raise BacktestDataError('No security prices are available inside the requested backtest period.')

    required_series = ('swing_average', 'ma20', 'ma60', 'rsi14', 'atr14', 'bollinger_upper', 'market_regime')
    if any(indicators[name][start_index] is None for name in required_series):
        raise BacktestDataError('Not enough warm-up history to calculate the strategy indicators.')

    cash = Decimal(initial_capital)
    core_quantity = ZERO
    core_average_cost = ZERO
    core_stop = None
    swing_quantity = ZERO
    swing_average_cost = ZERO
    swing_stop = None
    pending_orders = []
    trades = []
    equity_curve = []
    equity_values = []
    trade_index = 1

    core_realized = ZERO
    swing_realized = ZERO
    total_fees = ZERO
    swing_fees = ZERO
    swing_turnover_value = ZERO
    core_entry_count = 0
    core_exit_count = 0
    core_holding_days = 0
    swing_cycle_returns = []
    swing_cycle_days = []
    swing_entry_count = 0
    swing_exit_count = 0
    swing_entry_index = None
    last_swing_exit_index = None
    swing_signal_diagnostics = {
        'eligible_core_days': 0,
        'market_bear_days': 0,
        'rsi_pullback_detected_days': 0,
        'rsi_upward_cross_days': 0,
        'close_above_trend_average_days': 0,
        'cooldown_blocked_days': 0,
        'swing_entry_signal_count': 0,
        'swing_exit_signal_count': 0,
        'primary_block_reason_counts': {
            'NO_CORE_POSITION': 0,
            'MARKET_BEAR': 0,
            'NO_RSI_PULLBACK': 0,
            'RSI_NOT_CROSSED_UP': 0,
            'CLOSE_BELOW_TREND_AVERAGE': 0,
            'COOLDOWN_ACTIVE': 0,
            'SWING_ALREADY_OPEN': 0,
            'CORE_TREND_NOT_ELIGIBLE': 0,
            'CORE_EXIT_PENDING': 0,
            'ATR_UNAVAILABLE': 0,
            'ENTRY_SIGNAL_CREATED': 0,
        },
    }

    for index in range(start_index, len(bars)):
        bar = bars[index]

        for order in pending_orders:
            layer = order['layer']
            trade_type = order['type']
            execution_price = bar.open
            total_quantity_before = core_quantity + swing_quantity
            equity_before = cash + (total_quantity_before * execution_price)

            if trade_type == 'BUY':
                if layer == LAYER_CORE and core_quantity > ZERO:
                    continue
                if layer == LAYER_SWING and (swing_quantity > ZERO or core_quantity <= ZERO):
                    continue

                risk_percentage = (
                    parameters.core_risk_percentage
                    if layer == LAYER_CORE
                    else parameters.swing_risk_percentage
                )
                atr_multiplier = (
                    parameters.core_atr_multiplier
                    if layer == LAYER_CORE
                    else parameters.swing_atr_multiplier
                )
                stop_distance = order['atr'] * atr_multiplier
                if stop_distance <= ZERO or cash <= transaction_fee:
                    continue

                risk_quantity = (equity_before * risk_percentage) / stop_distance
                cash_quantity = (cash - transaction_fee) / execution_price
                if layer == LAYER_CORE:
                    exposure_quantity = (equity_before * parameters.max_core_exposure) / execution_price
                else:
                    available_exposure = max(equity_before - (total_quantity_before * execution_price), ZERO)
                    exposure_quantity = available_exposure / execution_price
                quantity = quantize_quantity(min(risk_quantity, cash_quantity, exposure_quantity))
                if quantity <= ZERO:
                    continue

                risk_amount = equity_before * risk_percentage
                raw_exposure = (
                    ZERO
                    if equity_before <= ZERO
                    else (risk_quantity * execution_price / equity_before) * HUNDRED
                )
                final_exposure = (
                    ZERO
                    if equity_before <= ZERO
                    else (quantity * execution_price / equity_before) * HUNDRED
                )
                sizing = {
                    'equity_before': equity_before,
                    'risk_fraction': risk_percentage,
                    'risk_amount': risk_amount,
                    'atr': order['atr'],
                    'stop_distance': stop_distance,
                    'raw_quantity': risk_quantity,
                    'affordable_quantity': cash_quantity,
                    'exposure_capped_quantity': exposure_quantity,
                    'final_quantity': quantity,
                    'raw_exposure': raw_exposure,
                    'final_exposure': final_exposure,
                    'exposure_cap_applied': exposure_quantity < risk_quantity and exposure_quantity <= cash_quantity,
                    'cash_cap_applied': cash_quantity < risk_quantity and cash_quantity < exposure_quantity,
                }

                gross_amount = quantity * execution_price
                cash = quantize_money(cash - gross_amount - transaction_fee)
                average_cost = (gross_amount + transaction_fee) / quantity
                total_fees += transaction_fee
                if layer == LAYER_CORE:
                    core_quantity = quantity
                    core_average_cost = average_cost
                    core_stop = execution_price - stop_distance
                    core_entry_count += 1
                else:
                    swing_quantity = quantity
                    swing_average_cost = average_cost
                    swing_stop = execution_price - stop_distance
                    swing_fees += transaction_fee
                    swing_turnover_value += gross_amount
                    swing_entry_count += 1
                    swing_entry_index = index

                trades.append(build_trade(
                    index=trade_index,
                    signal_date=order['signal_date'],
                    execution_bar=bar,
                    trade_type='BUY',
                    position_layer=layer,
                    reason=order['reason'],
                    quantity=quantity,
                    execution_price=execution_price,
                    fee=transaction_fee,
                    cash_after=cash,
                    core_quantity_after=core_quantity,
                    swing_quantity_after=swing_quantity,
                    realized_profit_loss=ZERO,
                    sizing=sizing,
                ))
                trade_index += 1
                continue

            quantity = core_quantity if layer == LAYER_CORE else swing_quantity
            average_cost = core_average_cost if layer == LAYER_CORE else swing_average_cost
            if quantity <= ZERO:
                continue
            gross_amount = quantity * execution_price
            realized_profit_loss = gross_amount - transaction_fee - (quantity * average_cost)
            cash = quantize_money(cash + gross_amount - transaction_fee)
            total_fees += transaction_fee
            if layer == LAYER_CORE:
                core_realized += realized_profit_loss
                core_quantity = ZERO
                core_average_cost = ZERO
                core_stop = None
                core_exit_count += 1
            else:
                swing_realized += realized_profit_loss
                entry_cost = quantity * average_cost
                swing_cycle_returns.append(
                    ZERO if entry_cost <= ZERO else (realized_profit_loss / entry_cost) * HUNDRED
                )
                swing_quantity = ZERO
                swing_average_cost = ZERO
                swing_stop = None
                swing_fees += transaction_fee
                swing_turnover_value += gross_amount
                swing_exit_count += 1
                last_swing_exit_index = index
                if swing_entry_index is not None:
                    swing_cycle_days.append(index - swing_entry_index)
                swing_entry_index = None

            trades.append(build_trade(
                index=trade_index,
                signal_date=order['signal_date'],
                execution_bar=bar,
                trade_type='SELL',
                position_layer=layer,
                reason=order['reason'],
                quantity=quantity,
                execution_price=execution_price,
                fee=transaction_fee,
                cash_after=cash,
                core_quantity_after=core_quantity,
                swing_quantity_after=swing_quantity,
                realized_profit_loss=realized_profit_loss,
                sizing={
                    'equity_before': equity_before,
                    'risk_fraction': (
                        parameters.core_risk_percentage
                        if layer == LAYER_CORE
                        else parameters.swing_risk_percentage
                    ),
                    'final_quantity': quantity,
                },
            ))
            trade_index += 1

        pending_orders = []

        total_quantity = core_quantity + swing_quantity
        core_value = core_quantity * bar.close
        swing_value = swing_quantity * bar.close
        holdings_value = core_value + swing_value
        total_equity = cash + holdings_value
        if core_quantity > ZERO:
            core_holding_days += 1
        core_exposure = ZERO if total_equity <= ZERO else (core_value / total_equity) * HUNDRED
        swing_exposure = ZERO if total_equity <= ZERO else (swing_value / total_equity) * HUNDRED
        total_exposure = core_exposure + swing_exposure

        equity_values.append(total_equity)
        equity_curve.append({
            'date': bar.date.isoformat(),
            'close': format_decimal(bar.close),
            'cash': format_decimal(cash),
            'holdings_value': format_decimal(holdings_value),
            'total_equity': format_decimal(total_equity),
            'ma10': format_decimal(indicators['ma10'][index]),
            'ema10': format_decimal(indicators['ema10'][index]),
            'swing_average': format_decimal(indicators['swing_average'][index]),
            'swing_average_type': parameters.swing_average_type,
            'ma20': format_decimal(indicators['ma20'][index]),
            'ma60': format_decimal(indicators['ma60'][index]),
            'rsi14': format_decimal(indicators['rsi14'][index]),
            'atr14': format_decimal(indicators['atr14'][index]),
            'bollinger_upper': format_decimal(indicators['bollinger_upper'][index]),
            'market_regime': indicators['market_regime'][index],
            'core_quantity': format_quantity(core_quantity),
            'core_average_cost': format_decimal(core_average_cost),
            'swing_quantity': format_quantity(swing_quantity),
            'swing_average_cost': format_decimal(swing_average_cost),
            'core_exposure': format_decimal(core_exposure),
            'swing_exposure': format_decimal(swing_exposure),
            'total_exposure': format_decimal(total_exposure),
        })

        if index + 1 >= len(bars):
            continue

        swing_average = indicators['swing_average'][index]
        ma20 = indicators['ma20'][index]
        ma60 = indicators['ma60'][index]
        previous_ma20 = indicators['ma20'][index - 1] if index else None
        previous_ma60 = indicators['ma60'][index - 1] if index else None
        previous_swing_average = indicators['swing_average'][index - 1] if index else None
        rsi14 = indicators['rsi14'][index]
        previous_rsi = indicators['rsi14'][index - 1] if index else None
        atr14 = indicators['atr14'][index]
        bollinger_upper = indicators['bollinger_upper'][index]
        market_regime = indicators['market_regime'][index]

        core_exit_reason = None
        if core_quantity > ZERO:
            two_closes_below_ma60 = (
                index > 0
                and previous_ma60 is not None
                and bars[index - 1].close < previous_ma60
                and bar.close < ma60
            )
            bearish_cross = (
                previous_ma20 is not None
                and previous_ma60 is not None
                and previous_ma20 >= previous_ma60
                and ma20 < ma60
            )
            if core_stop is not None and bar.close <= core_stop:
                core_exit_reason = 'CORE_ATR_EXIT'
            elif two_closes_below_ma60 or bearish_cross:
                core_exit_reason = 'CORE_TREND_EXIT'

        swing_exit_reason = None
        if enable_swing and swing_quantity > ZERO:
            if core_exit_reason or market_regime == REGIME_BEAR:
                swing_exit_reason = 'SWING_FORCED_EXIT'
            elif swing_stop is not None and bar.close <= swing_stop:
                swing_exit_reason = 'SWING_ATR_EXIT'
            elif rsi14 >= parameters.swing_rsi_exit_level:
                swing_exit_reason = 'SWING_RSI_EXIT'
            elif bar.close >= bollinger_upper:
                swing_exit_reason = 'SWING_BOLLINGER_EXIT'
            elif (
                previous_swing_average is not None
                and bars[index - 1].close >= previous_swing_average
                and bar.close < swing_average
            ):
                swing_exit_reason = 'SWING_MA10_EXIT'

        if swing_exit_reason:
            pending_orders.append({
                'type': 'SELL',
                'layer': LAYER_SWING,
                'reason': swing_exit_reason,
                'signal_date': bar.date,
            })
            swing_signal_diagnostics['swing_exit_signal_count'] += 1
        if core_exit_reason:
            pending_orders.append({
                'type': 'SELL',
                'layer': LAYER_CORE,
                'reason': core_exit_reason,
                'signal_date': bar.date,
            })

        if core_exit_reason is None and core_quantity > ZERO and atr14 is not None:
            trailing_stop = bar.close - (atr14 * parameters.core_atr_multiplier)
            core_stop = trailing_stop if core_stop is None else max(core_stop, trailing_stop)
        if swing_exit_reason is None and swing_quantity > ZERO and atr14 is not None:
            trailing_stop = bar.close - (atr14 * parameters.swing_atr_multiplier)
            swing_stop = trailing_stop if swing_stop is None else max(swing_stop, trailing_stop)

        if (
            core_quantity <= ZERO
            and core_exit_reason is None
            and market_regime != REGIME_BEAR
            and bar.close > ma60
            and ma20 > ma60
            and previous_ma60 is not None
            and ma60 > previous_ma60
            and atr14 is not None
            and atr14 > ZERO
        ):
            pending_orders.append({
                'type': 'BUY',
                'layer': LAYER_CORE,
                'reason': 'CORE_TREND_ENTRY',
                'signal_date': bar.date,
                'atr': atr14,
            })

        prior_rsi_window = indicators['rsi14'][max(0, index - parameters.swing_rsi_lookback):index]
        pullback_detected = any(
            value is not None and value < parameters.swing_rsi_entry_level
            for value in prior_rsi_window
        )
        rsi_crossed_up = (
            previous_rsi is not None
            and previous_rsi <= parameters.swing_rsi_entry_level
            and rsi14 > parameters.swing_rsi_entry_level
        )
        recovered_from_pullback = pullback_detected and rsi_crossed_up
        cooldown_satisfied = (
            last_swing_exit_index is None
            or index - last_swing_exit_index >= parameters.swing_cooldown_days
        )
        close_above_trend_average = bar.close > swing_average
        core_trend_eligible = (
            core_quantity > ZERO
            and core_exit_reason is None
            and market_regime != REGIME_BEAR
            and bar.close > ma60
            and ma20 > ma60
        )
        swing_entry_signal = (
            enable_swing
            and swing_quantity <= ZERO
            and swing_exit_reason is None
            and core_trend_eligible
            and close_above_trend_average
            and recovered_from_pullback
            and cooldown_satisfied
            and atr14 is not None
            and atr14 > ZERO
        )

        if enable_swing:
            if market_regime == REGIME_BEAR:
                swing_signal_diagnostics['market_bear_days'] += 1
            if core_trend_eligible:
                swing_signal_diagnostics['eligible_core_days'] += 1
            if pullback_detected:
                swing_signal_diagnostics['rsi_pullback_detected_days'] += 1
            if rsi_crossed_up:
                swing_signal_diagnostics['rsi_upward_cross_days'] += 1
            if close_above_trend_average:
                swing_signal_diagnostics['close_above_trend_average_days'] += 1
            if not cooldown_satisfied:
                swing_signal_diagnostics['cooldown_blocked_days'] += 1

            block_reasons = swing_signal_diagnostics['primary_block_reason_counts']
            if swing_entry_signal:
                block_reasons['ENTRY_SIGNAL_CREATED'] += 1
            elif swing_quantity > ZERO:
                block_reasons['SWING_ALREADY_OPEN'] += 1
            elif core_quantity <= ZERO:
                block_reasons['NO_CORE_POSITION'] += 1
            elif market_regime == REGIME_BEAR:
                block_reasons['MARKET_BEAR'] += 1
            elif core_exit_reason is not None:
                block_reasons['CORE_EXIT_PENDING'] += 1
            elif not core_trend_eligible:
                block_reasons['CORE_TREND_NOT_ELIGIBLE'] += 1
            elif not pullback_detected:
                block_reasons['NO_RSI_PULLBACK'] += 1
            elif not rsi_crossed_up:
                block_reasons['RSI_NOT_CROSSED_UP'] += 1
            elif not close_above_trend_average:
                block_reasons['CLOSE_BELOW_TREND_AVERAGE'] += 1
            elif not cooldown_satisfied:
                block_reasons['COOLDOWN_ACTIVE'] += 1
            elif atr14 is None or atr14 <= ZERO:
                block_reasons['ATR_UNAVAILABLE'] += 1

        if swing_entry_signal:
            pending_orders.append({
                'type': 'BUY',
                'layer': LAYER_SWING,
                'reason': 'SWING_PULLBACK_ENTRY',
                'signal_date': bar.date,
                'atr': atr14,
            })
            swing_signal_diagnostics['swing_entry_signal_count'] += 1

    curve_metrics = calculate_curve_metrics(equity_values, initial_capital)
    for point, drawdown in zip(equity_curve, curve_metrics['drawdowns']):
        point['drawdown'] = format_decimal(drawdown)

    last_close = bars[-1].close
    core_unrealized = (core_quantity * last_close) - (core_quantity * core_average_cost)
    swing_unrealized = (swing_quantity * last_close) - (swing_quantity * swing_average_cost)
    swing_cycle_count = len(swing_cycle_returns)
    profitable_swing_cycle_count = sum(1 for value in swing_cycle_returns if value > ZERO)
    swing_win_rate = (
        Decimal(profitable_swing_cycle_count) / Decimal(swing_cycle_count) * HUNDRED
        if swing_cycle_count
        else ZERO
    )
    average_swing_return = (
        sum(swing_cycle_returns, ZERO) / Decimal(swing_cycle_count)
        if swing_cycle_count
        else ZERO
    )
    average_days_per_swing_cycle = (
        Decimal(sum(swing_cycle_days)) / Decimal(len(swing_cycle_days))
        if swing_cycle_days
        else ZERO
    )

    return {
        **curve_metrics,
        'equity_curve': equity_curve,
        'trades': trades,
        'total_fees': total_fees,
        'executed_order_count': len(trades),
        'core_return_contribution': ((core_realized + core_unrealized) / Decimal(initial_capital)) * HUNDRED,
        'core_realized_profit_loss': core_realized,
        'core_unrealized_profit_loss': core_unrealized,
        'core_holding_days': core_holding_days,
        'core_entry_count': core_entry_count,
        'core_exit_count': core_exit_count,
        'swing_return_contribution': ((swing_realized + swing_unrealized) / Decimal(initial_capital)) * HUNDRED,
        'swing_realized_profit_loss': swing_realized,
        'swing_unrealized_profit_loss': swing_unrealized,
        'swing_cycle_count': swing_cycle_count,
        'swing_entry_count': swing_entry_count,
        'swing_exit_count': swing_exit_count,
        'average_days_per_swing_cycle': average_days_per_swing_cycle,
        'profitable_swing_cycle_count': profitable_swing_cycle_count,
        'swing_win_rate': swing_win_rate,
        'average_swing_return': average_swing_return,
        'swing_fees': swing_fees,
        'swing_total_fees': swing_fees,
        'swing_turnover': (swing_turnover_value / Decimal(initial_capital)) * HUNDRED,
        'swing_signal_diagnostics': swing_signal_diagnostics,
    }


def simulate_buy_and_hold(*, bars, start_date, initial_capital, transaction_fee):
    output_bars = [bar for bar in bars if bar.date >= start_date]
    if not output_bars:
        raise BacktestDataError('No security prices are available inside the requested backtest period.')
    first_bar = output_bars[0]
    investable_cash = Decimal(initial_capital) - transaction_fee
    quantity = quantize_quantity(investable_cash / first_bar.open) if investable_cash > ZERO else ZERO
    if quantity > ZERO:
        cash = quantize_money(Decimal(initial_capital) - (quantity * first_bar.open) - transaction_fee)
        total_fees = transaction_fee
        executed_order_count = 1
    else:
        cash = Decimal(initial_capital)
        total_fees = ZERO
        executed_order_count = 0
    equity_values = [cash + (quantity * bar.close) for bar in output_bars]
    metrics = calculate_curve_metrics(equity_values, initial_capital)
    return {
        **metrics,
        'total_fees': total_fees,
        'executed_order_count': executed_order_count,
    }


def format_comparison(name, strategy_id, result):
    return {
        'strategy': name,
        'strategy_id': strategy_id,
        'total_return': format_decimal(result['total_return']),
        'final_equity': format_decimal(result['final_equity']),
        'maximum_drawdown': format_decimal(result['maximum_drawdown']),
        'annualized_volatility': format_decimal(result['annualized_volatility']),
        'total_fees': format_decimal(result['total_fees']),
        'executed_orders': result['executed_order_count'],
    }


def build_summary(hybrid, core_only, buy_and_hold):
    return {
        'comparison': (
            f'Hybrid returned {format_decimal(hybrid["total_return"])}%, Core-Only returned '
            f'{format_decimal(core_only["total_return"])}%, and Buy and Hold returned '
            f'{format_decimal(buy_and_hold["total_return"])}% on the same historical prices.'
        ),
        'drawdownRisk': (
            f'Hybrid maximum drawdown was {format_decimal(hybrid["maximum_drawdown"])}% with '
            f'{format_decimal(hybrid["annualized_volatility"])}% annualized volatility.'
        ),
        'quality': (
            f'Core contributed {format_decimal(hybrid["core_return_contribution"])}% of initial capital; '
            f'{hybrid["swing_cycle_count"]} completed Swing cycles produced a '
            f'{format_decimal(hybrid["swing_win_rate"])}% Swing win rate.'
        ),
        'disclaimer': (
            'This is a real historical-data backtest using stored daily OHLCV prices. '
            'It is descriptive decision support, not a forecast or trading advice.'
        ),
    }


def build_history_status(security, bars, requested_start_date):
    return {
        'symbol': security.symbol,
        'available_rows': count_warmup_rows(bars, requested_start_date),
        'total_loaded_rows': len(bars),
        'first_available_date': bars[0].date.isoformat() if bars else None,
        'last_available_date': bars[-1].date.isoformat() if bars else None,
    }


def run_market_regime_core_swing_backtest(
    *,
    security,
    benchmark,
    start_date,
    end_date,
    initial_capital,
    transaction_fee,
    parameters,
):
    required_warmup_rows = calculate_required_warmup_trading_days(parameters)
    warmup_calendar_days = calculate_warmup_calendar_days(required_warmup_rows)
    warmup_start_date = calculate_warmup_start_date(start_date, required_warmup_rows)
    asset_bars, asset_source = load_daily_backtest_bars(
        security,
        warmup_start_date,
        end_date,
        requested_start_date=start_date,
        required_warmup_rows=required_warmup_rows,
        data_label='selected security',
    )
    if benchmark.pk == security.pk:
        benchmark_bars = asset_bars
        benchmark_source = dict(asset_source)
    else:
        benchmark_bars, benchmark_source = load_daily_backtest_bars(
            benchmark,
            warmup_start_date,
            end_date,
            requested_start_date=start_date,
            required_warmup_rows=required_warmup_rows,
            data_label='benchmark',
        )

    asset_history = build_history_status(security, asset_bars, start_date)
    benchmark_history = build_history_status(benchmark, benchmark_bars, start_date)
    if (
        asset_history['available_rows'] < required_warmup_rows
        or benchmark_history['available_rows'] < required_warmup_rows
    ):
        raise BacktestInsufficientHistoryError(
            asset=asset_history,
            benchmark=benchmark_history,
            required_warmup_rows=required_warmup_rows,
            requested_start_date=start_date,
            warmup_start_date=warmup_start_date,
        )

    indicators = build_indicator_inputs(asset_bars, benchmark_bars, parameters)
    hybrid = simulate_layered_strategy(
        bars=asset_bars,
        indicators=indicators,
        start_date=start_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
        parameters=parameters,
        enable_swing=True,
    )
    core_only = simulate_layered_strategy(
        bars=asset_bars,
        indicators=indicators,
        start_date=start_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
        parameters=parameters,
        enable_swing=False,
    )
    buy_and_hold = simulate_buy_and_hold(
        bars=asset_bars,
        start_date=start_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
    )

    points = hybrid['equity_curve']
    if not points or any(point['market_regime'] is None for point in points):
        raise BacktestDataError(
            'Not enough benchmark history to calculate MA200 and MA50 market regime.'
        )

    data_source = {
        **asset_source,
        'requested_start_date': start_date.isoformat(),
        'requested_end_date': end_date.isoformat(),
        'actual_start_date': points[0]['date'],
        'actual_end_date': points[-1]['date'],
        'warmup_start_date': warmup_start_date.isoformat(),
        'warmup_trading_days': required_warmup_rows,
        'warmup_calendar_days': warmup_calendar_days,
        'benchmark': benchmark_source,
    }
    comparisons = [
        format_comparison('Buy and Hold', 'buy-and-hold', buy_and_hold),
        format_comparison('Core-Only Medium-Term Strategy', 'core-only', core_only),
        format_comparison('Core + Swing Hybrid Strategy', 'core-swing-hybrid', hybrid),
    ]
    run_at = timezone.now()

    return {
        'id': f'backtest-{run_at.strftime("%Y%m%d%H%M%S%f")}-{security.symbol}-core-swing',
        'run_at': run_at.isoformat(),
        'initial_capital': format_decimal(initial_capital),
        'final_equity': format_decimal(hybrid['final_equity']),
        'total_return': format_decimal(hybrid['total_return']),
        'maximum_drawdown': format_decimal(hybrid['maximum_drawdown']),
        'annualized_volatility': format_decimal(hybrid['annualized_volatility']),
        'total_fees': format_decimal(hybrid['total_fees']),
        'executed_order_count': hybrid['executed_order_count'],
        'core_return_contribution': format_decimal(hybrid['core_return_contribution']),
        'core_realized_profit_loss': format_decimal(hybrid['core_realized_profit_loss']),
        'core_unrealized_profit_loss': format_decimal(hybrid['core_unrealized_profit_loss']),
        'core_holding_days': hybrid['core_holding_days'],
        'core_entry_count': hybrid['core_entry_count'],
        'core_exit_count': hybrid['core_exit_count'],
        'swing_return_contribution': format_decimal(hybrid['swing_return_contribution']),
        'swing_realized_profit_loss': format_decimal(hybrid['swing_realized_profit_loss']),
        'swing_unrealized_profit_loss': format_decimal(hybrid['swing_unrealized_profit_loss']),
        'swing_cycle_count': hybrid['swing_cycle_count'],
        'swing_entry_count': hybrid['swing_entry_count'],
        'swing_exit_count': hybrid['swing_exit_count'],
        'average_days_per_swing_cycle': format_decimal(hybrid['average_days_per_swing_cycle']),
        'profitable_swing_cycle_count': hybrid['profitable_swing_cycle_count'],
        'swing_win_rate': format_decimal(hybrid['swing_win_rate']),
        'average_swing_return': format_decimal(hybrid['average_swing_return']),
        'swing_fees': format_decimal(hybrid['swing_fees']),
        'swing_total_fees': format_decimal(hybrid['swing_total_fees']),
        'swing_turnover': format_decimal(hybrid['swing_turnover']),
        'swing_signal_diagnostics': hybrid['swing_signal_diagnostics'],
        'equity_curve': points,
        'drawdown_curve': [
            {'date': point['date'], 'drawdown': point['drawdown']}
            for point in points
        ],
        'trades': hybrid['trades'],
        'signal_message': (
            'No qualifying Core or Swing signals under the selected parameters.'
            if not hybrid['trades']
            else ''
        ),
        'comparisons': comparisons,
        'strategy_parameters': {
            'strategy': 'Market-Regime Core and Swing Strategy',
            'strategy_id': 'market-regime-core-swing',
            'benchmark': benchmark.symbol,
            'core_fast_ma': parameters.core_fast_ma,
            'core_slow_ma': parameters.core_slow_ma,
            'core_risk_fraction': format_decimal(parameters.core_risk_percentage),
            'core_risk_percentage': format_decimal(parameters.core_risk_percentage),
            'core_atr_multiplier': format_decimal(parameters.core_atr_multiplier),
            'max_core_exposure': format_decimal(parameters.max_core_exposure),
            'swing_risk_fraction': format_decimal(parameters.swing_risk_percentage),
            'swing_risk_percentage': format_decimal(parameters.swing_risk_percentage),
            'swing_atr_multiplier': format_decimal(parameters.swing_atr_multiplier),
            'swing_rsi_lookback': parameters.swing_rsi_lookback,
            'swing_rsi_entry_level': format_decimal(parameters.swing_rsi_entry_level),
            'swing_rsi_exit_level': format_decimal(parameters.swing_rsi_exit_level),
            'swing_cooldown_days': parameters.swing_cooldown_days,
            'swing_trend_average': parameters.swing_average_type,
            'swing_average_type': parameters.swing_average_type,
            'execution_rule': 'Signals use signal-date close data and execute at the next trading day open.',
        },
        'security': {
            'id': security.id,
            'symbol': security.symbol,
            'name': security.name,
            'asset_type': security.asset_type,
            'exchange': security.exchange,
            'currency': security.currency,
        },
        'benchmark': {
            'id': benchmark.id,
            'symbol': benchmark.symbol,
            'name': benchmark.name,
        },
        'data_source': data_source,
        'summary': build_summary(hybrid, core_only, buy_and_hold),
    }
