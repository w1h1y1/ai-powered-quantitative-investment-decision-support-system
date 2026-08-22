"""Unified deterministic evidence and preliminary assessment for the AI Agent.

This module assembles one structured snapshot from existing Django services.
It never recalculates regime, never replaces indicator formulas, and never
produces investment advice.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal

from backtest.services import (
    BacktestDataError,
    BacktestInsufficientHistoryError,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
    StrategyParameters,
    calculate_bollinger_lower,
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
from market.strategy_catalog import (
    AGENT_STRATEGY_IDS,
    STRATEGY_NO_STRATEGY,
    STRATEGY_RISK_OFF,
    get_agent_strategy_catalog,
    get_related_backtest_strategy,
)
from market.strategy_selection_service import select_strategy
from portfolio.services import get_portfolio_summary


AGENT_UNIFIED_CONTEXT_VERSION = 'agent_context_v2'
LLM_STRATEGY_CONTEXT_VERSION = 'llm_strategy_context_v1'

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
    bollinger_lower = calculate_bollinger_lower(bars)
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
    relative_strength = market_regime_result.get('relative_strength') or {}

    rsi = _number(momentum.get('rsi'), 4)
    lower_band = _number(bollinger_lower[-1], 4)
    latest_close = _number(close, 4)
    price_condition = (
        latest_close is not None and lower_band is not None
        and latest_close <= lower_band
    )
    rsi_condition = rsi is not None and rsi <= 35
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
            'rsi': rsi,
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
        'relative_performance': {
            'vs_spy_20d': _number(relative_strength.get('vs_spy_20d'), 6),
            'vs_spy_60d': _number(relative_strength.get('vs_spy_60d'), 6),
            'vs_sector_20d': _number(relative_strength.get('vs_sector_20d'), 6),
            'vs_sector_60d': _number(relative_strength.get('vs_sector_60d'), 6),
            'score': _number(relative_strength.get('score'), 6),
        },
        'mean_reversion_entry': {
            'bollinger_lower_20_2': lower_band,
            'rsi_entry_threshold': 35.0,
            'close_at_or_below_lower_band': price_condition,
            'rsi_at_or_below_threshold': rsi_condition,
            'entry_conditions_met': price_condition and rsi_condition,
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


def _quantitative_assessment_payload(market_regime, strategy_selection):
    return {
        'available': (
            market_regime.get('available') is True
            and strategy_selection.get('strategy_selection_available') is True
        ),
        'preliminary_regime': market_regime.get('regime'),
        'suggested_strategy': strategy_selection.get('selected_strategy'),
        'confidence': market_regime.get('confidence_score'),
        'confidence_label': market_regime.get('confidence'),
        'risk_off': strategy_selection.get('risk_off') is True,
        'allow_new_long': strategy_selection.get('allow_new_long') is True,
        'explanation': (
            _strings(market_regime.get('explanation'))
            + _strings(strategy_selection.get('reason'))
        ),
    }


def _hard_constraints_payload(strategy_selection, portfolio_context):
    allow_new_long = strategy_selection.get('allow_new_long') is True
    current_allowed = (
        list(AGENT_STRATEGY_IDS)
        if allow_new_long
        else [STRATEGY_RISK_OFF, STRATEGY_NO_STRATEGY]
    )
    active_strategy_ids = [
        definition['id']
        for definition in get_agent_strategy_catalog()
        if definition.get('executable') is True
    ]
    return {
        'allowed_strategies': list(AGENT_STRATEGY_IDS),
        'currently_allowed_strategies': current_allowed,
        'active_strategy_ids': active_strategy_ids,
        'execution_mode': strategy_selection.get('execution_mode') or 'long_only',
        'allow_new_long': allow_new_long,
        'risk_off': strategy_selection.get('risk_off') is True,
        'actual_trading_allowed': False,
        'portfolio_data_available': portfolio_context.get('available') is True,
    }


def _strategy_evidence_payload(backtest_context):
    """Describe comparison evidence without running two new strategy backtests."""

    unavailable_reason = 'strategy_specific_comparison_not_available'
    candidates = {}
    unavailable_reasons = {
        'defensive_state': 'defensive_state_not_backtestable',
        'abstention_state': 'abstention_state_not_backtestable',
    }
    for definition in get_agent_strategy_catalog():
        candidate_reason = (
            unavailable_reason
            if definition.get('backtest_available') is True
            else unavailable_reasons.get(
                definition.get('kind'), 'strategy_not_backtestable',
            )
        )
        candidates[definition['id']] = {
            'backtest_capability_available': definition.get('backtest_available') is True,
            'evidence_available': False,
            'unavailable_reason': candidate_reason,
            'total_return': None,
            'max_drawdown': None,
            'win_rate': None,
            'trade_count': None,
        }
    return {
        'backtest_evidence_available': False,
        'comparable_candidate_backtests_available': False,
        'comparison_unavailable_reason': unavailable_reason,
        'candidates': candidates,
        'related_hybrid_backtest': {
            **backtest_context,
            'comparable_for_candidate_selection': False,
            'comparison_note': (
                'This Core + Swing result is not a same-logic comparison '
                'between the independent Trend Following and Mean Reversion evaluators.'
            ),
        },
    }


def _available_strategies_payload(hard_constraints):
    currently_allowed = set(hard_constraints.get('currently_allowed_strategies') or [])
    return [
        {
            **definition,
            'currently_allowed': definition['id'] in currently_allowed,
        }
        for definition in get_agent_strategy_catalog()
    ]


def _evidence_catalog(
    *,
    market_data,
    technical_analysis,
    market_regime,
    market_context,
    quantitative_assessment,
    backtest_context,
):
    """Return the only factor/value pairs an LLM may cite numerically."""

    moving_averages = technical_analysis.get('moving_averages') or {}
    momentum = technical_analysis.get('momentum') or {}
    trend = technical_analysis.get('trend') or {}
    technical_volatility = technical_analysis.get('volatility') or {}
    relative = technical_analysis.get('relative_performance') or {}
    regime_volatility = market_regime.get('volatility') or {}
    confirmation = market_context.get('confirmation') or {}
    candidates = (
        ('Latest Price', market_data.get('latest_close'), 'market_data.latest_close'),
        ('Price Change', market_data.get('open_to_close_change'), 'market_data.open_to_close_change'),
        ('Price Change Percent', market_data.get('open_to_close_change_percent'), 'market_data.open_to_close_change_percent'),
        ('MA20', moving_averages.get('ma20'), 'technical_analysis.moving_averages.ma20'),
        ('MA60', moving_averages.get('ma60'), 'technical_analysis.moving_averages.ma60'),
        ('MA200', moving_averages.get('ma200'), 'technical_analysis.moving_averages.ma200'),
        ('RSI', momentum.get('rsi'), 'technical_analysis.momentum.rsi'),
        ('MACD', momentum.get('macd'), 'technical_analysis.momentum.macd'),
        ('MACD Signal', momentum.get('macd_signal'), 'technical_analysis.momentum.macd_signal'),
        ('MACD Histogram', momentum.get('macd_histogram'), 'technical_analysis.momentum.macd_histogram'),
        ('ADX', trend.get('adx'), 'technical_analysis.trend.adx'),
        ('Choppiness Index', market_regime.get('choppiness'), 'market_regime.choppiness'),
        ('ATR', technical_volatility.get('atr'), 'technical_analysis.volatility.atr'),
        ('ATR Percent', regime_volatility.get('atr_percent'), 'market_regime.volatility.atr_percent'),
        ('Realized Volatility 20D', regime_volatility.get('realized_volatility_20d'), 'market_regime.volatility.realized_volatility_20d'),
        ('Volatility Percentile', regime_volatility.get('volatility_percentile'), 'market_regime.volatility.volatility_percentile'),
        ('Relative to SPY 20D', relative.get('vs_spy_20d'), 'technical_analysis.relative_performance.vs_spy_20d'),
        ('Relative to SPY 60D', relative.get('vs_spy_60d'), 'technical_analysis.relative_performance.vs_spy_60d'),
        ('Relative to Sector 20D', relative.get('vs_sector_20d'), 'technical_analysis.relative_performance.vs_sector_20d'),
        ('Relative to Sector 60D', relative.get('vs_sector_60d'), 'technical_analysis.relative_performance.vs_sector_60d'),
        ('Market Confirmation Score', confirmation.get('score'), 'market_context.confirmation.score'),
        ('Preliminary Regime', quantitative_assessment.get('preliminary_regime'), 'quantitative_assessment.preliminary_regime'),
        ('Suggested Strategy', quantitative_assessment.get('suggested_strategy'), 'quantitative_assessment.suggested_strategy'),
        ('Risk Off', quantitative_assessment.get('risk_off'), 'quantitative_assessment.risk_off'),
        ('Allow New Long', quantitative_assessment.get('allow_new_long'), 'quantitative_assessment.allow_new_long'),
    )
    catalog = [
        {'factor': factor, 'value': value, 'source_path': source_path}
        for factor, value, source_path in candidates
        if value is not None
    ]
    if backtest_context.get('available') is True:
        for factor, field in (
            ('Hybrid Backtest Total Return', 'total_return'),
            ('Hybrid Backtest Max Drawdown', 'max_drawdown'),
            ('Hybrid Backtest Win Rate', 'win_rate'),
            ('Hybrid Backtest Trade Count', 'trade_count'),
        ):
            value = backtest_context.get(field)
            if value is not None:
                catalog.append({
                    'factor': factor,
                    'value': value,
                    'source_path': f'backtest_context.{field}',
                })
    return catalog


def build_unified_agent_context(security, user, *, benchmark=None):
    """Assemble evidence, preliminary judgment, and hard constraints."""

    benchmark_security = benchmark
    if benchmark_security is None:
        benchmark_security = ensure_benchmark_security(BROAD_MARKET_SYMBOL)

    market_regime_result = get_market_regime(security)
    market_data = _market_data_payload(security)
    technical_analysis = _technical_payload(security, market_regime_result)
    market_regime = _market_regime_payload(market_regime_result)
    market_context = _market_context_payload(market_regime_result)
    portfolio_context = _portfolio_payload(user, security)
    strategy_selection = select_strategy(market_regime_result)
    as_of_date = (
        market_regime_result.get('latest_market_date')
        or market_data.get('latest_market_date')
    )
    backtest_context = _backtest_payload(
        security,
        benchmark_security,
        as_of_date,
    )
    quantitative_assessment = _quantitative_assessment_payload(
        market_regime,
        strategy_selection,
    )
    hard_constraints = _hard_constraints_payload(
        strategy_selection,
        portfolio_context,
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
        'quantitative_assessment': quantitative_assessment,
        'hard_constraints': hard_constraints,
        'available_strategies': _available_strategies_payload(hard_constraints),
        'related_backtest_strategy': get_related_backtest_strategy(),
        'strategy_evidence': _strategy_evidence_payload(backtest_context),
        'evidence_catalog': _evidence_catalog(
            market_data=market_data,
            technical_analysis=technical_analysis,
            market_regime=market_regime,
            market_context=market_context,
            quantitative_assessment=quantitative_assessment,
            backtest_context=backtest_context,
        ),
        'data_quality': _data_quality_payload(
            market_data=market_data,
            technical_analysis=technical_analysis,
            market_regime=market_regime,
            market_context=market_context,
            portfolio_context=portfolio_context,
            backtest_context=backtest_context,
        ),
    }


def build_llm_strategy_context(context):
    """Derive a neutral LLM context without backend regime/strategy opinions."""

    strategies = []
    for definition in context.get('available_strategies') or []:
        neutral = deepcopy(definition)
        guidance = neutral.pop('preliminary_selection_rationale', None)
        if guidance:
            neutral['general_evaluation_guidance'] = guidance
        strategies.append(neutral)

    market_regime = context.get('market_regime') or {}
    source_catalog = context.get('evidence_catalog') or []
    excluded_paths = {
        'quantitative_assessment.preliminary_regime',
        'quantitative_assessment.suggested_strategy',
        'quantitative_assessment.risk_off',
        'quantitative_assessment.allow_new_long',
    }
    path_rewrites = {
        'market_regime.choppiness': 'market_conditions.choppiness',
        'market_regime.volatility.atr_percent': 'market_conditions.volatility.atr_percent',
        'market_regime.volatility.realized_volatility_20d': 'market_conditions.volatility.realized_volatility_20d',
        'market_regime.volatility.volatility_percentile': 'market_conditions.volatility.volatility_percentile',
    }
    evidence_catalog = []
    for item in source_catalog:
        if not isinstance(item, dict) or item.get('source_path') in excluded_paths:
            continue
        copied = deepcopy(item)
        copied['source_path'] = path_rewrites.get(
            copied.get('source_path'), copied.get('source_path'),
        )
        evidence_catalog.append(copied)
    evidence_catalog.append({
        'factor': 'Market Data Available',
        'source_path': 'market_data.available',
        'value': (context.get('market_data') or {}).get('available') is True,
    })

    technical = deepcopy(context.get('technical_analysis') or {})
    mean_reversion = technical.get('mean_reversion_entry') or {}
    for factor, field in (
        ('Mean Reversion Lower Band', 'bollinger_lower_20_2'),
        ('Mean Reversion RSI Threshold', 'rsi_entry_threshold'),
        ('Close At Or Below Lower Band', 'close_at_or_below_lower_band'),
        ('RSI At Or Below Entry Threshold', 'rsi_at_or_below_threshold'),
        ('Mean Reversion Entry Conditions Met', 'entry_conditions_met'),
    ):
        value = mean_reversion.get(field)
        if value is not None:
            evidence_catalog.append({
                'factor': factor,
                'source_path': f'technical_analysis.mean_reversion_entry.{field}',
                'value': value,
            })

    return {
        'llm_context_version': LLM_STRATEGY_CONTEXT_VERSION,
        'symbol': context.get('symbol'),
        'as_of_date': context.get('as_of_date'),
        'security': deepcopy(context.get('security') or {}),
        'market_data': deepcopy(context.get('market_data') or {}),
        'technical_analysis': technical,
        'market_conditions': {
            'choppiness': market_regime.get('choppiness'),
            'volatility': deepcopy(market_regime.get('volatility') or {}),
        },
        'market_context': deepcopy(context.get('market_context') or {}),
        'portfolio_context': deepcopy(context.get('portfolio_context') or {}),
        'backtest_context': deepcopy(context.get('backtest_context') or {}),
        'hard_constraints': deepcopy(context.get('hard_constraints') or {}),
        'available_strategies': strategies,
        'related_backtest_strategy': deepcopy(context.get('related_backtest_strategy') or {}),
        'strategy_evidence': deepcopy(context.get('strategy_evidence') or {}),
        'evidence_catalog': evidence_catalog,
        'data_quality': deepcopy(context.get('data_quality') or {}),
    }


def backend_suggestion_exposed_to_llm(llm_context):
    """Return true if a forbidden backend-opinion key leaked into LLM input."""

    forbidden = {
        'preliminary_regime', 'suggested_strategy', 'quantitative_assessment',
        'quantitative_agreement', 'backend_strategy_ranking',
        'preliminary_selection_rationale',
    }

    def contains(value):
        if isinstance(value, dict):
            return any(key in forbidden or contains(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains(item) for item in value)
        return False

    return contains(llm_context)


__all__ = [
    'AGENT_UNIFIED_CONTEXT_VERSION', 'LLM_STRATEGY_CONTEXT_VERSION',
    'backend_suggestion_exposed_to_llm', 'build_llm_strategy_context',
    'build_unified_agent_context',
]
