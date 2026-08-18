"""Structured schema for AG-02 agent analysis."""

import json

AGENT_ANALYSIS_VERSION = 'agent_analysis_v1'
AGENT_ANALYSIS_PROMPT_VERSION = 'agent_analysis_prompt_v1'

FORBIDDEN_ACTION_PHRASES = (
    'initiate a position',
    'enter a position',
    'add exposure',
    'increase exposure',
    'reduce exposure',
    'exit the position',
    'take profit',
    'buy the dip',
    'consider buying',
    'consider selling',
    'could enter',
    'capacity to enter',
    'room to add',
    'opportunity to buy',
    'ample capacity',
)


class UnifiedAnalysisValidationError(ValueError):
    """Raised when the provider output does not match the analysis schema."""


def _string(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise UnifiedAnalysisValidationError('expected a non-empty string')


def _string_list(value):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnifiedAnalysisValidationError('expected a list of strings')
    return [item.strip() for item in value if item.strip()]


def _section(data, field_name):
    section = data.get(field_name)
    if not isinstance(section, dict):
        raise UnifiedAnalysisValidationError(f'missing required field: {field_name}')
    return section


def _has_forbidden_text(value):
    if isinstance(value, str):
        lowered = value.lower()
        return any(phrase in lowered for phrase in FORBIDDEN_ACTION_PHRASES)
    if isinstance(value, dict):
        return any(_has_forbidden_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_forbidden_text(item) for item in value)
    return False


def has_forbidden_action_language(analysis):
    return _has_forbidden_text(analysis)


def has_open_close_direction_contradiction(analysis, context):
    direction = (context.get('market_data') or {}).get('open_to_close_direction')
    if direction not in {'Up', 'Down', 'Flat'}:
        return False
    text = json.dumps(analysis).lower()
    if direction == 'Down':
        forbidden = (
            'closed higher',
            'up from the open',
            'rose from the open',
            'closed above the open',
        )
    elif direction == 'Up':
        forbidden = (
            'closed lower',
            'down from the open',
            'fell from the open',
            'closed below the open',
        )
    else:
        forbidden = (
            'closed higher',
            'closed lower',
            'up from the open',
            'down from the open',
        )
    return any(phrase in text for phrase in forbidden)


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decision_stance(direction, price_vs_ma20, macd_histogram, regime):
    if regime == 'high_volatility':
        if direction == 'Bullish' and (price_vs_ma20 or 0) > 0 and (macd_histogram or 0) > 0:
            return 'Cautious Bullish'
        return 'Cautious'
    if direction == 'Bullish':
        if (price_vs_ma20 or 0) > 0 and (macd_histogram or 0) > 0:
            return 'Bullish'
        return 'Cautious Bullish'
    if direction == 'Bearish':
        return 'Bearish'
    if regime == 'sideways_range':
        return 'Neutral'
    return 'Neutral'


def _decision_confidence(context, analysis):
    market_regime = context.get('market_regime') or {}
    technical = context.get('technical_analysis') or {}
    market_context = context.get('market_context') or {}
    backtest = context.get('backtest_context') or {}
    confirmation = market_context.get('confirmation') or {}
    volatility = market_regime.get('volatility') or {}
    available_sources = sum([
        market_regime.get('available') is True,
        technical.get('available') is True,
        backtest.get('available') is True,
        (market_context.get('broad_market') or {}).get('available') is True,
    ])
    percentile = _as_float(volatility.get('volatility_percentile'))
    if confirmation.get('level') == 'Weak' or available_sources < 2:
        return 'Low'
    if percentile is not None and percentile >= 0.85:
        return 'Medium'
    if confirmation.get('level') == 'Strong' and available_sources >= 3:
        return 'High'
    return 'Medium'


def _decision_key_reasons(context, analysis):
    regime = (context.get('market_regime') or {}).get('regime')
    direction = (context.get('market_regime') or {}).get('direction')
    technical = context.get('technical_analysis') or {}
    moving_averages = technical.get('moving_averages') or {}
    momentum = technical.get('momentum') or {}
    backtest = context.get('backtest_context') or {}
    portfolio = context.get('portfolio_context') or {}
    market_context = context.get('market_context') or {}
    broad = market_context.get('broad_market') or {}
    sector = market_context.get('sector') or {}
    reasons = []

    price_vs_ma20 = _as_float(moving_averages.get('price_vs_ma20'))
    if price_vs_ma20 is not None:
        if price_vs_ma20 > 0.001:
            reasons.append('Price is above MA20.')
        elif price_vs_ma20 < -0.001:
            reasons.append('Price is below MA20.')
        else:
            reasons.append('Price is near MA20.')

    rsi = _as_float(momentum.get('rsi'))
    if rsi is not None:
        if rsi >= 70:
            reasons.append(f'RSI is overbought at {rsi:.1f}.')
        elif rsi <= 30:
            reasons.append(f'RSI is oversold at {rsi:.1f}.')
        else:
            reasons.append(f'RSI is neutral at {rsi:.1f}.')

    macd_histogram = _as_float(momentum.get('macd_histogram'))
    if macd_histogram is not None:
        if macd_histogram > 0:
            reasons.append('MACD momentum is positive.')
        elif macd_histogram < 0:
            reasons.append('MACD momentum is negative.')
        else:
            reasons.append('MACD momentum is flat.')

    if direction:
        reasons.append(f'Trend direction is {direction}.')

    broad_symbol = broad.get('symbol') or 'SPY'
    if broad.get('available') is True:
        broad_state = broad.get('regime') or broad.get('direction') or 'unavailable'
        reasons.append(f'Broad market {broad_symbol} is {broad_state}.')

    sector_benchmark = sector.get('benchmark')
    if sector.get('available') is True and sector_benchmark:
        sector_state = sector.get('regime') or sector.get('direction') or 'unavailable'
        reasons.append(f'Sector {sector_benchmark} is {sector_state}.')

    if backtest.get('available') is True:
        reasons.append(
            f'Historical backtest evidence is available with '
            f"{backtest.get('trade_count', 0)} trades."
        )

    if portfolio.get('has_position') is True:
        reasons.append('The portfolio currently holds this security.')
    elif portfolio.get('available') is True:
        reasons.append('The portfolio has no current position in this security.')

    return reasons[:5]


def _decision_main_risk(context, analysis):
    volatility = (context.get('market_regime') or {}).get('volatility') or {}
    percentile = _as_float(volatility.get('volatility_percentile'))
    if percentile is not None and percentile >= 0.85:
        return 'High volatility is the main current risk.'

    technical = context.get('technical_analysis') or {}
    moving_averages = technical.get('moving_averages') or {}
    momentum = technical.get('momentum') or {}
    price_vs_ma20 = _as_float(moving_averages.get('price_vs_ma20'))
    macd_histogram = _as_float(momentum.get('macd_histogram'))
    if price_vs_ma20 is not None and price_vs_ma20 < 0 and (macd_histogram or 0) < 0:
        return 'Price is below MA20 with negative momentum.'

    risk_factors = analysis.get('risk_factors') or []
    if risk_factors:
        return risk_factors[0]
    return 'Mixed evidence with limited confirmation.'


def build_decision_summary(context, analysis):
    market_regime = context.get('market_regime') or {}
    technical = context.get('technical_analysis') or {}
    moving_averages = technical.get('moving_averages') or {}
    momentum = technical.get('momentum') or {}
    backtest = context.get('backtest_context') or {}
    market_context = context.get('market_context') or {}
    confirmation = market_context.get('confirmation') or {}
    regime = market_regime.get('regime')
    direction = market_regime.get('direction')
    price_vs_ma20 = _as_float(moving_averages.get('price_vs_ma20'))
    macd_histogram = _as_float(momentum.get('macd_histogram'))
    stance = _decision_stance(direction, price_vs_ma20, macd_histogram, regime)
    confidence = _decision_confidence(context, analysis)
    suggested_approach = 'Wait for Confirmation'
    suitable_strategy = 'Swing'

    if regime == 'high_volatility':
        suggested_approach = 'Wait for Confirmation'
        suitable_strategy = 'Reduced Exposure / Wait'
    elif regime == 'sideways_range':
        suggested_approach = 'Mean-Reversion Opportunity'
        suitable_strategy = 'Mean Reversion'
    elif direction == 'Bullish':
        suggested_approach = 'Hold / Monitor'
        suitable_strategy = 'Trend Following'
    elif direction == 'Bearish':
        suggested_approach = 'Reduced Exposure'
        suitable_strategy = 'Reduced Exposure / Wait'

    time_horizon = 'Short-to-Medium Term'
    if regime == 'sideways_range' or regime == 'high_volatility':
        time_horizon = 'Short Term'
    elif backtest.get('available') is True and confirmation.get('level') == 'Strong':
        time_horizon = 'Medium Term'

    return {
        'stance': stance,
        'confidence': confidence,
        'suggested_approach': suggested_approach,
        'suitable_strategy': suitable_strategy,
        'time_horizon': time_horizon,
        'key_reasons': _decision_key_reasons(context, analysis),
        'main_risk': _decision_main_risk(context, analysis),
    }


def normalize_unified_analysis(data, context):
    """Normalize LLM narrative and inject Django-owned facts from context."""

    if not isinstance(data, dict):
        raise UnifiedAnalysisValidationError('analysis must be a JSON object')

    market_view = _section(data, 'market_view')
    technical_view = _section(data, 'technical_view')
    market_context_view = _section(data, 'market_context_view')
    portfolio_view = _section(data, 'portfolio_view')
    backtest_view = _section(data, 'backtest_view')

    market_regime = context.get('market_regime') or {}
    portfolio_context = context.get('portfolio_context') or {}
    backtest_context = context.get('backtest_context') or {}
    backtest_available = backtest_context.get('available') is True
    market_confirmation = (context.get('market_context') or {}).get('confirmation') or {}

    normalized = {
        'market_view': {
            'regime': market_regime.get('regime'),
            'direction': market_regime.get('direction'),
            'summary': _string(market_view.get('summary')),
        },
        'technical_view': {
            'trend': _string(technical_view.get('trend')),
            'momentum': _string(technical_view.get('momentum')),
            'volatility': _string(technical_view.get('volatility')),
        },
        'market_context_view': {
            'broad_market': _string(market_context_view.get('broad_market')),
            'sector': _string(market_context_view.get('sector')),
            'confirmation': _string(market_context_view.get('confirmation')),
            'confirmation_score': market_confirmation.get('score'),
            'confirmation_level': market_confirmation.get('level'),
        },
        'portfolio_view': {
            'has_position': portfolio_context.get('has_position') is True,
            'portfolio_weight': portfolio_context.get('portfolio_weight'),
            'exposure_comment': _string(portfolio_view.get('exposure_comment')),
        },
        'backtest_view': {
            'available': backtest_available,
            'summary': _string(backtest_view.get('summary')),
            'strengths': _string_list(backtest_view.get('strengths')) if backtest_available else [],
            'risks': _string_list(backtest_view.get('risks')) if backtest_available else [],
        },
        'overall_assessment': _string(data.get('overall_assessment')),
        'risk_factors': _string_list(data.get('risk_factors')),
    }
    normalized['decision_summary'] = build_decision_summary(context, normalized)
    return normalized
