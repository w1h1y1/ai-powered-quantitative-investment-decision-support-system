"""Run isolated LLM judgment, validate it, then merge with Django judgment."""

import logging

from .llm.base import UnsupportedProviderError
from .llm.provider_factory import get_llm_provider
from .unified_analysis_prompt import (
    build_schema_repair_prompt,
    build_strict_json_retry_prompt,
    build_unified_analysis_prompt,
)
from .unified_analysis_schema import (
    AGENT_ANALYSIS_PROMPT_VERSION,
    AGENT_ANALYSIS_VERSION,
    UnifiedAnalysisValidationError,
    build_quantitative_fallback,
    build_validated_system_analysis,
    has_open_close_direction_contradiction,
    has_forbidden_action_language,
    normalize_unified_analysis,
    standardize_unified_analysis_input,
)
from .unified_context_service import (
    AGENT_UNIFIED_CONTEXT_VERSION,
    LLM_STRATEGY_CONTEXT_VERSION,
    backend_suggestion_exposed_to_llm,
    build_llm_strategy_context,
    build_unified_agent_context,
)


logger = logging.getLogger('agent')


FAILURE_REASONS = {
    'timeout': 'LLM request timed out.',
    'auth_error': 'LLM service authentication failed.',
    'rate_limited': 'LLM service rate limit reached.',
    'http_5xx': 'LLM service is temporarily unavailable.',
    'network_error': 'LLM service is unreachable.',
    'invalid_json': 'LLM returned an invalid structured response.',
    'invalid_response': 'LLM returned an invalid structured response.',
    'api_key_missing': 'LLM service is not configured.',
}


def _metadata(
    context,
    provider,
    model,
    *,
    schema_repair_attempted=False,
    schema_repair_succeeded=False,
    formatting_normalizations=None,
    hard_constraint_violation_detected=False,
    hard_constraint_override_applied=False,
    llm_context=None,
    llm_assessment_mode='independent',
):
    return {
        'provider': provider,
        'model': model,
        'as_of_date': context.get('as_of_date'),
        'prompt_version': AGENT_ANALYSIS_PROMPT_VERSION,
        'analysis_version': AGENT_ANALYSIS_VERSION,
        'llm_context_version': (
            (llm_context or {}).get('llm_context_version')
            or LLM_STRATEGY_CONTEXT_VERSION
        ),
        'llm_assessment_mode': llm_assessment_mode,
        'backend_suggestion_exposed_to_llm': backend_suggestion_exposed_to_llm(
            llm_context or {},
        ),
        'schema_repair_attempted': schema_repair_attempted,
        'schema_repair_succeeded': schema_repair_succeeded,
        'formatting_normalizations': sorted(set(formatting_normalizations or [])),
        'hard_constraint_violation_detected': hard_constraint_violation_detected,
        'hard_constraint_override_applied': hard_constraint_override_applied,
    }


def _fallback(
    context,
    provider,
    model,
    reason_code,
    reason,
    *,
    validation_error=None,
    validation_stage=None,
    validation_error_code=None,
    schema_repair_attempted=False,
    formatting_normalizations=None,
    hard_constraint_violation_detected=False,
    llm_context=None,
):
    details = validation_error.safe_details() if validation_error else {}
    stage = details.get('validation_stage') or validation_stage
    error_code = details.get('validation_error_code') or validation_error_code
    error_path = details.get('validation_error_path')
    error_value = details.get('validation_error_value')
    source_path = details.get('validation_source_path')
    hard_constraint_detected = (
        hard_constraint_violation_detected
        or details.get('hard_constraint_triggered') is True
    )
    logger.warning(
        'Agent analysis fallback provider=%s model=%s symbol=%s '
        'prompt_version=%s analysis_version=%s reason_code=%s stage=%s '
        'error_code=%s path=%s source_path=%s expected=%s actual_type=%s actual=%r '
        'missing_fields=%s extra_fields=%s illegal_strategy_id=%s '
        'hard_constraint_triggered=%s schema_repair_attempted=%s reason=%s',
        provider,
        model,
        context.get('symbol'),
        AGENT_ANALYSIS_PROMPT_VERSION,
        AGENT_ANALYSIS_VERSION,
        reason_code,
        stage,
        error_code,
        error_path,
        source_path,
        details.get('expected'),
        details.get('actual_type'),
        details.get('actual'),
        details.get('missing_fields'),
        details.get('extra_fields'),
        details.get('illegal_strategy_id'),
        hard_constraint_detected,
        schema_repair_attempted,
        reason,
    )
    fallback_analysis = build_quantitative_fallback(context, reason_code)
    fallback_override = (
        (fallback_analysis.get('validated_system_decision') or {})
        .get('hard_constraint_override_applied') is True
    )
    return {
        'symbol': context.get('symbol'),
        'context_version': context.get('context_version'),
        'analysis_status': 'fallback',
        'decision_source': 'quantitative_fallback',
        'fallback_reason': reason_code,
        'unavailable_reason': reason,
        'validation_stage': stage,
        'validation_error_code': error_code,
        'validation_error_path': error_path,
        'validation_error_value': error_value,
        'validation_source_path': source_path,
        'llm_assessment_mode': 'unavailable',
        'backend_suggestion_exposed_to_llm': backend_suggestion_exposed_to_llm(
            llm_context or {},
        ),
        'hard_constraint_override_applied': fallback_override,
        'analysis': fallback_analysis,
        'metadata': _metadata(
            context, provider, model,
            schema_repair_attempted=schema_repair_attempted,
            schema_repair_succeeded=False,
            formatting_normalizations=formatting_normalizations,
            hard_constraint_violation_detected=hard_constraint_detected,
            hard_constraint_override_applied=fallback_override,
            llm_context=llm_context,
            llm_assessment_mode='unavailable',
        ),
    }


def _success(
    context,
    provider,
    model,
    analysis,
    *,
    schema_repair_attempted=False,
    formatting_normalizations=None,
    hard_constraint_violation_detected=False,
    llm_context=None,
):
    decision = analysis.get('validated_system_decision') or {}
    override = decision.get('hard_constraint_override_applied') is True
    decision_source = decision.get('decision_source') or 'llm_synthesis'
    return {
        'symbol': context.get('symbol'),
        'context_version': context.get('context_version'),
        'analysis_status': 'success',
        'decision_source': decision_source,
        'fallback_reason': None,
        'validation_stage': None,
        'validation_error_code': None,
        'validation_error_path': None,
        'validation_error_value': None,
        'validation_source_path': None,
        'llm_assessment_mode': 'independent',
        'backend_suggestion_exposed_to_llm': backend_suggestion_exposed_to_llm(
            llm_context or {},
        ),
        'hard_constraint_override_applied': override,
        'analysis': analysis,
        'metadata': _metadata(
            context, provider, model,
            schema_repair_attempted=schema_repair_attempted,
            schema_repair_succeeded=schema_repair_attempted,
            formatting_normalizations=formatting_normalizations,
            hard_constraint_violation_detected=hard_constraint_violation_detected,
            hard_constraint_override_applied=override,
            llm_context=llm_context,
        ),
    }


def _needs_retry(result):
    return result.failure_reason in {'invalid_json', 'invalid_response'}


def _constraint_error(analysis, context):
    if has_forbidden_action_language(analysis):
        return UnifiedAnalysisValidationError(
            'analysis contains prohibited action language',
            reason_code='llm_constraint_violation',
            stage='business_rule', error_code='forbidden_action_language',
            path='analysis', expected='informational decision support only',
        )
    if has_open_close_direction_contradiction(analysis, context):
        return UnifiedAnalysisValidationError(
            'analysis contradicts the supplied open-to-close direction',
            reason_code='llm_constraint_violation',
            stage='business_rule', error_code='market_fact_contradiction',
            path='narrative', expected='match market_data.open_to_close_direction',
        )
    return None


def _normalize_result(result, context):
    if result.failure_reason is not None:
        return None, None, []
    if not isinstance(result.analysis, dict):
        return None, UnifiedAnalysisValidationError(
            'analysis must be an object', error_code='invalid_type',
            path='analysis', expected='object', actual=result.analysis,
        ), []
    standardized, changes = standardize_unified_analysis_input(result.analysis)
    try:
        analysis = normalize_unified_analysis(
            standardized, context, already_standardized=True,
        )
        constraint_error = _constraint_error(analysis, context)
        if constraint_error is not None:
            return None, constraint_error, changes
        return analysis, None, changes
    except UnifiedAnalysisValidationError as exc:
        return None, exc, changes


def _log_validation_error(error, *, symbol, provider, model, attempt):
    details = error.safe_details()
    logger.warning(
        'LLM validation failed provider=%s model=%s symbol=%s attempt=%s '
        'prompt_version=%s analysis_version=%s stage=%s error_code=%s '
        'path=%s source_path=%s expected=%s actual_type=%s actual=%r missing_fields=%s '
        'extra_fields=%s illegal_strategy_id=%s hard_constraint_triggered=%s',
        provider, model, symbol, attempt,
        AGENT_ANALYSIS_PROMPT_VERSION, AGENT_ANALYSIS_VERSION,
        details.get('validation_stage'), details.get('validation_error_code'),
        details.get('validation_error_path'), details.get('validation_source_path'),
        details.get('expected'),
        details.get('actual_type'), details.get('actual'),
        details.get('missing_fields'), details.get('extra_fields'),
        details.get('illegal_strategy_id'), details.get('hard_constraint_triggered'),
    )


def run_agent_analysis(security, user, *, provider=None):
    """Build context, call DeepSeek, validate, and return structured analysis."""

    context = build_unified_agent_context(security, user)
    llm_context = build_llm_strategy_context(context)
    if context.get('context_version') != AGENT_UNIFIED_CONTEXT_VERSION:
        return _fallback(
            context,
            'unknown',
            None,
            'unsupported_context_version',
            'Unsupported agent context version.',
            validation_stage='schema',
            validation_error_code='unsupported_context_version',
            llm_context=llm_context,
        )

    llm_provider = provider
    provider_name = None
    model = None
    try:
        if llm_provider is None:
            llm_provider = get_llm_provider()
        provider_name = llm_provider.provider_name
        model = llm_provider.model
    except UnsupportedProviderError:
        return _fallback(
            context,
            'unknown',
            None,
            'llm_unsupported_provider',
            'LLM service is not configured.',
            validation_stage='api',
            validation_error_code='unsupported_provider',
            llm_context=llm_context,
        )

    if not llm_provider.is_configured():
        return _fallback(
            context,
            provider_name,
            model,
            'llm_api_key_missing',
            'LLM service is not configured.',
            validation_stage='api',
            validation_error_code='api_key_missing',
            llm_context=llm_context,
        )

    first = llm_provider.generate_structured_analysis(
        build_unified_analysis_prompt(llm_context),
    )
    result = first
    schema_repair_attempted = False
    formatting_normalizations = []
    hard_constraint_violation_detected = False
    analysis, validation_error, changes = _normalize_result(result, llm_context)
    formatting_normalizations.extend(changes)

    if validation_error is not None:
        hard_constraint_violation_detected = validation_error.hard_constraint_triggered
        _log_validation_error(
            validation_error, symbol=context.get('symbol'),
            provider=provider_name, model=model, attempt='initial',
        )

    should_repair = _needs_retry(result) or validation_error is not None
    if should_repair:
        if validation_error is not None:
            repair_prompt = build_schema_repair_prompt(
                llm_context, validation_error.safe_details(),
            )
        else:
            repair_prompt = build_strict_json_retry_prompt(
                llm_context,
                {
                    'validation_stage': 'json_parse',
                    'validation_error_code': result.failure_reason,
                    'expected': 'one complete JSON object',
                },
            )
        result = llm_provider.generate_structured_analysis(repair_prompt)
        schema_repair_attempted = True
        analysis, validation_error, changes = _normalize_result(result, llm_context)
        formatting_normalizations.extend(changes)
        if validation_error is not None:
            hard_constraint_violation_detected = (
                hard_constraint_violation_detected
                or validation_error.hard_constraint_triggered
            )
            _log_validation_error(
                validation_error, symbol=context.get('symbol'),
                provider=provider_name, model=model, attempt='repair',
            )

    if result.failure_reason is not None:
        validation_stage = (
            'json_parse'
            if result.failure_reason in {'invalid_json', 'invalid_response'}
            else 'api'
        )
        return _fallback(
            context,
            provider_name,
            model,
            f'llm_{result.failure_reason}',
            FAILURE_REASONS.get(result.failure_reason, 'LLM service is unavailable.'),
            validation_stage=validation_stage,
            validation_error_code=result.failure_reason,
            schema_repair_attempted=schema_repair_attempted,
            formatting_normalizations=formatting_normalizations,
            hard_constraint_violation_detected=hard_constraint_violation_detected,
            llm_context=llm_context,
        )
    if analysis is None:
        return _fallback(
            context,
            provider_name,
            model,
            getattr(validation_error, 'reason_code', 'llm_schema_validation_failed'),
            'LLM returned an invalid structured response.',
            validation_error=validation_error,
            schema_repair_attempted=schema_repair_attempted,
            formatting_normalizations=formatting_normalizations,
            hard_constraint_violation_detected=hard_constraint_violation_detected,
            llm_context=llm_context,
        )

    merged_analysis = build_validated_system_analysis(
        context,
        analysis,
        backend_suggestion_exposed=backend_suggestion_exposed_to_llm(llm_context),
    )
    return _success(
        context, provider_name, model, merged_analysis,
        schema_repair_attempted=schema_repair_attempted,
        formatting_normalizations=formatting_normalizations,
        hard_constraint_violation_detected=hard_constraint_violation_detected,
        llm_context=llm_context,
    )
