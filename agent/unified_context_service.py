"""Unified deterministic context for the future AI Agent.

This module assembles one structured snapshot from existing Django services.
It never recalculates regime, never replaces indicator formulas, and never
produces investment advice.
"""

from datetime import date
from decimal import Decimal

from backtest.services import (
    BacktestDataError,
    BacktestInsufficientHistoryError,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
    StrategyParameters,
    calculate_macd,
    calculate_simple_moving_average,
    run_market_regime_core_swing_backtest,
)
from market.models import SecurityDailyPrice
from market.regime_config import (
    BROAD_MARKET_SYMBOL,
    get_sector_benchmark,
    get_security_sector,
)
from market.regime_service import ensure_benchmark_security, get_market_regime
from market.services import subtract_years
from portfolio.services import get_portfolio_summary


AGENT_UNIFIED_CONTEXT_VERSION = 'agent_context_v1'

REGIME_DIRECTION_LABELS = {
    'bullish_trend': 'Bullish',
    'bearish_trend': 'Bearish',
    'sideways_range': 'Sideways',
    'high_volatility': 'High Volatility',
}

TREND_DIRECTION_LABELS = {
    'bullish': 'Bullish',
    'bearish': 'Bearish',
    'mixed': 'Mixed',
    'neutral': 'Neutral',
}

CONFIRMATION_LEVEL_WEAK = 'Weak'
CONFIRMATION_LEVEL_NEUTRAL = 'Neutral'
CONFIRMATION_LEVEL_STRONG = 'Strong'
CONFIRMATION_WEAK_THRESHOLD = 0.4
CONFIRMATION_STRONG_THRESHOLD = 0.6


def _number(value, digits=4):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _strings(value):
    return [
        item
        for item in (value or [])
        if isinstance(item, str) and item.strip()
    ]


def _asset_type_label(asset_type):
    if asset_type == 'STOCK':
        return 'Stock'
    if asset_type == 'ETF':
        return 'ETF'
    return asset_type


def _direction_from_regime(regime):
    return REGIME_DIRECTION_LABELS.get(regime)


def _confirmation_level(score):
    value = _number(score, 6)
    if value is None:
        return None
    if value < CONFIRMATION_WEAK_THRESHOLD:
        return CONFIRMATION_LEVEL_WEAK
    if value < CONFIRMATION_STRONG_THRESHOLD:
        return CONFIRMATION_LEVEL_NEUTRAL
    return CONFIRMATION_LEVEL_STRONG


def _bars(security, limit=260):
    prices = list(
        SecurityDailyPrice.objects
        .filter(security=security)
        .order_by('-date')[:limit],
    )
    prices.reverse()
    return prices


def _security_payload(security):
    sector, _sector_source = get_security_sector(security)
    return {
        'symbol': security.symbol,
        'name': security.name,
        'asset_type': _asset_type_label(security.asset_type),
        'exchange': security.exchange,
        'currency': security.currency,
        'sector': sector,
        'sector_benchmark': get_sector_benchmark(sector),
    }


def _market_data_payload(security):
    bars = _bars(security)
    if not bars:
        return {
            'available': False,
            'unavailable_reason': 'Insufficient historical data.',
            'latest_market_date': None,
            'latest_close': None,
            'history_count': 0,
        }
    latest = bars[-1]
    raw_close = latest.close
    raw_open = latest.open
    if raw_close > raw_open:
        direction = 'Up'
    elif raw_close < raw_open:
        direction = 'Down'
    else:
        direction = 'Flat'
    change = raw_close - raw_open
    change_percent = (
        (raw_close / raw_open) - 1
        if raw_open
        else None
    )
    return {
        'available': True,
        'latest_market_date': latest.date.isoformat(),
        'latest_open': _number(latest.open, 4),
        'latest_high': _number(latest.high, 4),
        'latest_low': _number(latest.low, 4),
        'latest_close': _number(latest.close, 4),
        'latest_volume': int(latest.volume or 0),
        'open_to_close_change': _number(change, 4),
        'open_to_close_change_percent': _number(change_percent, 6),
        'open_to_close_direction': direction,
        'history_count': len(bars),
    }


def _technical_payload(security, market_regime_result):
    bars = _bars(security)
    if not bars:
        return {
            'available': False,
            'unavailable_reason': 'Insufficient historical data.',
        }

    ma20 = calculate_simple_moving_average(bars, 20)
    ma60 = calculate_simple_moving_average(bars, 60)
    ma200 = calculate_simple_moving_average(bars, 200)
    macd, macd_signal, macd_histogram = calculate_macd(bars)
    close = bars[-1].close

    def price_vs_ma(ma_value):
        if ma_value is None:
            return None
        try:
            return round(float((close / ma_value) - 1), 6)
        except (TypeError, ZeroDivisionError):
            return None

    trend = market_regime_result.get('trend') or {}
    momentum = market_regime_result.get('momentum') or {}
    volatility = market_regime_result.get('volatility') or {}

    return {
        'available': True,
        'moving_averages': {
            'ma20': _number(ma20[-1], 4),
            'ma60': _number(ma60[-1], 4),
            'ma200': _number(ma200[-1], 4),
            'price_vs_ma20': price_vs_ma(ma20[-1]),
            'price_vs_ma60': price_vs_ma(ma60[-1]),
            'price_vs_ma200': price_vs_ma(ma200[-1]),
        },
        'momentum': {
            'rsi': _number(momentum.get('rsi'), 4),
            'macd': _number(macd[-1], 6),
            'macd_signal': _number(macd_signal[-1], 6),
            'macd_histogram': _number(
                momentum.get('macd_histogram', macd_histogram[-1]),
                6,
            ),
        },
        'trend': {
            'adx': _number(trend.get('adx'), 4),
        },
        'volatility': {
            'atr': _number(volatility.get('atr'), 4),
        },
    }


def _market_regime_payload(market_regime_result):
    trend = market_regime_result.get('trend') or {}
    range_data = market_regime_result.get('range') or {}
    volatility = market_regime_result.get('volatility') or {}
    return {
        'available': market_regime_result.get('regime_available') is True,
        'unavailable_reason': market_regime_result.get('regime_unavailable_reason'),
        'regime': market_regime_result.get('regime'),
        'confidence': market_regime_result.get('confidence'),
        'confidence_score': _number(market_regime_result.get('confidence_score'), 6),
        'direction': TREND_DIRECTION_LABELS.get(trend.get('direction')),
        'explanation': _strings(market_regime_result.get('explanation')),
        'trend_score': _number(trend.get('score'), 6),
        'choppiness': _number(range_data.get('choppiness'), 4),
        'volatility': {
            'atr_percent': _number(volatility.get('atr_percent'), 6),
            'realized_volatility_20d': _number(
                volatility.get('realized_volatility_20d'),
                6,
            ),
            'volatility_percentile': _number(
                volatility.get('volatility_percentile'),
                6,
            ),
            'percentile_available': volatility.get('percentile_available') is True,
        },
    }


def _market_context_payload(market_regime_result):
    context = market_regime_result.get('market_context') or {}
    broad_available = context.get('broad_market_context_available') is True
    sector_available = context.get('sector_context_available') is True
    return {
        'broad_market': {
            'symbol': context.get('broad_market') or BROAD_MARKET_SYMBOL,
            'available': broad_available,
            'regime': context.get('spy_regime'),
            'direction': _direction_from_regime(context.get('spy_regime')),
        },
        'sector': {
            'name': context.get('sector'),
            'benchmark': context.get('sector_benchmark'),
            'available': sector_available,
            'regime': context.get('sector_regime'),
            'direction': _direction_from_regime(context.get('sector_regime')),
        },
        'confirmation': {
            'score': _number(context.get('confirmation_score'), 6),
            'level': _confirmation_level(context.get('confirmation_score')),
        },
    }


def _portfolio_payload(user, security):
    try:
        summary = get_portfolio_summary(user)
    except Exception:
        return {
            'available': False,
            'unavailable_reason': 'Portfolio data unavailable.',
        }

    allocations = summary.get('allocations') or []
    matching = next(
        (item for item in allocations if item.get('symbol') == security.symbol),
        None,
    )
    payload = {
        'available': True,
        'remaining_liquidity': _number(summary.get('available_liquidity'), 2),
        'portfolio_total_value': _number(summary.get('total_asset_value'), 4),
    }
    if matching is None:
        payload.update({
            'has_position': False,
            'quantity': 0,
            'market_value': 0,
            'portfolio_weight': 0,
        })
        return payload

    market_value = _number(matching.get('market_value'), 4)
    total_value = _number(summary.get('total_asset_value'), 4)
    weight = None
    if market_value is not None and total_value:
        weight = round(market_value / total_value, 6)
    payload.update({
        'has_position': True,
        'quantity': _number(matching.get('quantity'), 6),
        'average_cost': _number(matching.get('average_price'), 4),
        'market_value': market_value,
        'unrealized_pnl': _number(matching.get('unrealized_profit_loss'), 4),
        'portfolio_weight': weight,
        'valuation_price': _number(matching.get('current_price'), 4),
        'valuation_as_of_date': matching.get('current_price_as_of') or None,
        'valuation_source': matching.get('current_price_source') or None,
        'valuation_is_stale': matching.get('current_price_is_stale') is True,
    })
    return payload


def _backtest_payload(security, benchmark, latest_date):
    if latest_date is None:
        return {
            'available': False,
            'unavailable_reason': 'Insufficient historical data.',
        }
    try:
        end_date = date.fromisoformat(str(latest_date))
    except (TypeError, ValueError):
        return {
            'available': False,
            'unavailable_reason': 'Backtest context unavailable.',
        }
    start_date = subtract_years(end_date, 1)
    try:
        result = run_market_regime_core_swing_backtest(
            security=security,
            benchmark=benchmark,
            start_date=start_date,
            end_date=end_date,
            initial_capital=Decimal('10000'),
            transaction_fee=Decimal('1.00'),
            parameters=StrategyParameters(),
        )
    except BacktestInsufficientHistoryError:
        return {
            'available': False,
            'unavailable_reason': 'Insufficient historical data.',
        }
    except (
        BacktestDataError,
        BacktestMarketDataRateLimited,
        BacktestMarketDataUnavailable,
    ):
        return {
            'available': False,
            'unavailable_reason': 'Backtest context unavailable.',
        }

    return {
        'available': True,
        'source': 'market_regime_hybrid_backtest',
        'strategy': 'Market-Regime Hybrid Strategy (Core + Swing)',
        'strategy_components': ['Core', 'Swing'],
        'benchmark': getattr(benchmark, 'symbol', None),
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'initial_capital': 10000.0,
        'total_return': _number(result.get('total_return'), 6),
        'max_drawdown': _number(result.get('maximum_drawdown'), 6),
        'annualized_volatility': _number(result.get('annualized_volatility'), 6),
        'total_fees': _number(result.get('total_fees'), 4),
        'trade_count': _number(result.get('executed_order_count'), 0),
        'win_rate': _number(result.get('swing_win_rate'), 4),
    }


def _data_quality_payload(
    *,
    market_data,
    technical_analysis,
    market_regime,
    market_context,
    portfolio_context,
    backtest_context,
):
    broad_available = market_context['broad_market']['available']
    sector_available = market_context['sector']['available']
    return {
        'market_data_available': market_data.get('available') is True,
        'technical_analysis_available': technical_analysis.get('available') is True,
        'market_regime_available': market_regime.get('available') is True,
        'market_context_available': broad_available and sector_available,
        'portfolio_context_available': portfolio_context.get('available') is True,
        'backtest_context_available': backtest_context.get('available') is True,
    }


def build_unified_agent_context(security, user, *, benchmark=None):
    """Assemble one structured Agent Context for a security and user."""

    benchmark_security = benchmark
    if benchmark_security is None:
        benchmark_security = ensure_benchmark_security(BROAD_MARKET_SYMBOL)

    market_regime_result = get_market_regime(security)
    market_data = _market_data_payload(security)
    technical_analysis = _technical_payload(security, market_regime_result)
    market_regime = _market_regime_payload(market_regime_result)
    market_context = _market_context_payload(market_regime_result)
    portfolio_context = _portfolio_payload(user, security)
    as_of_date = (
        market_regime_result.get('latest_market_date')
        or market_data.get('latest_market_date')
    )
    backtest_context = _backtest_payload(
        security,
        benchmark_security,
        as_of_date,
    )
    return {
        'symbol': security.symbol,
        'as_of_date': as_of_date,
        'context_version': AGENT_UNIFIED_CONTEXT_VERSION,
        'security': _security_payload(security),
        'market_data': market_data,
        'technical_analysis': technical_analysis,
        'market_regime': market_regime,
        'market_context': market_context,
        'portfolio_context': portfolio_context,
        'backtest_context': backtest_context,
        'data_quality': _data_quality_payload(
            market_data=market_data,
            technical_analysis=technical_analysis,
            market_regime=market_regime,
            market_context=market_context,
            portfolio_context=portfolio_context,
            backtest_context=backtest_context,
        ),
    }


__all__ = [
    'AGENT_UNIFIED_CONTEXT_VERSION',
    'build_unified_agent_context',
]
