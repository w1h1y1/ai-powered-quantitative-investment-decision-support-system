"""Validated quantitative-comparison + LLM-synthesis schema."""

import json
import math
import re
from copy import deepcopy

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

ENUM_ALIASES = {
    'regime': {
        'bullish trend': REGIME_BULLISH,
        'bearish trend': REGIME_BEARISH,
        'sideways range': REGIME_SIDEWAYS,
        'high volatility': REGIME_HIGH_VOLATILITY,
    },
    'direction': {value: value for value in ALLOWED_DIRECTIONS},
    'suitability': {
        'high': 'high', 'medium': 'medium', 'low': 'low',
        'not allowed': 'not_allowed',
        'insufficient evidence': 'insufficient_evidence',
    },
    'risk_level': {value: value for value in ALLOWED_RISK_LEVELS},
    'strategy': {
        'trend following': STRATEGY_TREND_FOLLOWING,
        'mean reversion': STRATEGY_MEAN_REVERSION,
        'risk off': STRATEGY_RISK_OFF,
        'defensive risk off': STRATEGY_RISK_OFF,
        'no strategy': STRATEGY_NO_STRATEGY,
        'no suitable strategy': STRATEGY_NO_STRATEGY,
    },
}


class UnifiedAnalysisValidationError(ValueError):
    """Raised when provider output is unsafe or does not match v3."""

    def __init__(
        self,
        message,
        *,
        reason_code='llm_schema_validation_failed',
        stage='schema',
        error_code='schema_mismatch',
        path=None,
        expected=None,
        actual=None,
        missing_fields=None,
        extra_fields=None,
        illegal_strategy_id=None,
        hard_constraint_triggered=False,
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.stage = stage
        self.error_code = error_code
        self.path = path
        self.expected = expected
        self.actual_type = type(actual).__name__ if actual is not None else None
        self.actual = actual if isinstance(actual, (str, int, float, bool)) else None
        self.missing_fields = sorted(missing_fields or [])
        self.extra_fields = sorted(extra_fields or [])
        self.illegal_strategy_id = illegal_strategy_id
        self.hard_constraint_triggered = hard_constraint_triggered

    def safe_details(self):
        """Return bounded diagnostics safe for logs and repair prompts."""

        actual = self.actual
        if self.error_code == 'invalid_type' and isinstance(actual, str):
            actual = None
        if isinstance(actual, str):
            actual = actual[:120]
        return {
            'validation_stage': self.stage,
            'validation_error_code': self.error_code,
            'validation_error_path': self.path,
            'expected': self.expected,
            'actual_type': self.actual_type,
            'actual': actual,
            'missing_fields': self.missing_fields,
            'extra_fields': self.extra_fields,
            'illegal_strategy_id': self.illegal_strategy_id,
            'hard_constraint_triggered': self.hard_constraint_triggered,
        }


def _alias_key(value):
    if not isinstance(value, str):
        return None
    return re.sub(r'[\s_\-/]+', ' ', value.strip().lower()).strip()


def _normalize_enum_format(value, enum_name):
    key = _alias_key(value)
    if key is None:
        return value
    return ENUM_ALIASES[enum_name].get(key, value)


def _normalize_confidence_format(value):
    if isinstance(value, bool):
        return value
    number = value
    is_percent = False
    if isinstance(value, str):
        stripped = value.strip()
        is_percent = stripped.endswith('%')
        if is_percent:
            stripped = stripped[:-1].strip()
        try:
            number = float(stripped)
        except ValueError:
            return value
    if not isinstance(number, (int, float)) or not math.isfinite(float(number)):
        return value
    number = float(number)
    if is_percent or 1 < number <= 100:
        number /= 100
    return number


def standardize_unified_analysis_input(data):
    """Apply only finite, semantics-preserving model-output normalizations."""

    if not isinstance(data, dict):
        return data, []
    standardized = deepcopy(data)
    changes = []

    def replace(container, key, normalized, path):
        if isinstance(container, dict) and key in container and container[key] != normalized:
            container[key] = normalized
            changes.append(path)

    market = standardized.get('final_market_assessment')
    if isinstance(market, dict):
        replace(market, 'regime', _normalize_enum_format(market.get('regime'), 'regime'), 'final_market_assessment.regime')
        replace(market, 'direction', _normalize_enum_format(market.get('direction'), 'direction'), 'final_market_assessment.direction')
        replace(market, 'confidence', _normalize_confidence_format(market.get('confidence')), 'final_market_assessment.confidence')

    comparison = standardized.get('strategy_comparison')
    if isinstance(comparison, dict):
        normalized_comparison = {}
        collision = False
        for strategy_id, candidate in comparison.items():
            normalized_id = _normalize_enum_format(strategy_id, 'strategy')
            if normalized_id in normalized_comparison:
                collision = True
                break
            normalized_comparison[normalized_id] = candidate
            if normalized_id != strategy_id:
                changes.append(f'strategy_comparison.{strategy_id}')
        if not collision:
            standardized['strategy_comparison'] = normalized_comparison
            comparison = normalized_comparison
        for strategy_id, candidate in comparison.items():
            if isinstance(candidate, dict):
                replace(
                    candidate, 'suitability',
                    _normalize_enum_format(candidate.get('suitability'), 'suitability'),
                    f'strategy_comparison.{strategy_id}.suitability',
                )

    strategy = standardized.get('final_strategy_assessment')
    if isinstance(strategy, dict):
        replace(strategy, 'selected_strategy', _normalize_enum_format(strategy.get('selected_strategy'), 'strategy'), 'final_strategy_assessment.selected_strategy')
        replace(strategy, 'suitability', _normalize_enum_format(strategy.get('suitability'), 'suitability'), 'final_strategy_assessment.suitability')
        replace(strategy, 'confidence', _normalize_confidence_format(strategy.get('confidence')), 'final_strategy_assessment.confidence')

    risk = standardized.get('risk_assessment')
    if isinstance(risk, dict):
        replace(risk, 'risk_level', _normalize_enum_format(risk.get('risk_level'), 'risk_level'), 'risk_assessment.risk_level')

    return standardized, changes


def _string(value, field_name):
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise UnifiedAnalysisValidationError(
        f'{field_name} must be a non-empty string',
        error_code='invalid_type', path=field_name,
        expected='non-empty string', actual=value,
    )


def _string_list(value, field_name):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnifiedAnalysisValidationError(
            f'{field_name} must be an array of strings',
            error_code='invalid_type', path=field_name,
            expected='array of strings', actual=value,
        )
    return [item.strip() for item in value if item.strip()]


def _section(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, dict):
        raise UnifiedAnalysisValidationError(
            f'missing required field: {field_name}',
            error_code='missing_field', path=field_name,
            expected='object', actual=value, missing_fields=[field_name],
        )
    return value


def _require_exact_fields(value, expected, field_name):
    actual_fields = set(value)
    expected_fields = set(expected)
    if actual_fields != expected_fields:
        raise UnifiedAnalysisValidationError(
            f'{field_name} has missing or extra fields',
            error_code='field_set_mismatch', path=field_name,
            expected='exact required field set',
            missing_fields=expected_fields - actual_fields,
            extra_fields=actual_fields - expected_fields,
        )


def _enum(value, allowed, field_name):
    if value not in allowed:
        raise UnifiedAnalysisValidationError(
            f'{field_name} has an unsupported value',
            error_code='invalid_enum', path=field_name,
            expected='|'.join(sorted(allowed)), actual=value,
            illegal_strategy_id=(
                value if field_name.endswith('selected_strategy') else None
            ),
        )
    return value


def _boolean(value, field_name):
    if not isinstance(value, bool):
        raise UnifiedAnalysisValidationError(
            f'{field_name} must be a boolean',
            error_code='invalid_type', path=field_name,
            expected='boolean', actual=value,
        )
    return value


def _confidence(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnifiedAnalysisValidationError(
            f'{field_name} must be numeric',
            error_code='invalid_type', path=field_name,
            expected='JSON number from 0 to 1', actual=value,
        )
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise UnifiedAnalysisValidationError(
            f'{field_name} must be between 0 and 1',
            error_code='out_of_range', path=field_name,
            expected='JSON number from 0 to 1', actual=value,
        )
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
        raise UnifiedAnalysisValidationError(
            f'{field_name} must be {qualifier}',
            error_code='invalid_type', path=field_name,
            expected=qualifier, actual=value,
        )
    catalog = {
        item.get('factor'): item.get('value')
        for item in (context.get('evidence_catalog') or [])
        if isinstance(item, dict) and isinstance(item.get('factor'), str)
    }
    normalized = []
    for index, item in enumerate(value):
        item_name = f'{field_name}[{index}]'
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(
                f'{item_name} must be an object',
                error_code='invalid_type', path=item_name,
                expected='object', actual=item,
            )
        _require_exact_fields(item, {'factor', 'value', 'interpretation'}, item_name)
        factor = _string(item.get('factor'), f'{item_name}.factor')
        if factor not in catalog:
            raise UnifiedAnalysisValidationError(
                f'{item_name} references an unavailable factor',
                reason_code='llm_evidence_validation_failed',
                stage='business_rule', error_code='unknown_evidence_factor',
                path=f'{item_name}.factor', expected='exact evidence_catalog factor',
                actual=factor,
            )
        evidence_value = item.get('value')
        if not _same_value(evidence_value, catalog[factor]):
            raise UnifiedAnalysisValidationError(
                f'{item_name} value does not match context',
                reason_code='llm_evidence_validation_failed',
                stage='business_rule', error_code='evidence_value_mismatch',
                path=f'{item_name}.value', expected=repr(catalog[factor]),
                actual=evidence_value,
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
        actual_ids = set(value) if isinstance(value, dict) else set()
        raise UnifiedAnalysisValidationError(
            'strategy_comparison must contain every available strategy exactly once',
            error_code='field_set_mismatch', path='strategy_comparison',
            expected='|'.join(candidate_ids), actual=value,
            missing_fields=set(candidate_ids) - actual_ids,
            extra_fields=actual_ids - set(candidate_ids),
        )
    normalized = {}
    currently_allowed = _currently_allowed_ids(context, candidate_ids)
    for strategy_id in candidate_ids:
        item = value.get(strategy_id)
        field_name = f'strategy_comparison.{strategy_id}'
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(
                f'{field_name} must be an object',
                error_code='invalid_type', path=field_name,
                expected='object', actual=item,
            )
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
                stage='business_rule', error_code='non_comparable_backtest_evidence',
                path=field_name,
            )
        suitability = _enum(
                item.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY,
                f'{field_name}.suitability',
            )
        if strategy_id not in currently_allowed and suitability != 'not_allowed':
            raise UnifiedAnalysisValidationError(
                f'{field_name}.suitability must be not_allowed under current constraints',
                reason_code='llm_strategy_not_allowed',
                stage='business_rule', error_code='hard_constraint_violation',
                path=f'{field_name}.suitability', expected='not_allowed',
                actual=suitability, hard_constraint_triggered=True,
            )
        if strategy_id in currently_allowed and suitability == 'not_allowed':
            raise UnifiedAnalysisValidationError(
                f'{field_name}.suitability contradicts current permissions',
                stage='business_rule', error_code='permission_contradiction',
                path=f'{field_name}.suitability',
                expected='high|medium|low|insufficient_evidence',
                actual=suitability,
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
                    stage='business_rule', error_code='unverified_numeric_value',
                    path='narrative', expected='numbers present in Agent Context',
                    actual=match,
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


def normalize_unified_analysis(data, context, *, already_standardized=False):
    """Validate LLM comparison, verify evidence, and enforce risk limits."""

    if not isinstance(data, dict):
        raise UnifiedAnalysisValidationError(
            'analysis must be a JSON object', error_code='invalid_type',
            path='analysis', expected='object', actual=data,
        )
    if not already_standardized:
        data, _ = standardize_unified_analysis_input(data)
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
            stage='business_rule', error_code='hard_constraint_violation',
            path='final_strategy_assessment.selected_strategy',
            expected='|'.join(sorted(currently_allowed)), actual=final_strategy,
            illegal_strategy_id=final_strategy, hard_constraint_triggered=True,
        )

    final_suitability = _enum(
        strategy.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY,
        'final_strategy_assessment.suitability',
    )
    if comparison[final_strategy]['suitability'] != final_suitability:
        raise UnifiedAnalysisValidationError(
            'final suitability contradicts strategy comparison',
            error_code='cross_field_mismatch',
            path='final_strategy_assessment.suitability',
            expected=comparison[final_strategy]['suitability'], actual=final_suitability,
        )
    if final_suitability in {'not_allowed', 'insufficient_evidence'}:
        raise UnifiedAnalysisValidationError(
            'selected strategy cannot be unavailable or prohibited',
            stage='business_rule', error_code='invalid_selected_suitability',
            path='final_strategy_assessment.suitability',
            expected='high|medium|low', actual=final_suitability,
        )
    if final_strategy in ACTIVE_STRATEGIES and final_suitability == 'low':
        raise UnifiedAnalysisValidationError(
            'an active strategy with low suitability cannot be selected',
            stage='business_rule', error_code='invalid_selected_suitability',
            path='final_strategy_assessment.suitability',
            expected='high|medium', actual=final_suitability,
        )

    why_not = _string_list(
        strategy.get('why_not_alternatives'), 'final_strategy_assessment.why_not_alternatives',
    )
    if len(why_not) < len(candidate_ids) - 1:
        raise UnifiedAnalysisValidationError(
            'why_not_alternatives must address every non-selected candidate',
            error_code='insufficient_items',
            path='final_strategy_assessment.why_not_alternatives',
            expected=f'at least {len(candidate_ids) - 1} strings', actual=len(why_not),
        )

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
        raise UnifiedAnalysisValidationError(
            'agreement contradicts final assessments',
            error_code='cross_field_mismatch',
            path='quantitative_agreement.agrees_with_backend',
            expected='false when final regime or strategy differs', actual=agrees,
        )
    if not agrees and not differences:
        raise UnifiedAnalysisValidationError(
            'differences are required when backend assessment is rejected',
            error_code='insufficient_items', path='quantitative_agreement.differences',
            expected='non-empty array of strings', actual=differences,
        )

    llm_allow_new_long = _boolean(risk.get('allow_new_long'), 'risk_assessment.allow_new_long')
    llm_risk_off = _boolean(risk.get('risk_off'), 'risk_assessment.risk_off')
    constraints = context.get('hard_constraints') or {}
    backend_allow_new_long = constraints.get('allow_new_long') is True
    backend_risk_off = constraints.get('risk_off') is True
    if not backend_allow_new_long and llm_allow_new_long:
        raise UnifiedAnalysisValidationError(
            'allow_new_long=true attempts to relax a backend hard constraint',
            reason_code='llm_strategy_not_allowed',
            stage='business_rule', error_code='hard_constraint_violation',
            path='risk_assessment.allow_new_long', expected=False,
            actual=True, hard_constraint_triggered=True,
        )
    if backend_risk_off and not llm_risk_off:
        raise UnifiedAnalysisValidationError(
            'risk_off=false attempts to relax a backend hard constraint',
            reason_code='llm_strategy_not_allowed',
            stage='business_rule', error_code='hard_constraint_violation',
            path='risk_assessment.risk_off', expected=True,
            actual=False, hard_constraint_triggered=True,
        )
    effective_allow_new_long = llm_allow_new_long and backend_allow_new_long
    effective_risk_off = llm_risk_off or backend_risk_off
    if final_strategy in ACTIVE_STRATEGIES and (not effective_allow_new_long or effective_risk_off):
        raise UnifiedAnalysisValidationError(
            'active strategy conflicts with effective risk constraints',
            reason_code='llm_strategy_not_allowed',
            stage='business_rule', error_code='hard_constraint_violation',
            path='final_strategy_assessment.selected_strategy',
            expected='risk_off|no_strategy', actual=final_strategy,
            illegal_strategy_id=final_strategy, hard_constraint_triggered=True,
        )
    if final_strategy == STRATEGY_RISK_OFF and not effective_risk_off:
        raise UnifiedAnalysisValidationError(
            'risk_off selection requires risk_off=true',
            stage='business_rule', error_code='cross_field_mismatch',
            path='risk_assessment.risk_off', expected=True, actual=False,
        )

    expected_backtest_evidence = (
        (context.get('strategy_evidence') or {}).get('backtest_evidence_available') is True
    )
    llm_backtest_evidence = _boolean(data.get('backtest_evidence_available'), 'backtest_evidence_available')
    if llm_backtest_evidence != expected_backtest_evidence:
        raise UnifiedAnalysisValidationError(
            'backtest_evidence_available contradicts the Agent Context',
            reason_code='llm_evidence_validation_failed',
            stage='business_rule', error_code='evidence_availability_mismatch',
            path='backtest_evidence_available',
            expected=expected_backtest_evidence, actual=llm_backtest_evidence,
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
    'normalize_unified_analysis', 'standardize_unified_analysis_input',
]
