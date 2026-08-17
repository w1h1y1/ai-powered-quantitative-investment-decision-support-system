"""Stable Agent Context schema constants.

The Agent Context is the single deterministic input object a future LLM layer
will consume.  Units are explicit here because the system intentionally mixes
decimal-fraction returns (technical) and percentage-point metrics (Strategy
Evaluation), and the LLM must never be left to guess which is which.
"""

AGENT_CONTEXT_VERSION = 'agent_context_v1'


TECHNICAL_UNITS = {
    'trend_direction': 'enum(bullish|bearish|mixed)',
    'trend_score': 'score_-1_to_1',
    'trend_strength_score': 'score_0_to_1',
    'price_vs_ma20': 'decimal_fraction',
    'ma20_vs_ma60': 'decimal_fraction',
    'price_vs_ma200': 'decimal_fraction',
    'ma20_slope': 'decimal_fraction',
    'ma60_slope': 'decimal_fraction',
    'adx': 'index_0_to_100',
    'momentum_score': 'score_-1_to_1',
    'rsi': 'index_0_to_100',
    'macd_histogram': 'price_units',
    'return_20d': 'decimal_fraction',
    'return_60d': 'decimal_fraction',
    'volatility_score': 'score_0_to_1',
    'atr': 'price_units',
    'atr_percent': 'decimal_fraction',
    'realized_volatility_20d': 'decimal_fraction',
    'volatility_percentile': 'decimal_fraction_0_to_1',
    'percentile_available': 'boolean',
    'choppiness': 'index_0_to_100',
    'range_score': 'score_0_to_1',
}

RELATIVE_STRENGTH_UNITS = {
    'score': 'score_-1_to_1',
    'vs_spy_20d': 'decimal_fraction',
    'vs_spy_60d': 'decimal_fraction',
    'vs_sector_20d': 'decimal_fraction',
    'vs_sector_60d': 'decimal_fraction',
}

EVALUATION_UNITS = {
    'initial_capital': 'money_security_currency',
    'final_equity': 'money_security_currency',
    'total_return': 'percentage_points',
    'maximum_drawdown': 'percentage_points',
    'annualized_volatility': 'percentage_points',
    'total_fees': 'money_security_currency',
    'executed_order_count': 'count',
}
