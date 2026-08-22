"""Deterministic Market Regime to Strategy Selection mapping.

This first version is intentionally long-only and informational.  It selects a
strategy state but never creates orders, transactions, or portfolio actions.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .regime_config import (
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
)
from .strategy_catalog import (
    DETERMINISTIC_STRATEGY_IDS,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    get_agent_strategy_catalog,
    get_strategy_definition,
)


STRATEGIES = DETERMINISTIC_STRATEGY_IDS

STRATEGY_MODE_ACTIVE = 'active'
STRATEGY_MODE_DEFENSIVE = 'defensive'
EXECUTION_MODE_LONG_ONLY = 'long_only'


@dataclass(frozen=True)
class StrategySelectionRule:
    selected_strategy: str
    strategy_mode: str
    allow_new_long: bool
    risk_off: bool
    reason: tuple[str, ...]


# The complete v1 policy is centralized here so the View, future frontend, and
# future Agent integrations cannot drift into separate regime interpretations.
REGIME_STRATEGY_MAP = {
    REGIME_BULLISH: StrategySelectionRule(
        selected_strategy=STRATEGY_TREND_FOLLOWING,
        strategy_mode=STRATEGY_MODE_ACTIVE,
        allow_new_long=True,
        risk_off=False,
        reason=(
            'The current market regime is Bullish Trend.',
        ),
    ),
    REGIME_SIDEWAYS: StrategySelectionRule(
        selected_strategy=STRATEGY_MEAN_REVERSION,
        strategy_mode=STRATEGY_MODE_ACTIVE,
        allow_new_long=True,
        risk_off=False,
        reason=(
            'The current market regime is Sideways / Range.',
            'A strong directional trend is not confirmed.',
        ),
    ),
    REGIME_HIGH_VOLATILITY: StrategySelectionRule(
        selected_strategy=STRATEGY_RISK_OFF,
        strategy_mode=STRATEGY_MODE_DEFENSIVE,
        allow_new_long=False,
        risk_off=True,
        reason=(
            'The current market regime is High Volatility.',
            'New long positions are disabled under the current configuration.',
        ),
    ),
    REGIME_BEARISH: StrategySelectionRule(
        selected_strategy=STRATEGY_TREND_FOLLOWING,
        strategy_mode=STRATEGY_MODE_ACTIVE,
        allow_new_long=False,
        risk_off=False,
        reason=(
            'The current market regime is Bearish Trend.',
            'The system currently operates in long-only mode.',
            'New long positions are disabled while the bearish trend persists.',
        ),
    ),
}


def _unavailable_response(
    market_regime_result: Mapping,
    *,
    reason_code: str,
    reason: str,
):
    return {
        'symbol': market_regime_result.get('symbol'),
        'strategy_selection_available': False,
        'strategy_selection_unavailable_reason': reason_code,
        'market_regime': market_regime_result.get('regime'),
        'market_regime_unavailable_reason': market_regime_result.get(
            'regime_unavailable_reason'
        ),
        'regime_confidence': market_regime_result.get('confidence'),
        'regime_confidence_score': market_regime_result.get('confidence_score'),
        'selected_strategy': None,
        'strategy_mode': None,
        'execution_mode': EXECUTION_MODE_LONG_ONLY,
        'allow_new_long': None,
        'risk_off': None,
        'selection_confidence': None,
        'reason': [reason],
        'strategy_catalog': get_agent_strategy_catalog(),
    }


def select_strategy(market_regime_result: Mapping):
    """Select a long-only strategy from one completed Market Regime result.

    The input is treated as read-only.  No indicators are recalculated and no
    persistence or execution side effects are performed.
    """

    if not isinstance(market_regime_result, Mapping):
        raise TypeError('market_regime_result must be a mapping.')

    if market_regime_result.get('regime_available') is not True:
        return _unavailable_response(
            market_regime_result,
            reason_code='market_regime_unavailable',
            reason=(
                'Strategy selection is unavailable because the market regime '
                'is unavailable.'
            ),
        )

    market_regime = market_regime_result.get('regime')
    rule = REGIME_STRATEGY_MAP.get(market_regime)
    if rule is None:
        return _unavailable_response(
            market_regime_result,
            reason_code='unsupported_market_regime',
            reason=(
                'Strategy selection is unavailable because the market regime '
                'is not supported.'
            ),
        )

    regime_confidence = market_regime_result.get('confidence')
    strategy_definition = get_strategy_definition(rule.selected_strategy)
    selection_reasons = list(rule.reason)
    catalog_rationale = strategy_definition.get('preliminary_selection_rationale')
    if catalog_rationale:
        selection_reasons.insert(1, catalog_rationale)
    return {
        'symbol': market_regime_result.get('symbol'),
        'strategy_selection_available': True,
        'strategy_selection_unavailable_reason': None,
        'market_regime': market_regime,
        'market_regime_unavailable_reason': None,
        'regime_confidence': regime_confidence,
        'regime_confidence_score': market_regime_result.get('confidence_score'),
        'selected_strategy': rule.selected_strategy,
        'strategy_mode': rule.strategy_mode,
        'execution_mode': EXECUTION_MODE_LONG_ONLY,
        'allow_new_long': rule.allow_new_long,
        'risk_off': rule.risk_off,
        'selection_confidence': regime_confidence,
        'reason': selection_reasons,
        'strategy_definition': strategy_definition,
        'strategy_catalog': get_agent_strategy_catalog(),
    }


__all__ = [
    'EXECUTION_MODE_LONG_ONLY',
    'REGIME_STRATEGY_MAP',
    'STRATEGIES',
    'STRATEGY_MEAN_REVERSION',
    'STRATEGY_MODE_ACTIVE',
    'STRATEGY_MODE_DEFENSIVE',
    'STRATEGY_RISK_OFF',
    'STRATEGY_TREND_FOLLOWING',
    'select_strategy',
]
