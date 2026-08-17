"""Deterministic Agent Context assembly.

The Agent Context reuses the formal Market Regime, Strategy Selection and
Strategy Evaluation services.  It never recalculates indicators, never copies
the regime-to-strategy mapping, and never generates its own market facts.
"""

from market.regime_config import BROAD_MARKET_SYMBOL
from market.regime_service import (
    ensure_benchmark_security,
    get_market_regime,
)
from market.strategy_selection_service import select_strategy
from backtest.strategy_evaluation_service import evaluate_selected_strategy

from .schemas import (
    AGENT_CONTEXT_VERSION,
    EVALUATION_UNITS,
    RELATIVE_STRENGTH_UNITS,
    TECHNICAL_UNITS,
)


def _strings(value):
    return [
        item
        for item in (value or [])
        if isinstance(item, str) and item.strip()
    ]


def _security_payload(security):
    return {
        'id': security.id,
        'symbol': security.symbol,
        'name': security.name,
        'exchange': security.exchange,
        'currency': security.currency,
    }


def _technical_payload(market_regime_result):
    trend = market_regime_result.get('trend') or {}
    momentum = market_regime_result.get('momentum') or {}
    volatility = market_regime_result.get('volatility') or {}
    range_data = market_regime_result.get('range') or {}
    relative_strength = market_regime_result.get('relative_strength') or {}
    return {
        'latest': {
            'trend_direction': trend.get('direction'),
            'trend_score': trend.get('score'),
            'trend_strength_score': trend.get('strength_score'),
            'price_vs_ma20': trend.get('price_vs_ma20'),
            'ma20_vs_ma60': trend.get('ma20_vs_ma60'),
            'price_vs_ma200': trend.get('price_vs_ma200'),
            'ma20_slope': trend.get('ma20_slope'),
            'ma60_slope': trend.get('ma60_slope'),
            'adx': trend.get('adx'),
            'momentum_score': momentum.get('score'),
            'rsi': momentum.get('rsi'),
            'macd_histogram': momentum.get('macd_histogram'),
            'return_20d': momentum.get('return_20d'),
            'return_60d': momentum.get('return_60d'),
            'volatility_score': volatility.get('score'),
            'atr': volatility.get('atr'),
            'atr_percent': volatility.get('atr_percent'),
            'realized_volatility_20d': volatility.get('realized_volatility_20d'),
            'volatility_percentile': volatility.get('volatility_percentile'),
            'percentile_available': volatility.get('percentile_available'),
            'choppiness': range_data.get('choppiness'),
            'range_score': range_data.get('score'),
        },
        'relative_strength': {
            'score': relative_strength.get('score'),
            'vs_spy_20d': relative_strength.get('vs_spy_20d'),
            'vs_spy_60d': relative_strength.get('vs_spy_60d'),
            'vs_sector_20d': relative_strength.get('vs_sector_20d'),
            'vs_sector_60d': relative_strength.get('vs_sector_60d'),
        },
        'units': {
            **TECHNICAL_UNITS,
            'relative_strength': RELATIVE_STRENGTH_UNITS,
        },
    }


def _market_context_payload(market_regime_result):
    context = market_regime_result.get('market_context') or {}
    sector_available = context.get('sector_context_available') is True
    return {
        'broad_market': context.get('broad_market'),
        'broad_market_available': context.get('broad_market_context_available') is True,
        'broad_market_reason': context.get('broad_market_context_reason'),
        'spy_regime': context.get('spy_regime'),
        'sector': context.get('sector'),
        'sector_source': context.get('sector_source'),
        'sector_benchmark': context.get('sector_benchmark'),
        'sector_available': sector_available,
        'sector_reason': context.get('sector_context_reason'),
        'sector_regime': context.get('sector_regime') if sector_available else None,
        'confirmation_score': context.get('confirmation_score'),
    }


def _market_regime_payload(market_regime_result):
    return {
        'available': market_regime_result.get('regime_available') is True,
        'unavailable_reason': market_regime_result.get('regime_unavailable_reason'),
        'regime': market_regime_result.get('regime'),
        'confidence': market_regime_result.get('confidence'),
        'confidence_score': market_regime_result.get('confidence_score'),
        'explanation': _strings(market_regime_result.get('explanation')),
    }


def _strategy_selection_payload(strategy_selection):
    return {
        'available': strategy_selection.get('strategy_selection_available') is True,
        'unavailable_reason': strategy_selection.get('strategy_selection_unavailable_reason'),
        'selected_strategy': strategy_selection.get('selected_strategy'),
        'strategy_mode': strategy_selection.get('strategy_mode'),
        'execution_mode': strategy_selection.get('execution_mode'),
        'allow_new_long': strategy_selection.get('allow_new_long'),
        'risk_off': strategy_selection.get('risk_off'),
        'selection_confidence': strategy_selection.get('selection_confidence'),
        'reason': _strings(strategy_selection.get('reason')),
    }


def _small_strategy_parameters(strategy_parameters):
    if not isinstance(strategy_parameters, dict):
        return None
    return {
        key: strategy_parameters[key]
        for key in ('strategy', 'strategy_id')
        if key in strategy_parameters
    } or None


def _strategy_evaluation_payload(evaluation_result):
    return {
        'available': evaluation_result.get('evaluation_available') is True,
        'status': evaluation_result.get('evaluation_status'),
        'unavailable_reason': evaluation_result.get('evaluation_unavailable_reason'),
        'evaluation_strategy': evaluation_result.get('evaluation_strategy'),
        'metrics': {
            'initial_capital': evaluation_result.get('initial_capital'),
            'final_equity': evaluation_result.get('final_equity'),
            'total_return': evaluation_result.get('total_return'),
            'maximum_drawdown': evaluation_result.get('maximum_drawdown'),
            'annualized_volatility': evaluation_result.get('annualized_volatility'),
            'total_fees': evaluation_result.get('total_fees'),
            'executed_order_count': evaluation_result.get('executed_order_count'),
        },
        'evaluation_window': evaluation_result.get('evaluation_window'),
        'data_source': evaluation_result.get('data_source'),
        'strategy_parameters': _small_strategy_parameters(
            evaluation_result.get('strategy_parameters'),
        ),
        'units': EVALUATION_UNITS,
    }


def _data_quality_payload(
    *,
    market_regime_result,
    strategy_selection,
    evaluation_result,
    as_of_date,
):
    market_context = market_regime_result.get('market_context') or {}
    broad_market_available = market_context.get('broad_market_context_available') is True
    sector_available = market_context.get('sector_context_available') is True
    market_context_available = broad_market_available and sector_available
    market_context_reason = (
        market_context.get('broad_market_context_reason')
        or market_context.get('sector_context_reason')
        or None
    )

    regime_available = market_regime_result.get('regime_available') is True
    selection_available = strategy_selection.get('strategy_selection_available') is True
    evaluation_available = evaluation_result.get('evaluation_available') is True
    evaluation_status = evaluation_result.get('evaluation_status')
    evaluation_degraded = (
        not evaluation_available
        and evaluation_status != 'not_applicable'
    )

    stock_market_data = (market_regime_result.get('market_data') or {}).get('stock') or {}
    spy_market_data = (market_regime_result.get('market_data') or {}).get('spy') or {}
    sector_market_data = (market_regime_result.get('market_data') or {}).get('sector') or {}
    volatility = market_regime_result.get('volatility') or {}

    modules = {
        'market_regime': {
            'available': regime_available,
            'status': 'available' if regime_available else 'unavailable',
            'reason': market_regime_result.get('regime_unavailable_reason'),
            'latest_market_date': market_regime_result.get('latest_market_date'),
            'data_source': stock_market_data.get('source'),
            'fetched_from_provider': stock_market_data.get('fetched_from_provider'),
            'provider_error': stock_market_data.get('provider_error'),
            'historical_data_count': market_regime_result.get('historical_data_count'),
            'required_core_history_count': market_regime_result.get(
                'required_core_history_count',
            ),
            'percentile_available': volatility.get('percentile_available'),
        },
        'market_context': {
            'available': market_context_available,
            'status': 'available' if market_context_available else 'unavailable',
            'reason': market_context_reason,
            'broad_market_available': broad_market_available,
            'broad_market_reason': market_context.get('broad_market_context_reason'),
            'sector_available': sector_available,
            'sector_reason': market_context.get('sector_context_reason'),
            'broad_market_data_source': spy_market_data.get('source'),
            'sector_data_source': sector_market_data.get('source'),
            'confirmation_score': market_context.get('confirmation_score'),
        },
        'strategy_selection': {
            'available': selection_available,
            'status': 'available' if selection_available else 'unavailable',
            'reason': strategy_selection.get('strategy_selection_unavailable_reason'),
            'selection_confidence': strategy_selection.get('selection_confidence'),
        },
        'strategy_evaluation': {
            'available': evaluation_available,
            'status': evaluation_status,
            'reason': evaluation_result.get('evaluation_unavailable_reason'),
            'latest_market_date': evaluation_result.get(
                'market_regime_latest_market_date',
            ),
            'data_source': (evaluation_result.get('data_source') or {}).get('source'),
        },
    }

    degraded_modules = []
    if not regime_available:
        degraded_modules.append('market_regime')
    if not market_context_available:
        degraded_modules.append('market_context')
    if not selection_available:
        degraded_modules.append('strategy_selection')
    if evaluation_degraded:
        degraded_modules.append('strategy_evaluation')

    return {
        'all_modules_available': not degraded_modules,
        'degraded_modules': degraded_modules,
        'as_of_date': as_of_date,
        'modules': modules,
    }


def build_agent_context_from_parts(
    *,
    security,
    market_regime_result,
    strategy_selection,
    evaluation_result,
):
    """Assemble a stable Agent Context from already-computed formal results."""

    as_of_date = (
        market_regime_result.get('latest_market_date')
        or evaluation_result.get('market_regime_latest_market_date')
        or None
    )
    return {
        'context_version': AGENT_CONTEXT_VERSION,
        'symbol': security.symbol,
        'as_of_date': as_of_date,
        'security': _security_payload(security),
        'technical': _technical_payload(market_regime_result),
        'market_context': _market_context_payload(market_regime_result),
        'market_regime': _market_regime_payload(market_regime_result),
        'strategy_selection': _strategy_selection_payload(strategy_selection),
        'strategy_evaluation': _strategy_evaluation_payload(evaluation_result),
        'data_quality': _data_quality_payload(
            market_regime_result=market_regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=evaluation_result,
            as_of_date=as_of_date,
        ),
    }


def build_agent_context(security, *, benchmark=None):
    """Build the deterministic Agent Context for one security.

    Market Regime is computed exactly once.  The same result is reused by
    Strategy Selection and Strategy Evaluation so the Agent Context never
    triggers a second regime calculation or a second mapping run.
    """

    benchmark_security = benchmark
    if benchmark_security is None:
        benchmark_security = ensure_benchmark_security(BROAD_MARKET_SYMBOL)

    market_regime_result = get_market_regime(security)
    strategy_selection = select_strategy(market_regime_result)
    evaluation_result = evaluate_selected_strategy(
        security=security,
        benchmark=benchmark_security,
        market_regime_result=market_regime_result,
        strategy_selection_result=strategy_selection,
    )
    return build_agent_context_from_parts(
        security=security,
        market_regime_result=market_regime_result,
        strategy_selection=strategy_selection,
        evaluation_result=evaluation_result,
    )


__all__ = [
    'AGENT_CONTEXT_VERSION',
    'build_agent_context',
    'build_agent_context_from_parts',
]
