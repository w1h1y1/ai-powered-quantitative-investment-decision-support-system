"""Deterministic, non-executing guidance for validated Agent decisions."""

from market.strategy_catalog import (
    STRATEGY_MEAN_REVERSION,
    STRATEGY_NO_STRATEGY,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    get_strategy_definition,
)


ACTIVE_STRATEGIES = {STRATEGY_TREND_FOLLOWING, STRATEGY_MEAN_REVERSION}


def _strategy_name(strategy_id):
    definition = get_strategy_definition(strategy_id) or {}
    return definition.get('name') or str(strategy_id).replace('_', ' ').title()


def _first_condition(strategy_id, field):
    definition = get_strategy_definition(strategy_id) or {}
    conditions = definition.get(field) or []
    return conditions[0] if conditions else None


def _monitoring_triggers(final_strategy, *, risk_off):
    if risk_off:
        condition = _first_condition(STRATEGY_RISK_OFF, 'supporting_conditions')
        return [{
            'factor': 'Risk-Off constraint',
            'condition': condition or 'Hard risk constraints continue to prohibit new long exposure.',
        }]

    if final_strategy in ACTIVE_STRATEGIES:
        condition = _first_condition(final_strategy, 'entry_conditions')
        triggers = [{
            'factor': _strategy_name(final_strategy),
            'condition': condition,
        }] if condition else []
        triggers.append({
            'factor': 'Risk conditions',
            'condition': _first_condition(STRATEGY_RISK_OFF, 'supporting_conditions'),
        })
        return triggers

    return [
        {
            'factor': 'Trend Following',
            'condition': _first_condition(STRATEGY_TREND_FOLLOWING, 'entry_conditions'),
        },
        {
            'factor': 'Mean Reversion',
            'condition': _first_condition(STRATEGY_MEAN_REVERSION, 'entry_conditions'),
        },
        {
            'factor': 'Risk conditions',
            'condition': _first_condition(STRATEGY_RISK_OFF, 'supporting_conditions'),
        },
    ]


def build_recommended_action(context, final_strategy):
    """Return bounded decision-support guidance after Django validates a strategy.

    This payload never authorizes execution and intentionally contains no order,
    quantity, target-price, or automatic position-sizing instruction.
    """

    constraints = context.get('hard_constraints') or {}
    portfolio = context.get('portfolio_context') or {}
    portfolio_available = portfolio.get('available') is True
    quantity = portfolio.get('quantity')
    if portfolio_available and (
        portfolio.get('has_position') is True
        or isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity > 0
    ):
        has_position = True
    elif portfolio_available and (
        portfolio.get('has_position') is False or quantity == 0
    ):
        has_position = False
    else:
        has_position = None
    allow_new_long = constraints.get('allow_new_long') is True
    risk_off = (
        final_strategy == STRATEGY_RISK_OFF
        or constraints.get('risk_off') is True
        or not allow_new_long
    )

    common = {
        'position_context': (
            'existing_position' if has_position is True
            else 'no_position' if has_position is False
            else 'portfolio_unavailable'
        ),
        'new_entry_allowed': allow_new_long and not risk_off,
        'automatic_execution': False,
        'monitoring_triggers': _monitoring_triggers(final_strategy, risk_off=risk_off),
        'reassessment_reason': (
            'Regenerate the analysis when a listed strategy entry condition or a hard risk constraint changes.'
        ),
    }

    if risk_off:
        if has_position is True:
            return {
                **common,
                'action': 'reduce_risk',
                'label': 'Reduce Risk / No New Long',
                'suggested_exposure_change': 'review_risk_reduction',
                'summary': (
                    'Review the existing position for risk reduction under the active '
                    'Risk-Off constraint. Do not add new long exposure.'
                ),
            }
        if has_position is False:
            return {
                **common,
                'action': 'avoid_new_entry',
                'label': 'Avoid New Entry',
                'suggested_exposure_change': 'none',
                'summary': (
                    'Remain out of the position while Risk-Off is active and new long '
                    'exposure is prohibited.'
                ),
            }
        return {
            **common,
            'action': 'review_risk',
            'label': 'Review Risk / No New Long',
            'suggested_exposure_change': 'none',
            'summary': (
                'Portfolio context is unavailable. Keep the neutral Risk-Off guidance '
                'and do not add new long exposure.'
            ),
        }

    if final_strategy == STRATEGY_NO_STRATEGY:
        if has_position is True:
            return {
                **common,
                'action': 'hold_and_monitor',
                'label': 'Hold and Monitor',
                'suggested_exposure_change': 'none',
                'summary': (
                    'Maintain the current position without adding exposure, and monitor '
                    'for a validated strategy entry condition or a new risk constraint.'
                ),
            }
        if has_position is False:
            return {
                **common,
                'action': 'wait',
                'label': 'Wait / No New Entry',
                'suggested_exposure_change': 'none',
                'summary': (
                    'Wait without opening a new position because neither active strategy '
                    'currently meets its validated entry requirements.'
                ),
            }
        return {
            **common,
            'action': 'monitor',
            'label': 'Monitor / Reassess',
            'suggested_exposure_change': 'none',
            'summary': (
                'Portfolio context is unavailable. Keep a neutral stance and reassess '
                'when a validated strategy entry condition changes.'
            ),
        }

    if final_strategy in ACTIVE_STRATEGIES:
        name = _strategy_name(final_strategy)
        return {
            **common,
            'action': 'consider_strategy',
            'label': f'Consider {name}',
            'suggested_exposure_change': 'consider_strategy_rules',
            'summary': (
                f'Consider {name} only under its validated entry rules and current '
                'portfolio constraints. This is decision support, not an order.'
            ),
        }

    return {
        **common,
        'action': 'monitor',
        'label': 'Monitor / Reassess',
        'suggested_exposure_change': 'none',
        'summary': 'Keep a neutral stance and reassess when validated conditions change.',
    }


__all__ = ['build_recommended_action']
