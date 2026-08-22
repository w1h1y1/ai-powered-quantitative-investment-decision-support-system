"""Validated quantitative-comparison + LLM-synthesis schema."""

import json
import math
import re

from market.regime_config import (
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
)
from market.strategy_catalog import (
    AGENT_STRATEGY_IDS,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_NO_STRATEGY,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
)


AGENT_ANALYSIS_VERSION = 'investment_agent_analysis_v3'
AGENT_ANALYSIS_PROMPT_VERSION = 'investment_agent_analysis_prompt_v3'

ALLOWED_REGIMES = {
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
}
ALLOWED_DIRECTIONS = {'bullish', 'bearish', 'neutral', 'mixed'}
ALLOWED_CANDIDATE_SUITABILITY = {
    'high', 'medium', 'low', 'not_allowed', 'insufficient_evidence',
}
ALLOWED_RISK_LEVELS = {'low', 'medium', 'high'}
ACTIVE_STRATEGIES = {STRATEGY_TREND_FOLLOWING, STRATEGY_MEAN_REVERSION}
TOP_LEVEL_FIELDS = {
    'final_market_assessment', 'strategy_comparison',
    'final_strategy_assessment', 'quantitative_agreement',
    'risk_assessment', 'backtest_evidence_available',
    'supporting_evidence', 'limitations',
}
NUMBER_PATTERN = re.compile(r'(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_])')

FORBIDDEN_ACTION_PHRASES = (
    'initiate a position', 'enter a position', 'add exposure',
    'increase exposure', 'reduce exposure', 'exit the position',
    'take profit', 'buy the dip', 'consider buying', 'consider selling',
    'could enter', 'capacity to enter', 'room to add',
    'opportunity to buy', 'ample capacity',
)


class UnifiedAnalysisValidationError(ValueError):
    """Raised when provider output is unsafe or does not match v3."""

    def __init__(self, message, *, reason_code='llm_schema_validation_failed'):
        super().__init__(message)
        self.reason_code = reason_code


def _string(value, field_name):
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise UnifiedAnalysisValidationError(f'{field_name} must be a non-empty string')


def _string_list(value, field_name):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnifiedAnalysisValidationError(f'{field_name} must be an array of strings')
    return [item.strip() for item in value if item.strip()]


def _section(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, dict):
        raise UnifiedAnalysisValidationError(f'missing required field: {field_name}')
    return value


def _require_exact_fields(value, expected, field_name):
    if set(value) != set(expected):
        raise UnifiedAnalysisValidationError(f'{field_name} has missing or extra fields')


def _enum(value, allowed, field_name):
    if value not in allowed:
        raise UnifiedAnalysisValidationError(f'{field_name} has an unsupported value')
    return value


def _boolean(value, field_name):
    if not isinstance(value, bool):
        raise UnifiedAnalysisValidationError(f'{field_name} must be a boolean')
    return value


def _confidence(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnifiedAnalysisValidationError(f'{field_name} must be numeric')
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise UnifiedAnalysisValidationError(f'{field_name} must be between 0 and 1')
    return round(number, 6)


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
        forbidden = ('closed higher', 'up from the open', 'rose from the open', 'closed above the open')
    elif direction == 'Up':
        forbidden = ('closed lower', 'down from the open', 'fell from the open', 'closed below the open')
    else:
        forbidden = ('closed higher', 'closed lower', 'up from the open', 'down from the open')
    return any(phrase in text for phrase in forbidden)


def _same_value(actual, expected):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)
    return actual == expected


def _normalize_evidence(value, context, *, field_name, allow_empty):
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = 'an array' if allow_empty else 'a non-empty array'
        raise UnifiedAnalysisValidationError(f'{field_name} must be {qualifier}')
    catalog = {
        item.get('factor'): item.get('value')
        for item in (context.get('evidence_catalog') or [])
        if isinstance(item, dict) and isinstance(item.get('factor'), str)
    }
    normalized = []
    for index, item in enumerate(value):
        item_name = f'{field_name}[{index}]'
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(f'{item_name} must be an object')
        _require_exact_fields(item, {'factor', 'value', 'interpretation'}, item_name)
        factor = _string(item.get('factor'), f'{item_name}.factor')
        if factor not in catalog:
            raise UnifiedAnalysisValidationError(
                f'{item_name} references an unavailable factor',
                reason_code='llm_evidence_validation_failed',
            )
        evidence_value = item.get('value')
        if not _same_value(evidence_value, catalog[factor]):
            raise UnifiedAnalysisValidationError(
                f'{item_name} value does not match context',
                reason_code='llm_evidence_validation_failed',
            )
        normalized.append({
            'factor': factor,
            'value': evidence_value,
            'interpretation': _string(item.get('interpretation'), f'{item_name}.interpretation'),
        })
    return normalized


def _candidate_ids(context):
    ids = [
        item.get('id') for item in (context.get('available_strategies') or [])
        if isinstance(item, dict) and item.get('id') in AGENT_STRATEGY_IDS
    ]
    return ids or list(AGENT_STRATEGY_IDS)


def _currently_allowed_ids(context, candidate_ids):
    constraints = context.get('hard_constraints') or {}
    configured = constraints.get('currently_allowed_strategies')
    if isinstance(configured, list):
        return {item for item in configured if item in candidate_ids}
    if constraints.get('allow_new_long') is True:
        return set(candidate_ids)
    return {STRATEGY_RISK_OFF, STRATEGY_NO_STRATEGY} & set(candidate_ids)


def _normalize_strategy_comparison(value, context, candidate_ids):
    if not isinstance(value, dict) or set(value) != set(candidate_ids):
        raise UnifiedAnalysisValidationError(
            'strategy_comparison must contain every available strategy exactly once'
        )
    normalized = {}
    currently_allowed = _currently_allowed_ids(context, candidate_ids)
    for strategy_id in candidate_ids:
        item = value.get(strategy_id)
        field_name = f'strategy_comparison.{strategy_id}'
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(f'{field_name} must be an object')
        _require_exact_fields(
            item,
            {'suitability', 'supporting_factors', 'conflicting_factors'},
            field_name,
        )
        supporting = _normalize_evidence(
            item.get('supporting_factors'), context,
            field_name=f'{field_name}.supporting_factors', allow_empty=True,
        )
        conflicting = _normalize_evidence(
            item.get('conflicting_factors'), context,
            field_name=f'{field_name}.conflicting_factors', allow_empty=True,
        )
        if any(
            evidence['factor'].startswith('Hybrid Backtest')
            for evidence in supporting + conflicting
        ):
            raise UnifiedAnalysisValidationError(
                'the related hybrid backtest is not candidate-comparison evidence',
                reason_code='llm_evidence_validation_failed',
            )
        suitability = _enum(
                item.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY,
                f'{field_name}.suitability',
            )
        if strategy_id not in currently_allowed and suitability != 'not_allowed':
            raise UnifiedAnalysisValidationError(
                f'{field_name}.suitability must be not_allowed under current constraints'
            )
        if strategy_id in currently_allowed and suitability == 'not_allowed':
            raise UnifiedAnalysisValidationError(
                f'{field_name}.suitability contradicts current permissions'
            )
        normalized[strategy_id] = {
            'suitability': suitability,
            'supporting_factors': supporting,
            'conflicting_factors': conflicting,
        }
    return normalized


def _context_numbers(value):
    numbers = []
    if isinstance(value, bool):
        return numbers
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        numbers.append(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            numbers.extend(_context_numbers(item))
    elif isinstance(value, list):
        for item in value:
            numbers.extend(_context_numbers(item))
    return numbers


def _validate_narrative_numbers(strings, context, extra_allowed):
    allowed = _context_numbers(context) + [float(item) for item in extra_allowed]
    for narrative in strings:
        if not isinstance(narrative, str):
            continue
        for match in NUMBER_PATTERN.findall(narrative):
            number = float(match)
            if not any(math.isclose(number, item, rel_tol=1e-9, abs_tol=1e-9) for item in allowed):
                raise UnifiedAnalysisValidationError(
                    'narrative contains a numeric value absent from context',
                    reason_code='llm_evidence_validation_failed',
                )


def _quantitative_assessment(context):
    source = context.get('quantitative_assessment') or {}
    return {
        'preliminary_regime': source.get('preliminary_regime'),
        'suggested_strategy': source.get('suggested_strategy'),
        'confidence': source.get('confidence'),
        'risk_off': source.get('risk_off') is True,
        'allow_new_long': source.get('allow_new_long') is True,
        'explanation': [
            item for item in (source.get('explanation') or [])
            if isinstance(item, str) and item.strip()
        ],
    }


def normalize_unified_analysis(data, context):
    """Validate LLM comparison, verify evidence, and enforce risk limits."""

    if not isinstance(data, dict):
        raise UnifiedAnalysisValidationError('analysis must be a JSON object')
    _require_exact_fields(data, TOP_LEVEL_FIELDS, 'analysis')

    market = _section(data, 'final_market_assessment')
    strategy = _section(data, 'final_strategy_assessment')
    agreement = _section(data, 'quantitative_agreement')
    risk = _section(data, 'risk_assessment')
    _require_exact_fields(market, {'regime', 'direction', 'confidence', 'summary'}, 'final_market_assessment')
    _require_exact_fields(
        strategy,
        {'selected_strategy', 'confidence', 'suitability', 'reason', 'why_not_alternatives'},
        'final_strategy_assessment',
    )
    _require_exact_fields(agreement, {'agrees_with_backend', 'differences'}, 'quantitative_agreement')
    _require_exact_fields(risk, {'risk_level', 'risk_off', 'allow_new_long', 'summary'}, 'risk_assessment')

    candidate_ids = _candidate_ids(context)
    comparison = _normalize_strategy_comparison(data.get('strategy_comparison'), context, candidate_ids)
    final_regime = _enum(market.get('regime'), ALLOWED_REGIMES, 'final_market_assessment.regime')
    final_strategy = _enum(
        strategy.get('selected_strategy'), set(candidate_ids),
        'final_strategy_assessment.selected_strategy',
    )
    currently_allowed = _currently_allowed_ids(context, candidate_ids)
    if final_strategy not in currently_allowed:
        raise UnifiedAnalysisValidationError(
            'selected strategy is prohibited by current hard constraints',
            reason_code='llm_strategy_not_allowed',
        )

    final_suitability = _enum(
        strategy.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY,
        'final_strategy_assessment.suitability',
    )
    if comparison[final_strategy]['suitability'] != final_suitability:
        raise UnifiedAnalysisValidationError('final suitability contradicts strategy comparison')
    if final_suitability in {'not_allowed', 'insufficient_evidence'}:
        raise UnifiedAnalysisValidationError('selected strategy cannot be unavailable or prohibited')
    if final_strategy in ACTIVE_STRATEGIES and final_suitability == 'low':
        raise UnifiedAnalysisValidationError('an active strategy with low suitability cannot be selected')

    why_not = _string_list(
        strategy.get('why_not_alternatives'), 'final_strategy_assessment.why_not_alternatives',
    )
    if len(why_not) < len(candidate_ids) - 1:
        raise UnifiedAnalysisValidationError('why_not_alternatives must address every non-selected candidate')

    agrees = _boolean(agreement.get('agrees_with_backend'), 'quantitative_agreement.agrees_with_backend')
    differences = _string_list(agreement.get('differences'), 'quantitative_agreement.differences')
    evidence = _normalize_evidence(
        data.get('supporting_evidence'), context,
        field_name='supporting_evidence', allow_empty=False,
    )
    limitations = _string_list(data.get('limitations'), 'limitations')

    quantitative = _quantitative_assessment(context)
    same_regime = final_regime == quantitative.get('preliminary_regime')
    same_strategy = final_strategy == quantitative.get('suggested_strategy')
    if agrees and not (same_regime and same_strategy):
        raise UnifiedAnalysisValidationError('agreement contradicts final assessments')
    if not agrees and not differences:
        raise UnifiedAnalysisValidationError('differences are required when backend assessment is rejected')

    llm_allow_new_long = _boolean(risk.get('allow_new_long'), 'risk_assessment.allow_new_long')
    llm_risk_off = _boolean(risk.get('risk_off'), 'risk_assessment.risk_off')
    constraints = context.get('hard_constraints') or {}
    backend_allow_new_long = constraints.get('allow_new_long') is True
    backend_risk_off = constraints.get('risk_off') is True
    effective_allow_new_long = llm_allow_new_long and backend_allow_new_long
    effective_risk_off = llm_risk_off or backend_risk_off
    if final_strategy in ACTIVE_STRATEGIES and (not effective_allow_new_long or effective_risk_off):
        raise UnifiedAnalysisValidationError(
            'active strategy conflicts with effective risk constraints',
            reason_code='llm_strategy_not_allowed',
        )
    if final_strategy == STRATEGY_RISK_OFF and not effective_risk_off:
        raise UnifiedAnalysisValidationError('risk_off selection requires risk_off=true')

    expected_backtest_evidence = (
        (context.get('strategy_evidence') or {}).get('backtest_evidence_available') is True
    )
    llm_backtest_evidence = _boolean(data.get('backtest_evidence_available'), 'backtest_evidence_available')
    if llm_backtest_evidence != expected_backtest_evidence:
        raise UnifiedAnalysisValidationError(
            'backtest_evidence_available contradicts the Agent Context',
            reason_code='llm_evidence_validation_failed',
        )

    market_confidence = _confidence(market.get('confidence'), 'final_market_assessment.confidence')
    strategy_confidence = _confidence(strategy.get('confidence'), 'final_strategy_assessment.confidence')
    comparison_interpretations = [
        item['interpretation']
        for candidate in comparison.values()
        for key in ('supporting_factors', 'conflicting_factors')
        for item in candidate[key]
    ]
    _validate_narrative_numbers(
        [
            market.get('summary'), strategy.get('reason'), risk.get('summary'),
            *why_not, *differences, *limitations, *comparison_interpretations,
            *[item['interpretation'] for item in evidence],
        ],
        context,
        [market_confidence, strategy_confidence],
    )

    return {
        'analysis_version': AGENT_ANALYSIS_VERSION,
        'analysis_status': 'success',
        'decision_source': 'llm_synthesis',
        'fallback_reason': None,
        'final_market_assessment': {
            'regime': final_regime,
            'direction': _enum(market.get('direction'), ALLOWED_DIRECTIONS, 'final_market_assessment.direction'),
            'confidence': market_confidence,
            'summary': _string(market.get('summary'), 'final_market_assessment.summary'),
        },
        'strategy_comparison': comparison,
        'final_strategy_assessment': {
            'selected_strategy': final_strategy,
            'confidence': strategy_confidence,
            'suitability': final_suitability,
            'reason': _string(strategy.get('reason'), 'final_strategy_assessment.reason'),
            'why_not_alternatives': why_not,
        },
        'quantitative_assessment': quantitative,
        'quantitative_agreement': {'agrees_with_backend': agrees, 'differences': differences},
        'risk_assessment': {
            'risk_level': _enum(risk.get('risk_level'), ALLOWED_RISK_LEVELS, 'risk_assessment.risk_level'),
            'risk_off': effective_risk_off,
            'allow_new_long': effective_allow_new_long,
            'summary': _string(risk.get('summary'), 'risk_assessment.summary'),
        },
        'backtest_evidence_available': llm_backtest_evidence,
        'available_strategies': context.get('available_strategies') or [],
        'related_backtest_strategy': context.get('related_backtest_strategy'),
        'supporting_evidence': evidence,
        'limitations': limitations,
    }


def _fallback_direction(context):
    direction = ((context.get('market_regime') or {}).get('direction') or '').lower()
    return direction if direction in ALLOWED_DIRECTIONS else 'neutral'


def _fallback_risk_level(context):
    constraints = context.get('hard_constraints') or {}
    volatility = (context.get('market_regime') or {}).get('volatility') or {}
    percentile = volatility.get('volatility_percentile')
    if constraints.get('risk_off') is True:
        return 'high'
    if constraints.get('allow_new_long') is not True:
        return 'medium'
    if isinstance(percentile, (int, float)) and percentile >= 0.85:
        return 'high'
    return 'medium'


def _fallback_confidence(value, default=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return round(min(1.0, max(0.0, float(value))), 6)


def build_quantitative_fallback(context, fallback_reason):
    """Convert deterministic preliminary facts into a safe v3 response."""

    quantitative = _quantitative_assessment(context)
    constraints = context.get('hard_constraints') or {}
    explanations = quantitative.get('explanation') or []
    candidate_ids = _candidate_ids(context)
    currently_allowed = _currently_allowed_ids(context, candidate_ids)
    suggested = quantitative.get('suggested_strategy')
    allow_new_long = constraints.get('allow_new_long') is True
    risk_off = constraints.get('risk_off') is True
    if risk_off and STRATEGY_RISK_OFF in currently_allowed:
        selected_strategy = STRATEGY_RISK_OFF
    elif not allow_new_long and STRATEGY_NO_STRATEGY in currently_allowed:
        selected_strategy = STRATEGY_NO_STRATEGY
    elif suggested in currently_allowed:
        selected_strategy = suggested
    else:
        selected_strategy = STRATEGY_NO_STRATEGY

    comparison = {}
    for strategy_id in candidate_ids:
        if strategy_id not in currently_allowed:
            suitability = 'not_allowed'
        elif strategy_id == selected_strategy:
            suitability = 'high'
        elif strategy_id == suggested:
            suitability = 'medium'
        else:
            suitability = 'insufficient_evidence'
        comparison[strategy_id] = {
            'suitability': suitability,
            'supporting_factors': [],
            'conflicting_factors': [],
        }

    preferred_factors = {
        'Preliminary Regime', 'Suggested Strategy', 'ADX',
        'Choppiness Index', 'Volatility Percentile',
    }
    evidence = [
        {
            'factor': item['factor'],
            'value': item['value'],
            'interpretation': 'Deterministic input retained for the quantitative fallback.',
        }
        for item in (context.get('evidence_catalog') or [])
        if isinstance(item, dict) and item.get('factor') in preferred_factors
    ][:4]
    limitations = [
        'DeepSeek synthesis was unavailable; the final result uses the deterministic quantitative fallback.',
        'Comparable candidate backtest evidence is unavailable.',
    ]
    data_quality = context.get('data_quality') or {}
    unavailable = [name for name, available in data_quality.items() if available is False]
    if unavailable:
        limitations.append('Unavailable context modules: ' + ', '.join(sorted(unavailable)) + '.')

    same_strategy = selected_strategy == suggested
    differences = [] if same_strategy else [
        'The safe fallback strategy differs from the preliminary strategy because current hard constraints prohibit it.'
    ]
    why_not = [
        f'{strategy_id} was not selected because the deterministic fallback ranked it below {selected_strategy}.'
        for strategy_id in candidate_ids if strategy_id != selected_strategy
    ]
    return {
        'analysis_version': AGENT_ANALYSIS_VERSION,
        'analysis_status': 'fallback',
        'decision_source': 'quantitative_fallback',
        'fallback_reason': fallback_reason,
        'final_market_assessment': {
            'regime': quantitative.get('preliminary_regime'),
            'direction': _fallback_direction(context),
            'confidence': _fallback_confidence(quantitative.get('confidence')),
            'summary': explanations[0] if explanations else 'Deterministic market regime retained as the fallback assessment.',
        },
        'strategy_comparison': comparison,
        'final_strategy_assessment': {
            'selected_strategy': selected_strategy,
            'confidence': _fallback_confidence(quantitative.get('confidence')),
            'suitability': comparison[selected_strategy]['suitability'],
            'reason': explanations[-1] if explanations else 'Deterministic strategy selection retained as the fallback assessment.',
            'why_not_alternatives': why_not,
        },
        'quantitative_assessment': quantitative,
        'quantitative_agreement': {
            'agrees_with_backend': same_strategy,
            'differences': differences,
        },
        'risk_assessment': {
            'risk_level': _fallback_risk_level(context),
            'risk_off': risk_off,
            'allow_new_long': allow_new_long,
            'summary': 'Django hard risk constraints remain authoritative in fallback mode.',
        },
        'backtest_evidence_available': (
            (context.get('strategy_evidence') or {}).get('backtest_evidence_available') is True
        ),
        'available_strategies': context.get('available_strategies') or [],
        'related_backtest_strategy': context.get('related_backtest_strategy'),
        'supporting_evidence': evidence,
        'limitations': limitations,
    }


__all__ = [
    'AGENT_ANALYSIS_PROMPT_VERSION', 'AGENT_ANALYSIS_VERSION',
    'UnifiedAnalysisValidationError', 'build_quantitative_fallback',
    'has_forbidden_action_language', 'has_open_close_direction_contradiction',
    'normalize_unified_analysis',
]
