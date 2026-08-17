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

    return {
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
