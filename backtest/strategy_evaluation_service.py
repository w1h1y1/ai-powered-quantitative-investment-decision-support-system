"""Server-selected historical strategy evaluation.

The current Market Regime selects one registered strategy.  The selected
strategy is then evaluated on historical data as decision-support evidence;
the evaluation never overrides Strategy Selection and never places orders in
the portfolio subsystem.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from market.regime_service import get_market_regime
from market.services import subtract_years
from market.strategy_selection_service import (
    STRATEGIES,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    select_strategy,
)

from .services import (
    ATR_PERIOD,
    BOLLINGER_PERIOD,
    RSI_PERIOD,
    ZERO,
    BacktestDataError,
    BacktestInsufficientHistoryError,
    StrategyParameters,
    build_history_status,
    build_indicator_inputs,
    calculate_atr,
    calculate_bollinger_lower,
    calculate_bollinger_upper,
    calculate_curve_metrics,
    calculate_required_warmup_trading_days,
    calculate_rsi,
    calculate_simple_moving_average,
    calculate_warmup_calendar_days,
    calculate_warmup_start_date,
    format_decimal,
    format_quantity,
    load_daily_backtest_bars,
    quantize_money,
    quantize_quantity,
    simulate_layered_strategy,
)


EVALUATION_STATUS_COMPLETED = 'completed'
EVALUATION_STATUS_NOT_APPLICABLE = 'not_applicable'
EVALUATION_STATUS_UNAVAILABLE = 'unavailable'

MEAN_REVERSION_MA_PERIOD = 20
MEAN_REVERSION_RSI_ENTRY = Decimal('35')
MEAN_REVERSION_RSI_EXIT = Decimal('55')
MEAN_REVERSION_BOLLINGER_MULTIPLIER = Decimal('2')
MEAN_REVERSION_RISK_FRACTION = Decimal('0.01')
MEAN_REVERSION_ATR_MULTIPLIER = Decimal('2')
MEAN_REVERSION_MAX_EXPOSURE = Decimal('0.50')
MEAN_REVERSION_WARMUP_SAFETY_ROWS = 20
MEAN_REVERSION_LAYER = 'MEAN_REVERSION'


class StrategyEvaluationContractError(BacktestDataError):
    """Raised when an evaluation request conflicts with point-in-time rules."""


@dataclass(frozen=True)
class StrategyEvaluatorRegistration:
    strategy_id: str
    evaluator: object
    active_backtest: bool


def _security_payload(security):
    return {
        'id': security.id,
        'symbol': security.symbol,
        'name': security.name,
        'asset_type': security.asset_type,
        'exchange': security.exchange,
        'currency': security.currency,
    }


def _benchmark_payload(benchmark, *, used_by_strategy):
    return {
        'id': benchmark.id,
        'symbol': benchmark.symbol,
        'name': benchmark.name,
        'used_by_strategy': used_by_strategy,
    }


def _format_active_evaluation(
    *,
    strategy_id,
    result,
    initial_capital,
    security,
    benchmark,
    benchmark_used,
    strategy_parameters,
    data_source,
):
    points = result['equity_curve']
    return {
        'evaluation_available': True,
        'evaluation_status': EVALUATION_STATUS_COMPLETED,
        'evaluation_unavailable_reason': None,
        'evaluation_strategy': strategy_id,
        'initial_capital': format_decimal(initial_capital),
        'final_equity': format_decimal(result['final_equity']),
        'total_return': format_decimal(result['total_return']),
        'maximum_drawdown': format_decimal(result['maximum_drawdown']),
        'annualized_volatility': format_decimal(result['annualized_volatility']),
        'total_fees': format_decimal(result['total_fees']),
        'executed_order_count': result['executed_order_count'],
        'equity_curve': points,
        'drawdown_curve': [
            {'date': point['date'], 'drawdown': point['drawdown']}
            for point in points
        ],
        'trades': result['trades'],
        'signal_message': (
            f'No qualifying {strategy_id.replace("_", " ").title()} signals '
            'under the fixed v1 rules.'
            if not result['trades']
            else ''
        ),
        'strategy_parameters': strategy_parameters,
        'security': _security_payload(security),
        'benchmark': _benchmark_payload(
            benchmark,
            used_by_strategy=benchmark_used,
        ),
        'data_source': data_source,
    }


def _prepare_trend_following_data(
    *,
    security,
    benchmark,
    start_date,
    end_date,
    parameters,
):
    required_warmup_rows = calculate_required_warmup_trading_days(parameters)
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

    asset_history = build_history_status(security, asset_bars, start_date, asset_source)
    benchmark_history = build_history_status(
        benchmark,
        benchmark_bars,
        start_date,
        benchmark_source,
    )
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

    return {
        'bars': asset_bars,
        'indicators': build_indicator_inputs(asset_bars, benchmark_bars, parameters),
        'data_source': {
            **asset_source,
            'requested_start_date': start_date.isoformat(),
            'requested_end_date': end_date.isoformat(),
            'warmup_start_date': warmup_start_date.isoformat(),
            'warmup_trading_days': required_warmup_rows,
            'warmup_calendar_days': calculate_warmup_calendar_days(required_warmup_rows),
            'benchmark': benchmark_source,
        },
    }


def evaluate_trend_following(
    *,
    security,
    benchmark,
    start_date,
    end_date,
    initial_capital,
    transaction_fee,
):
    """Evaluate the established Core-only medium-term trend logic."""

    parameters = StrategyParameters()
    prepared = _prepare_trend_following_data(
        security=security,
        benchmark=benchmark,
        start_date=start_date,
        end_date=end_date,
        parameters=parameters,
    )
    result = simulate_layered_strategy(
        bars=prepared['bars'],
        indicators=prepared['indicators'],
        start_date=start_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
        parameters=parameters,
        enable_swing=False,
    )
    points = result['equity_curve']
    if not points or any(point['market_regime'] is None for point in points):
        raise BacktestDataError(
            'Not enough benchmark history to calculate the trend evaluator regime.'
        )
    prepared['data_source']['actual_start_date'] = points[0]['date']
    prepared['data_source']['actual_end_date'] = points[-1]['date']

    return _format_active_evaluation(
        strategy_id=STRATEGY_TREND_FOLLOWING,
        result=result,
        initial_capital=initial_capital,
        security=security,
        benchmark=benchmark,
        benchmark_used=True,
        strategy_parameters={
            'strategy': 'Core-Only Medium-Term Trend Following',
            'strategy_id': STRATEGY_TREND_FOLLOWING,
            'adapter': 'existing_core_only',
            'core_fast_ma': parameters.core_fast_ma,
            'core_slow_ma': parameters.core_slow_ma,
            'risk_fraction': format_decimal(parameters.core_risk_percentage),
            'atr_multiplier': format_decimal(parameters.core_atr_multiplier),
            'max_exposure': format_decimal(parameters.max_core_exposure),
            'execution_rule': (
                'Signals use signal-date close data and execute at the next trading day open.'
            ),
        },
        data_source=prepared['data_source'],
    )


def _mean_reversion_trade(
    *,
    index,
    signal_date,
    execution_bar,
    trade_type,
    reason,
    quantity,
    execution_price,
    fee,
    cash_after,
    position_after,
    realized_profit_loss,
    sizing=None,
):
    sizing = sizing or {}
    return {
        'id': f'mean-reversion-trade-{index}',
        'position_layer': MEAN_REVERSION_LAYER,
        'reason': reason,
        'signal_date': signal_date.isoformat(),
        'execution_date': execution_bar.date.isoformat(),
        'type': trade_type,
        'execution_price': format_decimal(execution_price),
        'quantity': format_quantity(quantity),
        'fee': format_decimal(fee),
        'cash_after': format_decimal(cash_after),
        'position_after': format_quantity(position_after),
        'realized_profit_loss': format_decimal(realized_profit_loss),
        'equity_before': format_decimal(sizing.get('equity_before')),
        'risk_fraction': format_decimal(sizing.get('risk_fraction')),
        'risk_amount': format_decimal(sizing.get('risk_amount')),
        'atr': format_decimal(sizing.get('atr')),
        'stop_distance': format_decimal(sizing.get('stop_distance')),
        'raw_quantity': (
            None
            if sizing.get('raw_quantity') is None
            else format_quantity(sizing['raw_quantity'])
        ),
        'affordable_quantity': (
            None
            if sizing.get('affordable_quantity') is None
            else format_quantity(sizing['affordable_quantity'])
        ),
        'exposure_capped_quantity': (
            None
            if sizing.get('exposure_capped_quantity') is None
            else format_quantity(sizing['exposure_capped_quantity'])
        ),
        'final_quantity': format_quantity(sizing.get('final_quantity', quantity)),
        'exposure_cap_applied': bool(sizing.get('exposure_cap_applied', False)),
        'cash_cap_applied': bool(sizing.get('cash_cap_applied', False)),
    }


def simulate_mean_reversion(
    *,
    bars,
    start_date,
    initial_capital,
    transaction_fee,
    ma20,
    rsi14,
    atr14,
    bollinger_upper,
    bollinger_lower,
):
    """Run the independent v1 long-only Mean Reversion strategy.

    Every signal is formed from the current close and trailing indicators.  It
    is queued and can only execute on the next bar's open.
    """

    start_index = next(
        (index for index, bar in enumerate(bars) if bar.date >= start_date),
        None,
    )
    if start_index is None:
        raise BacktestDataError(
            'No security prices are available inside the requested evaluation period.'
        )
    required = (ma20, rsi14, atr14, bollinger_upper, bollinger_lower)
    if any(series[start_index] is None for series in required):
        raise BacktestDataError(
            'Not enough warm-up history to calculate Mean Reversion indicators.'
        )

    cash = Decimal(initial_capital)
    quantity = ZERO
    average_cost = ZERO
    fixed_stop = None
    pending_order = None
    trades = []
    equity_curve = []
    equity_values = []
    total_fees = ZERO
    trade_index = 1

    for index in range(start_index, len(bars)):
        bar = bars[index]

        if pending_order is not None:
            execution_price = bar.open
            equity_before = cash + (quantity * execution_price)
            if pending_order['type'] == 'BUY' and quantity <= ZERO:
                stop_distance = pending_order['atr'] * MEAN_REVERSION_ATR_MULTIPLIER
                if stop_distance > ZERO and cash > transaction_fee:
                    risk_amount = equity_before * MEAN_REVERSION_RISK_FRACTION
                    raw_quantity = risk_amount / stop_distance
                    affordable_quantity = (cash - transaction_fee) / execution_price
                    exposure_capped_quantity = (
                        equity_before * MEAN_REVERSION_MAX_EXPOSURE / execution_price
                    )
                    bought_quantity = quantize_quantity(min(
                        raw_quantity,
                        affordable_quantity,
                        exposure_capped_quantity,
                    ))
                    if bought_quantity > ZERO:
                        gross_amount = bought_quantity * execution_price
                        cash = quantize_money(cash - gross_amount - transaction_fee)
                        quantity = bought_quantity
                        average_cost = (gross_amount + transaction_fee) / quantity
                        fixed_stop = execution_price - stop_distance
                        total_fees += transaction_fee
                        trades.append(_mean_reversion_trade(
                            index=trade_index,
                            signal_date=pending_order['signal_date'],
                            execution_bar=bar,
                            trade_type='BUY',
                            reason=pending_order['reason'],
                            quantity=quantity,
                            execution_price=execution_price,
                            fee=transaction_fee,
                            cash_after=cash,
                            position_after=quantity,
                            realized_profit_loss=ZERO,
                            sizing={
                                'equity_before': equity_before,
                                'risk_fraction': MEAN_REVERSION_RISK_FRACTION,
                                'risk_amount': risk_amount,
                                'atr': pending_order['atr'],
                                'stop_distance': stop_distance,
                                'raw_quantity': raw_quantity,
                                'affordable_quantity': affordable_quantity,
                                'exposure_capped_quantity': exposure_capped_quantity,
                                'final_quantity': quantity,
                                'exposure_cap_applied': (
                                    exposure_capped_quantity < raw_quantity
                                    and exposure_capped_quantity <= affordable_quantity
                                ),
                                'cash_cap_applied': (
                                    affordable_quantity < raw_quantity
                                    and affordable_quantity < exposure_capped_quantity
                                ),
                            },
                        ))
                        trade_index += 1
            elif pending_order['type'] == 'SELL' and quantity > ZERO:
                sold_quantity = quantity
                gross_amount = sold_quantity * execution_price
                realized_profit_loss = (
                    gross_amount - transaction_fee - (sold_quantity * average_cost)
                )
                cash = quantize_money(cash + gross_amount - transaction_fee)
                total_fees += transaction_fee
                quantity = ZERO
                average_cost = ZERO
                fixed_stop = None
                trades.append(_mean_reversion_trade(
                    index=trade_index,
                    signal_date=pending_order['signal_date'],
                    execution_bar=bar,
                    trade_type='SELL',
                    reason=pending_order['reason'],
                    quantity=sold_quantity,
                    execution_price=execution_price,
                    fee=transaction_fee,
                    cash_after=cash,
                    position_after=ZERO,
                    realized_profit_loss=realized_profit_loss,
                    sizing={
                        'equity_before': equity_before,
                        'risk_fraction': MEAN_REVERSION_RISK_FRACTION,
                        'final_quantity': sold_quantity,
                    },
                ))
                trade_index += 1
            pending_order = None

        holdings_value = quantity * bar.close
        total_equity = cash + holdings_value
        equity_values.append(total_equity)
        exposure = (
            ZERO
            if total_equity <= ZERO
            else (holdings_value / total_equity) * Decimal('100')
        )
        equity_curve.append({
            'date': bar.date.isoformat(),
            'close': format_decimal(bar.close),
            'cash': format_decimal(cash),
            'holdings_value': format_decimal(holdings_value),
            'total_equity': format_decimal(total_equity),
            'position_quantity': format_quantity(quantity),
            'average_cost': format_decimal(average_cost),
            'exposure': format_decimal(exposure),
            'ma20': format_decimal(ma20[index]),
            'rsi14': format_decimal(rsi14[index]),
            'atr14': format_decimal(atr14[index]),
            'bollinger_upper': format_decimal(bollinger_upper[index]),
            'bollinger_lower': format_decimal(bollinger_lower[index]),
            'drawdown': None,
        })

        if quantity > ZERO:
            if fixed_stop is not None and bar.close <= fixed_stop:
                pending_order = {
                    'type': 'SELL',
                    'reason': 'MEAN_REVERSION_EXIT_ATR_RISK',
                    'signal_date': bar.date,
                }
            elif bar.close >= ma20[index] or rsi14[index] >= MEAN_REVERSION_RSI_EXIT:
                pending_order = {
                    'type': 'SELL',
                    'reason': 'MEAN_REVERSION_EXIT_MEAN_REACHED',
                    'signal_date': bar.date,
                }
        elif (
            atr14[index] is not None
            and atr14[index] > ZERO
            and rsi14[index] <= MEAN_REVERSION_RSI_ENTRY
            and bar.close <= bollinger_lower[index]
        ):
            pending_order = {
                'type': 'BUY',
                'reason': 'MEAN_REVERSION_ENTRY_OVERSOLD_LOWER_BAND',
                'signal_date': bar.date,
                'atr': atr14[index],
            }

    metrics = calculate_curve_metrics(equity_values, initial_capital)
    for point, drawdown in zip(equity_curve, metrics['drawdowns']):
        point['drawdown'] = format_decimal(drawdown)
    return {
        **metrics,
        'equity_curve': equity_curve,
        'trades': trades,
        'total_fees': total_fees,
        'executed_order_count': len(trades),
    }


def evaluate_mean_reversion(
    *,
    security,
    benchmark,
    start_date,
    end_date,
    initial_capital,
    transaction_fee,
):
    """Evaluate independent RSI/Bollinger/ATR Mean Reversion v1."""

    required_warmup_rows = max(
        MEAN_REVERSION_MA_PERIOD,
        RSI_PERIOD,
        ATR_PERIOD,
        BOLLINGER_PERIOD,
    ) + MEAN_REVERSION_WARMUP_SAFETY_ROWS
    warmup_start_date = calculate_warmup_start_date(start_date, required_warmup_rows)
    bars, asset_source = load_daily_backtest_bars(
        security,
        warmup_start_date,
        end_date,
        requested_start_date=start_date,
        required_warmup_rows=required_warmup_rows,
        data_label='selected security',
    )
    asset_history = build_history_status(security, bars, start_date, asset_source)
    if asset_history['available_rows'] < required_warmup_rows:
        raise BacktestInsufficientHistoryError(
            asset=asset_history,
            benchmark=asset_history,
            required_warmup_rows=required_warmup_rows,
            requested_start_date=start_date,
            warmup_start_date=warmup_start_date,
        )

    ma20 = calculate_simple_moving_average(bars, MEAN_REVERSION_MA_PERIOD)
    rsi14 = calculate_rsi(bars, RSI_PERIOD)
    atr14 = calculate_atr(bars, ATR_PERIOD)
    bollinger_upper = calculate_bollinger_upper(
        bars,
        BOLLINGER_PERIOD,
        MEAN_REVERSION_BOLLINGER_MULTIPLIER,
    )
    bollinger_lower = calculate_bollinger_lower(
        bars,
        BOLLINGER_PERIOD,
        MEAN_REVERSION_BOLLINGER_MULTIPLIER,
    )
    result = simulate_mean_reversion(
        bars=bars,
        start_date=start_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
        ma20=ma20,
        rsi14=rsi14,
        atr14=atr14,
        bollinger_upper=bollinger_upper,
        bollinger_lower=bollinger_lower,
    )
    points = result['equity_curve']
    data_source = {
        **asset_source,
        'requested_start_date': start_date.isoformat(),
        'requested_end_date': end_date.isoformat(),
        'actual_start_date': points[0]['date'],
        'actual_end_date': points[-1]['date'],
        'warmup_start_date': warmup_start_date.isoformat(),
        'warmup_trading_days': required_warmup_rows,
        'warmup_calendar_days': calculate_warmup_calendar_days(required_warmup_rows),
        'benchmark': None,
    }
    return _format_active_evaluation(
        strategy_id=STRATEGY_MEAN_REVERSION,
        result=result,
        initial_capital=initial_capital,
        security=security,
        benchmark=benchmark,
        benchmark_used=False,
        strategy_parameters={
            'strategy': 'Independent Mean Reversion v1',
            'strategy_id': STRATEGY_MEAN_REVERSION,
            'entry_rule': (
                'Close at or below the 20-day lower Bollinger Band and RSI14 at or below 35.'
            ),
            'exit_rule': (
                'Close reaches the 20-day mean, RSI14 reaches 55, or the fixed ATR stop is hit.'
            ),
            'rsi_entry_level': format_decimal(MEAN_REVERSION_RSI_ENTRY),
            'rsi_exit_level': format_decimal(MEAN_REVERSION_RSI_EXIT),
            'bollinger_period': BOLLINGER_PERIOD,
            'bollinger_multiplier': format_decimal(MEAN_REVERSION_BOLLINGER_MULTIPLIER),
            'risk_fraction': format_decimal(MEAN_REVERSION_RISK_FRACTION),
            'atr_multiplier': format_decimal(MEAN_REVERSION_ATR_MULTIPLIER),
            'max_exposure': format_decimal(MEAN_REVERSION_MAX_EXPOSURE),
            'execution_rule': (
                'Signals use signal-date close data and execute at the next trading day open.'
            ),
        },
        data_source=data_source,
    )


# The complete evaluation dispatch contract is centralized here.  Risk-Off is
# registered explicitly but has no evaluator because it is a defensive state,
# not an active historical trading strategy.
STRATEGY_EVALUATOR_REGISTRY = {
    STRATEGY_TREND_FOLLOWING: StrategyEvaluatorRegistration(
        strategy_id=STRATEGY_TREND_FOLLOWING,
        evaluator=evaluate_trend_following,
        active_backtest=True,
    ),
    STRATEGY_MEAN_REVERSION: StrategyEvaluatorRegistration(
        strategy_id=STRATEGY_MEAN_REVERSION,
        evaluator=evaluate_mean_reversion,
        active_backtest=True,
    ),
    STRATEGY_RISK_OFF: StrategyEvaluatorRegistration(
        strategy_id=STRATEGY_RISK_OFF,
        evaluator=None,
        active_backtest=False,
    ),
}


def _empty_evaluation_fields(*, status, reason):
    return {
        'evaluation_available': False,
        'evaluation_status': status,
        'evaluation_unavailable_reason': reason,
        'evaluation_strategy': None,
        'initial_capital': None,
        'final_equity': None,
        'total_return': None,
        'maximum_drawdown': None,
        'annualized_volatility': None,
        'total_fees': None,
        'executed_order_count': None,
        'equity_curve': [],
        'drawdown_curve': [],
        'trades': [],
        'signal_message': '',
        'strategy_parameters': None,
        'security': None,
        'benchmark': None,
        'data_source': None,
    }


def _parse_latest_market_date(market_regime_result):
    value = market_regime_result.get('latest_market_date')
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def evaluate_selected_strategy(
    *,
    security,
    benchmark,
    start_date=None,
    end_date=None,
    initial_capital=Decimal('10000'),
    transaction_fee=Decimal('1.00'),
    market_regime_result=None,
    strategy_selection_result=None,
):
    """Run Market Regime -> Strategy Selection -> registered evaluator.

    Callers may supply ``market_regime_result`` and ``strategy_selection_result``
    to reuse already-computed deterministic results.  When omitted, the function
    keeps its original behavior and computes both itself.  The optional results
    must come from the formal Market Regime and Strategy Selection services so
    that evaluation never introduces a second interpretation of the regime.
    """

    if market_regime_result is None:
        market_regime_result = get_market_regime(security)
    if strategy_selection_result is None:
        strategy_selection = select_strategy(market_regime_result)
    else:
        strategy_selection = strategy_selection_result
    provenance = {
        **strategy_selection,
        'market_regime_latest_market_date': market_regime_result.get(
            'latest_market_date'
        ),
        'evaluation_scope': 'historical_evidence_for_current_strategy_selection',
    }

    if strategy_selection.get('strategy_selection_available') is not True:
        return {
            **provenance,
            **_empty_evaluation_fields(
                status=EVALUATION_STATUS_UNAVAILABLE,
                reason=(
                    strategy_selection.get('strategy_selection_unavailable_reason')
                    or 'strategy_selection_unavailable'
                ),
            ),
            'evaluation_window': None,
        }

    selected_strategy = strategy_selection.get('selected_strategy')
    registration = STRATEGY_EVALUATOR_REGISTRY.get(selected_strategy)
    if registration is None:
        return {
            **provenance,
            **_empty_evaluation_fields(
                status=EVALUATION_STATUS_UNAVAILABLE,
                reason='strategy_evaluator_unavailable',
            ),
            'evaluation_window': None,
        }

    if not registration.active_backtest:
        return {
            **provenance,
            **_empty_evaluation_fields(
                status=EVALUATION_STATUS_NOT_APPLICABLE,
                reason=(
                    'Risk-Off is a defensive state rather than an active trading strategy.'
                ),
            ),
            'evaluation_window': None,
        }

    latest_market_date = _parse_latest_market_date(market_regime_result)
    if latest_market_date is None:
        return {
            **provenance,
            **_empty_evaluation_fields(
                status=EVALUATION_STATUS_UNAVAILABLE,
                reason='market_regime_latest_date_unavailable',
            ),
            'evaluation_window': None,
        }

    if (start_date is None) != (end_date is None):
        raise StrategyEvaluationContractError(
            'start_date and end_date must be supplied together.'
        )
    if end_date is None:
        end_date = latest_market_date
        start_date = subtract_years(latest_market_date, 1)
    elif end_date != latest_market_date:
        raise StrategyEvaluationContractError(
            'end_date must match the Market Regime latest_market_date because '
            'historical as-of Market Regime selection is not implemented.'
        )
    if start_date >= end_date:
        raise StrategyEvaluationContractError(
            'Start date must be earlier than end date.'
        )

    evaluation = registration.evaluator(
        security=security,
        benchmark=benchmark,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        transaction_fee=transaction_fee,
    )
    return {
        **provenance,
        **evaluation,
        'evaluation_window': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        },
    }


if set(STRATEGY_EVALUATOR_REGISTRY) != set(STRATEGIES):
    raise RuntimeError('Strategy evaluator registry must cover every formal strategy.')


__all__ = [
    'EVALUATION_STATUS_COMPLETED',
    'EVALUATION_STATUS_NOT_APPLICABLE',
    'EVALUATION_STATUS_UNAVAILABLE',
    'STRATEGY_EVALUATOR_REGISTRY',
    'StrategyEvaluationContractError',
    'evaluate_mean_reversion',
    'evaluate_selected_strategy',
    'evaluate_trend_following',
    'simulate_mean_reversion',
]
