"""Validation and deterministic merge for independent Investment Agent judgments."""

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


AGENT_ANALYSIS_VERSION = 'investment_agent_analysis_v4'
AGENT_ANALYSIS_PROMPT_VERSION = 'investment_agent_analysis_prompt_v4'

ALLOWED_REGIMES = {
    REGIME_BEARISH, REGIME_BULLISH, REGIME_HIGH_VOLATILITY, REGIME_SIDEWAYS,
}
ALLOWED_DIRECTIONS = {'bullish', 'bearish', 'neutral', 'mixed'}
ALLOWED_CANDIDATE_SUITABILITY = {
    'high', 'medium', 'low', 'not_allowed', 'insufficient_evidence',
}
ALLOWED_RISK_LEVELS = {'low', 'medium', 'high'}
ACTIVE_STRATEGIES = {STRATEGY_TREND_FOLLOWING, STRATEGY_MEAN_REVERSION}
LLM_TOP_LEVEL_FIELDS = {
    'llm_market_assessment', 'llm_strategy_comparison',
    'llm_final_strategy_assessment', 'llm_risk_assessment',
    'backtest_evidence_available', 'supporting_evidence', 'limitations',
}
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
    """A bounded, user-safe LLM response validation failure."""

    def __init__(
        self, message, *, reason_code='llm_schema_validation_failed',
        stage='schema', error_code='schema_mismatch', path=None,
        expected=None, actual=None, missing_fields=None, extra_fields=None,
        illegal_strategy_id=None, hard_constraint_triggered=False,
        source_path=None,
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
        self.source_path = source_path

    def safe_details(self):
        actual = self.actual
        source_path = self.source_path
        if self.error_code == 'invalid_type' and isinstance(actual, str):
            actual = None
        if isinstance(actual, str):
            actual = actual[:120]
        if isinstance(source_path, str):
            source_path = source_path[:160]
        return {
            'validation_stage': self.stage,
            'validation_error_code': self.error_code,
            'validation_error_path': self.path,
            'validation_error_value': actual,
            'validation_source_path': source_path,
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
    return ENUM_ALIASES[enum_name].get(key, value) if key is not None else value


def _normalize_confidence_format(value):
    if isinstance(value, bool):
        return value
    number = value
    percent = False
    if isinstance(value, str):
        stripped = value.strip()
        percent = stripped.endswith('%')
        if percent:
            stripped = stripped[:-1].strip()
        try:
            number = float(stripped)
        except ValueError:
            return value
    if not isinstance(number, (int, float)) or not math.isfinite(float(number)):
        return value
    number = float(number)
    return number / 100 if percent or 1 < number <= 100 else number


def standardize_unified_analysis_input(data):
    """Normalize harmless real-provider formatting variants before v4 validation."""

    if not isinstance(data, dict):
        return data, []
    value = deepcopy(data)
    changes = []
    legacy_names = {
        'final_market_assessment': 'llm_market_assessment',
        'strategy_comparison': 'llm_strategy_comparison',
        'final_strategy_assessment': 'llm_final_strategy_assessment',
        'risk_assessment': 'llm_risk_assessment',
    }
    for old, new in legacy_names.items():
        if old in value and new not in value:
            value[new] = value.pop(old)
            changes.append(old)
    if 'quantitative_agreement' in value:
        value.pop('quantitative_agreement')
        changes.append('quantitative_agreement')
    risk = value.get('llm_risk_assessment')
    if isinstance(risk, dict):
        for obsolete in ('risk_off', 'allow_new_long'):
            if obsolete in risk:
                risk.pop(obsolete)
                changes.append(f'llm_risk_assessment.{obsolete}')

    def replace(container, key, normalized, path):
        if isinstance(container, dict) and key in container and container[key] != normalized:
            container[key] = normalized
            changes.append(path)

    market = value.get('llm_market_assessment')
    if isinstance(market, dict):
        replace(market, 'regime', _normalize_enum_format(market.get('regime'), 'regime'), 'llm_market_assessment.regime')
        replace(market, 'direction', _normalize_enum_format(market.get('direction'), 'direction'), 'llm_market_assessment.direction')
        replace(market, 'confidence', _normalize_confidence_format(market.get('confidence')), 'llm_market_assessment.confidence')
    comparison = value.get('llm_strategy_comparison')
    if isinstance(comparison, dict):
        normalized_comparison = {}
        for strategy_id, candidate in comparison.items():
            normalized_id = _normalize_enum_format(strategy_id, 'strategy')
            if normalized_id in normalized_comparison:
                normalized_comparison = comparison
                break
            normalized_comparison[normalized_id] = candidate
            if normalized_id != strategy_id:
                changes.append(f'llm_strategy_comparison.{strategy_id}')
        value['llm_strategy_comparison'] = normalized_comparison
        for strategy_id, candidate in normalized_comparison.items():
            if isinstance(candidate, dict):
                replace(candidate, 'suitability', _normalize_enum_format(candidate.get('suitability'), 'suitability'), f'llm_strategy_comparison.{strategy_id}.suitability')
    strategy = value.get('llm_final_strategy_assessment')
    if isinstance(strategy, dict):
        replace(strategy, 'selected_strategy', _normalize_enum_format(strategy.get('selected_strategy'), 'strategy'), 'llm_final_strategy_assessment.selected_strategy')
        replace(strategy, 'suitability', _normalize_enum_format(strategy.get('suitability'), 'suitability'), 'llm_final_strategy_assessment.suitability')
        replace(strategy, 'confidence', _normalize_confidence_format(strategy.get('confidence')), 'llm_final_strategy_assessment.confidence')
    if isinstance(risk, dict):
        replace(risk, 'risk_level', _normalize_enum_format(risk.get('risk_level'), 'risk_level'), 'llm_risk_assessment.risk_level')
    return value, changes


def _string(value, path):
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise UnifiedAnalysisValidationError(
        f'{path} must be a non-empty string', error_code='invalid_type',
        path=path, expected='non-empty string', actual=value,
    )


def _string_list(value, path):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnifiedAnalysisValidationError(
            f'{path} must be an array of strings', error_code='invalid_type',
            path=path, expected='array of strings', actual=value,
        )
    return [item.strip() for item in value if item.strip()]


def _boolean(value, path):
    if not isinstance(value, bool):
        raise UnifiedAnalysisValidationError(
            f'{path} must be boolean', error_code='invalid_type', path=path,
            expected='boolean', actual=value,
        )
    return value


def _confidence(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnifiedAnalysisValidationError(
            f'{path} must be numeric', error_code='invalid_type', path=path,
            expected='JSON number from 0 to 1', actual=value,
        )
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise UnifiedAnalysisValidationError(
            f'{path} is outside range', error_code='out_of_range', path=path,
            expected='JSON number from 0 to 1', actual=value,
        )
    return round(number, 6)


def _enum(value, allowed, path):
    if value not in allowed:
        raise UnifiedAnalysisValidationError(
            f'{path} has an unsupported value', error_code='invalid_enum',
            path=path, expected='|'.join(sorted(allowed)), actual=value,
            illegal_strategy_id=value if path.endswith('selected_strategy') else None,
        )
    return value


def _section(data, name):
    value = data.get(name)
    if not isinstance(value, dict):
        raise UnifiedAnalysisValidationError(
            f'{name} is required', error_code='missing_field', path=name,
            expected='object', actual=value, missing_fields=[name],
        )
    return value


def _require_exact_fields(value, expected, path):
    actual = set(value)
    expected = set(expected)
    if actual != expected:
        raise UnifiedAnalysisValidationError(
            f'{path} has missing or extra fields', error_code='field_set_mismatch',
            path=path, expected='exact required field set',
            missing_fields=expected - actual, extra_fields=actual - expected,
        )


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
    phrases = {
        'Down': ('closed higher', 'up from the open', 'rose from the open', 'closed above the open'),
        'Up': ('closed lower', 'down from the open', 'fell from the open', 'closed below the open'),
        'Flat': ('closed higher', 'closed lower', 'up from the open', 'down from the open'),
    }
    return any(phrase in text for phrase in phrases[direction])


def _same_value(actual, expected):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)
    return actual == expected


def _normalize_evidence(value, context, *, path, allow_empty):
    if not isinstance(value, list) or (not allow_empty and not value):
        expected = 'array' if allow_empty else 'non-empty array'
        raise UnifiedAnalysisValidationError(
            f'{path} must be {expected}', error_code='invalid_type', path=path,
            expected=expected, actual=value,
        )
    catalog = {
        item.get('source_path'): item
        for item in (context.get('evidence_catalog') or [])
        if isinstance(item, dict) and isinstance(item.get('source_path'), str)
    }
    normalized = []
    for index, item in enumerate(value):
        item_path = f'{path}[{index}]'
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(
                f'{item_path} must be an object', error_code='invalid_type',
                path=item_path, expected='object', actual=item,
            )
        actual_fields = set(item)
        accepted_fields = (
            {'factor', 'source_path', 'value', 'interpretation'},
            {'factor', 'value', 'interpretation'},
        )
        if actual_fields not in accepted_fields:
            _require_exact_fields(item, accepted_fields[0], item_path)
        factor = _string(item.get('factor'), f'{item_path}.factor')
        source_path = item.get('source_path')
        if source_path is None:
            matches = [
                candidate_path for candidate_path, candidate in catalog.items()
                if candidate.get('factor') == factor
            ]
            if len(matches) == 1:
                source_path = matches[0]
        source_path = _string(source_path, f'{item_path}.source_path')
        source = catalog.get(source_path)
        if source is None:
            raise UnifiedAnalysisValidationError(
                f'{item_path} references an unknown source path',
                reason_code='llm_evidence_validation_failed', stage='evidence',
                error_code='unknown_evidence_source_path', path=f'{item_path}.source_path',
                expected='source_path present in evidence_catalog', actual=source_path,
                source_path=source_path,
            )
        if factor != source.get('factor'):
            raise UnifiedAnalysisValidationError(
                f'{item_path} factor does not match source path',
                reason_code='llm_evidence_validation_failed', stage='evidence',
                error_code='evidence_factor_mismatch', path=f'{item_path}.factor',
                expected=source.get('factor'), actual=factor, source_path=source_path,
            )
        evidence_value = item.get('value')
        if not _same_value(evidence_value, source.get('value')):
            raise UnifiedAnalysisValidationError(
                f'{item_path} value does not match its context field',
                reason_code='llm_evidence_validation_failed', stage='evidence',
                error_code='unverified_numeric_value' if isinstance(evidence_value, (int, float)) else 'evidence_value_mismatch',
                path=f'{item_path}.value', expected=repr(source.get('value')),
                actual=evidence_value, source_path=source_path,
            )
        normalized.append({
            'factor': factor, 'source_path': source_path, 'value': source.get('value'),
            'interpretation': _string(item.get('interpretation'), f'{item_path}.interpretation'),
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
    return set(candidate_ids) if constraints.get('allow_new_long') is True else {
        STRATEGY_RISK_OFF, STRATEGY_NO_STRATEGY,
    } & set(candidate_ids)


def _normalize_comparison(value, context, candidate_ids):
    if not isinstance(value, dict) or set(value) != set(candidate_ids):
        actual = set(value) if isinstance(value, dict) else set()
        raise UnifiedAnalysisValidationError(
            'llm_strategy_comparison must contain every candidate exactly once',
            error_code='field_set_mismatch', path='llm_strategy_comparison',
            expected='|'.join(candidate_ids), missing_fields=set(candidate_ids) - actual,
            extra_fields=actual - set(candidate_ids),
        )
    normalized = {}
    for strategy_id in candidate_ids:
        path = f'llm_strategy_comparison.{strategy_id}'
        item = value.get(strategy_id)
        if not isinstance(item, dict):
            raise UnifiedAnalysisValidationError(
                f'{path} must be object', error_code='invalid_type', path=path,
                expected='object', actual=item,
            )
        _require_exact_fields(item, {'suitability', 'supporting_factors', 'conflicting_factors'}, path)
        suitability = _enum(item.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY, f'{path}.suitability')
        normalized[strategy_id] = {
            'suitability': suitability,
            'supporting_factors': _normalize_evidence(item.get('supporting_factors'), context, path=f'{path}.supporting_factors', allow_empty=True),
            'conflicting_factors': _normalize_evidence(item.get('conflicting_factors'), context, path=f'{path}.conflicting_factors', allow_empty=True),
        }
        if any(
            evidence['factor'].startswith('Hybrid Backtest')
            for evidence in normalized[strategy_id]['supporting_factors'] + normalized[strategy_id]['conflicting_factors']
        ):
            raise UnifiedAnalysisValidationError(
                'related hybrid backtest is not comparable candidate evidence',
                reason_code='llm_evidence_validation_failed', stage='evidence',
                error_code='non_comparable_backtest_evidence', path=path,
            )
    return normalized


def normalize_unified_analysis(data, context, *, already_standardized=False):
    """Validate the LLM-only judgment. Backend comparison is intentionally absent."""

    if not isinstance(data, dict):
        raise UnifiedAnalysisValidationError(
            'analysis must be object', error_code='invalid_type', path='analysis',
            expected='object', actual=data,
        )
    if not already_standardized:
        data, _ = standardize_unified_analysis_input(data)
    _require_exact_fields(data, LLM_TOP_LEVEL_FIELDS, 'analysis')
    market = _section(data, 'llm_market_assessment')
    strategy = _section(data, 'llm_final_strategy_assessment')
    risk = _section(data, 'llm_risk_assessment')
    _require_exact_fields(market, {'regime', 'direction', 'confidence', 'summary'}, 'llm_market_assessment')
    _require_exact_fields(strategy, {'selected_strategy', 'confidence', 'suitability', 'reason', 'why_not_alternatives'}, 'llm_final_strategy_assessment')
    _require_exact_fields(risk, {'risk_level', 'summary'}, 'llm_risk_assessment')
    candidate_ids = _candidate_ids(context)
    comparison = _normalize_comparison(data.get('llm_strategy_comparison'), context, candidate_ids)
    selected = _enum(strategy.get('selected_strategy'), set(candidate_ids), 'llm_final_strategy_assessment.selected_strategy')
    suitability = _enum(strategy.get('suitability'), ALLOWED_CANDIDATE_SUITABILITY, 'llm_final_strategy_assessment.suitability')
    if comparison[selected]['suitability'] != suitability:
        raise UnifiedAnalysisValidationError(
            'selected suitability contradicts comparison', error_code='cross_field_mismatch',
            path='llm_final_strategy_assessment.suitability',
            expected=comparison[selected]['suitability'], actual=suitability,
        )
    if selected in ACTIVE_STRATEGIES and suitability in {'low', 'insufficient_evidence'}:
        raise UnifiedAnalysisValidationError(
            'low-evidence active strategy cannot be selected', stage='business_rule',
            error_code='invalid_selected_suitability',
            path='llm_final_strategy_assessment.suitability', expected='high|medium|not_allowed',
            actual=suitability,
        )
    entry = (context.get('technical_analysis') or {}).get('mean_reversion_entry') or {}
    if selected == STRATEGY_MEAN_REVERSION and entry.get('entry_conditions_met') is False:
        raise UnifiedAnalysisValidationError(
            'mean reversion cannot be selected without its actual entry conditions',
            reason_code='llm_strategy_validation_failed', stage='business_rule',
            error_code='mean_reversion_entry_not_met',
            path='llm_final_strategy_assessment.selected_strategy',
            expected='no_strategy or another supported candidate', actual=selected,
        )
    why_not = _string_list(strategy.get('why_not_alternatives'), 'llm_final_strategy_assessment.why_not_alternatives')
    if len(why_not) < len(candidate_ids) - 1:
        raise UnifiedAnalysisValidationError(
            'why_not_alternatives must address every alternative',
            error_code='insufficient_items', path='llm_final_strategy_assessment.why_not_alternatives',
            expected=f'at least {len(candidate_ids) - 1} strings', actual=len(why_not),
        )
    expected_backtest = (context.get('strategy_evidence') or {}).get('backtest_evidence_available') is True
    actual_backtest = _boolean(data.get('backtest_evidence_available'), 'backtest_evidence_available')
    if actual_backtest != expected_backtest:
        raise UnifiedAnalysisValidationError(
            'backtest evidence availability contradicts context',
            reason_code='llm_evidence_validation_failed', stage='evidence',
            error_code='evidence_availability_mismatch', path='backtest_evidence_available',
            expected=expected_backtest, actual=actual_backtest,
        )
    return {
        'llm_market_assessment': {
            'regime': _enum(market.get('regime'), ALLOWED_REGIMES, 'llm_market_assessment.regime'),
            'direction': _enum(market.get('direction'), ALLOWED_DIRECTIONS, 'llm_market_assessment.direction'),
            'confidence': _confidence(market.get('confidence'), 'llm_market_assessment.confidence'),
            'summary': _string(market.get('summary'), 'llm_market_assessment.summary'),
        },
        'llm_strategy_comparison': comparison,
        'llm_final_strategy_assessment': {
            'selected_strategy': selected,
            'confidence': _confidence(strategy.get('confidence'), 'llm_final_strategy_assessment.confidence'),
            'suitability': suitability,
            'reason': _string(strategy.get('reason'), 'llm_final_strategy_assessment.reason'),
            'why_not_alternatives': why_not,
        },
        'llm_risk_assessment': {
            'risk_level': _enum(risk.get('risk_level'), ALLOWED_RISK_LEVELS, 'llm_risk_assessment.risk_level'),
            'summary': _string(risk.get('summary'), 'llm_risk_assessment.summary'),
        },
        'backtest_evidence_available': actual_backtest,
        'supporting_evidence': _normalize_evidence(data.get('supporting_evidence'), context, path='supporting_evidence', allow_empty=False),
        'limitations': _string_list(data.get('limitations'), 'limitations'),
    }


def _backend_assessment(context):
    source = context.get('quantitative_assessment') or {}
    return {
        'available': source.get('available') is True,
        'preliminary_regime': source.get('preliminary_regime'),
        'suggested_strategy': source.get('suggested_strategy'),
        'confidence': source.get('confidence'),
        'confidence_label': source.get('confidence_label'),
        'risk_off': source.get('risk_off') is True,
        'allow_new_long': source.get('allow_new_long') is True,
        'explanation': [item for item in (source.get('explanation') or []) if isinstance(item, str) and item.strip()],
    }


def _agreement(backend, llm):
    llm_market = llm['llm_market_assessment']
    llm_strategy = llm['llm_final_strategy_assessment']
    regime_agreement = backend.get('preliminary_regime') == llm_market.get('regime')
    strategy_agreement = backend.get('suggested_strategy') == llm_strategy.get('selected_strategy')
    differences = []
    if not regime_agreement:
        differences.append({
            'field': 'regime', 'backend_value': backend.get('preliminary_regime'),
            'llm_value': llm_market.get('regime'),
            'summary': 'The deterministic regime classification and independent AI regime assessment differ.',
        })
    if not strategy_agreement:
        differences.append({
            'field': 'selected_strategy', 'backend_value': backend.get('suggested_strategy'),
            'llm_value': llm_strategy.get('selected_strategy'),
            'summary': 'The deterministic preliminary strategy and independent AI strategy selection differ.',
        })
    return {
        'agrees_with_backend': regime_agreement and strategy_agreement,
        'regime_agreement': regime_agreement,
        'strategy_agreement': strategy_agreement,
        'backend_preliminary_regime': backend.get('preliminary_regime'),
        'llm_regime': llm_market.get('regime'),
        'backend_suggested_strategy': backend.get('suggested_strategy'),
        'llm_selected_strategy': llm_strategy.get('selected_strategy'),
        'differences': differences,
    }


def _validated_decision(context, backend, llm_selected):
    constraints = context.get('hard_constraints') or {}
    allowed = _currently_allowed_ids(context, list(AGENT_STRATEGY_IDS))
    final = llm_selected
    reason = None
    if constraints.get('risk_off') is True and llm_selected != STRATEGY_RISK_OFF:
        final = STRATEGY_RISK_OFF
        reason = 'The deterministic risk engine requires the defensive Risk-Off state.'
    elif constraints.get('allow_new_long') is not True and llm_selected in ACTIVE_STRATEGIES:
        final = STRATEGY_RISK_OFF
        reason = 'New long exposure is prohibited by the deterministic risk engine.'
    elif llm_selected not in allowed:
        final = STRATEGY_RISK_OFF if STRATEGY_RISK_OFF in allowed else STRATEGY_NO_STRATEGY
        reason = 'The independent AI selection is not permitted by current deterministic constraints.'
    override = final != llm_selected
    return {
        'backend_preliminary_strategy': backend.get('suggested_strategy'),
        'llm_selected_strategy': llm_selected,
        'validated_final_strategy': final,
        'hard_constraint_override_applied': override,
        'override_reason': reason,
        'decision_source': 'llm_synthesis_with_constraint_override' if override else 'llm_synthesis',
        'fallback_used': False,
        'backend_hard_constraints': {
            'risk_off': constraints.get('risk_off') is True,
            'allow_new_long': constraints.get('allow_new_long') is True,
            'allowed_strategy_ids': sorted(allowed),
        },
    }


def build_validated_system_analysis(context, llm_assessment, *, backend_suggestion_exposed=False):
    backend = _backend_assessment(context)
    selected = llm_assessment['llm_final_strategy_assessment']['selected_strategy']
    decision = _validated_decision(context, backend, selected)
    analysis = {
        'analysis_version': AGENT_ANALYSIS_VERSION,
        'analysis_status': 'success',
        'decision_source': decision['decision_source'],
        'fallback_reason': None,
        'llm_assessment_mode': 'independent',
        'backend_suggestion_exposed_to_llm': backend_suggestion_exposed,
        'backend_quantitative_assessment': backend,
        'llm_independent_assessment': llm_assessment,
        'quantitative_agreement': _agreement(backend, llm_assessment),
        'validated_system_decision': decision,
        'available_strategies': deepcopy(context.get('available_strategies') or []),
    }
    analysis.update({
        # Read-only v3 compatibility projection for stored responses and older clients.
        'final_market_assessment': deepcopy(llm_assessment['llm_market_assessment']),
        'strategy_comparison': deepcopy(llm_assessment['llm_strategy_comparison']),
        'final_strategy_assessment': deepcopy(llm_assessment['llm_final_strategy_assessment']),
        'quantitative_assessment': deepcopy(backend),
        'risk_assessment': {
            **deepcopy(llm_assessment['llm_risk_assessment']),
            'risk_off': (context.get('hard_constraints') or {}).get('risk_off') is True,
            'allow_new_long': (context.get('hard_constraints') or {}).get('allow_new_long') is True,
        },
        'backtest_evidence_available': llm_assessment['backtest_evidence_available'],
        'supporting_evidence': deepcopy(llm_assessment['supporting_evidence']),
        'limitations': deepcopy(llm_assessment['limitations']),
    })
    return analysis


def _fallback_strategy(context, backend):
    constraints = context.get('hard_constraints') or {}
    allowed = _currently_allowed_ids(context, list(AGENT_STRATEGY_IDS))
    if constraints.get('risk_off') is True and STRATEGY_RISK_OFF in allowed:
        return STRATEGY_RISK_OFF
    suggested = backend.get('suggested_strategy')
    if suggested in allowed:
        return suggested
    if constraints.get('allow_new_long') is not True and STRATEGY_RISK_OFF in allowed:
        return STRATEGY_RISK_OFF
    return STRATEGY_NO_STRATEGY


def build_quantitative_fallback(context, fallback_reason):
    backend = _backend_assessment(context)
    final = _fallback_strategy(context, backend)
    constraints = context.get('hard_constraints') or {}
    analysis = {
        'analysis_version': AGENT_ANALYSIS_VERSION,
        'analysis_status': 'fallback',
        'decision_source': 'quantitative_fallback',
        'fallback_reason': fallback_reason,
        'llm_assessment_mode': 'unavailable',
        'backend_suggestion_exposed_to_llm': False,
        'backend_quantitative_assessment': backend,
        'llm_independent_assessment': None,
        'quantitative_agreement': {
            'agrees_with_backend': None, 'regime_agreement': None,
            'strategy_agreement': None,
            'backend_preliminary_regime': backend.get('preliminary_regime'),
            'llm_regime': None,
            'backend_suggested_strategy': backend.get('suggested_strategy'),
            'llm_selected_strategy': None,
            'differences': [],
        },
        'validated_system_decision': {
            'backend_preliminary_strategy': backend.get('suggested_strategy'),
            'llm_selected_strategy': None,
            'validated_final_strategy': final,
            'hard_constraint_override_applied': final != backend.get('suggested_strategy'),
            'override_reason': (
                'The deterministic risk engine overrode the preliminary active strategy.'
                if final != backend.get('suggested_strategy') else None
            ),
            'decision_source': 'quantitative_fallback',
            'fallback_used': True,
            'backend_hard_constraints': {
                'risk_off': constraints.get('risk_off') is True,
                'allow_new_long': constraints.get('allow_new_long') is True,
                'allowed_strategy_ids': sorted(_currently_allowed_ids(context, list(AGENT_STRATEGY_IDS))),
            },
        },
        'available_strategies': deepcopy(context.get('available_strategies') or []),
    }
    candidate_ids = [item.get('id') for item in analysis['available_strategies'] if item.get('id')] or list(AGENT_STRATEGY_IDS)
    comparison = {
        strategy_id: {
            'suitability': 'high' if strategy_id == final else 'insufficient_evidence',
            'supporting_factors': [], 'conflicting_factors': [],
        }
        for strategy_id in candidate_ids
    }
    analysis.update({
        # Read-only v3 compatibility projection for stored responses and older clients.
        'final_market_assessment': {
            'regime': backend.get('preliminary_regime'),
            'direction': str((context.get('market_regime') or {}).get('direction') or 'neutral').lower(),
            'confidence': backend.get('confidence') or 0.0,
            'summary': (backend.get('explanation') or ['Deterministic fallback assessment.'])[0],
        },
        'strategy_comparison': comparison,
        'final_strategy_assessment': {
            'selected_strategy': final, 'confidence': backend.get('confidence') or 0.0,
            'suitability': comparison[final]['suitability'],
            'reason': (backend.get('explanation') or ['Deterministic fallback strategy.'])[-1],
            'why_not_alternatives': [
                f'{strategy_id} was not selected by the deterministic fallback.'
                for strategy_id in candidate_ids if strategy_id != final
            ],
        },
        'quantitative_assessment': deepcopy(backend),
        'risk_assessment': {
            'risk_level': 'high' if constraints.get('risk_off') is True else 'medium',
            'risk_off': constraints.get('risk_off') is True,
            'allow_new_long': constraints.get('allow_new_long') is True,
            'summary': 'Django hard constraints remain authoritative in fallback mode.',
        },
        'backtest_evidence_available': False,
        'supporting_evidence': [],
        'limitations': ['Independent AI assessment was unavailable; deterministic fallback was used.'],
    })
    return analysis


__all__ = [
    'AGENT_ANALYSIS_PROMPT_VERSION', 'AGENT_ANALYSIS_VERSION',
    'UnifiedAnalysisValidationError', 'build_quantitative_fallback',
    'build_validated_system_analysis', 'has_forbidden_action_language',
    'has_open_close_direction_contradiction', 'normalize_unified_analysis',
    'standardize_unified_analysis_input',
]
