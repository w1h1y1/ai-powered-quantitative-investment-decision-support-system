"""DeepSeek reads the versioned unified context and returns v3 synthesis."""

import logging

from .llm.base import UnsupportedProviderError
from .llm.provider_factory import get_llm_provider
from .unified_analysis_prompt import (
    build_constraint_retry_prompt,
    build_strict_json_retry_prompt,
    build_unified_analysis_prompt,
)
from .unified_analysis_schema import (
    AGENT_ANALYSIS_PROMPT_VERSION,
    AGENT_ANALYSIS_VERSION,
    UnifiedAnalysisValidationError,
    build_quantitative_fallback,
    has_open_close_direction_contradiction,
    has_forbidden_action_language,
    normalize_unified_analysis,
)
from .unified_context_service import (
    AGENT_UNIFIED_CONTEXT_VERSION,
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


def _metadata(context, provider, model):
    return {
        'provider': provider,
        'model': model,
        'as_of_date': context.get('as_of_date'),
        'prompt_version': AGENT_ANALYSIS_PROMPT_VERSION,
        'analysis_version': AGENT_ANALYSIS_VERSION,
    }


def _fallback(context, provider, model, reason_code, reason):
    logger.warning(
        'Agent analysis fallback provider=%s model=%s symbol=%s reason=%s',
        provider,
        model,
        context.get('symbol'),
        reason,
    )
    return {
        'symbol': context.get('symbol'),
        'context_version': context.get('context_version'),
        'analysis_status': 'fallback',
        'decision_source': 'quantitative_fallback',
        'fallback_reason': reason_code,
        'unavailable_reason': reason,
        'analysis': build_quantitative_fallback(context, reason_code),
        'metadata': _metadata(context, provider, model),
    }


def _success(context, provider, model, analysis):
    return {
        'symbol': context.get('symbol'),
        'context_version': context.get('context_version'),
        'analysis_status': 'success',
        'decision_source': 'llm_synthesis',
        'fallback_reason': None,
        'analysis': analysis,
        'metadata': _metadata(context, provider, model),
    }


def _needs_retry(result):
    return result.failure_reason in {'invalid_json', 'invalid_response'}


def _violates_constraints(analysis, context):
    return (
        has_forbidden_action_language(analysis)
        or has_open_close_direction_contradiction(analysis, context)
    )


def _normalize_result(result, context):
    if result.failure_reason is not None:
        return None, None
    if not isinstance(result.analysis, dict):
        return None, UnifiedAnalysisValidationError('analysis must be an object')
    try:
        return normalize_unified_analysis(result.analysis, context), None
    except UnifiedAnalysisValidationError as exc:
        return None, exc


def run_agent_analysis(security, user, *, provider=None):
    """Build context, call DeepSeek, validate, and return structured analysis."""

    context = build_unified_agent_context(security, user)
    if context.get('context_version') != AGENT_UNIFIED_CONTEXT_VERSION:
        return _fallback(
            context,
            'unknown',
            None,
            'unsupported_context_version',
            'Unsupported agent context version.',
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
        )

    if not llm_provider.is_configured():
        return _fallback(
            context,
            provider_name,
            model,
            'llm_api_key_missing',
            'LLM service is not configured.',
        )

    first = llm_provider.generate_structured_analysis(
        build_unified_analysis_prompt(context),
    )
    result = first
    retried = False
    if _needs_retry(first):
        result = llm_provider.generate_structured_analysis(
            build_strict_json_retry_prompt(context),
        )
        retried = True

    analysis, validation_error = _normalize_result(result, context)
    if analysis is None and result.failure_reason is None and not retried:
        # Parseable JSON but missing/invalid schema: one controlled repair retry.
        repaired = llm_provider.generate_structured_analysis(
            build_strict_json_retry_prompt(context),
        )
        result = repaired
        retried = True
        analysis, validation_error = _normalize_result(result, context)

    if analysis is not None and _violates_constraints(analysis, context):
        result = llm_provider.generate_structured_analysis(
            build_constraint_retry_prompt(context),
        )
        analysis, validation_error = _normalize_result(result, context)

    if result.failure_reason is not None:
        return _fallback(
            context,
            provider_name,
            model,
            f'llm_{result.failure_reason}',
            FAILURE_REASONS.get(result.failure_reason, 'LLM service is unavailable.'),
        )
    if analysis is None:
        return _fallback(
            context,
            provider_name,
            model,
            getattr(validation_error, 'reason_code', 'llm_schema_validation_failed'),
            'LLM returned an invalid structured response.',
        )
    if _violates_constraints(analysis, context):
        return _fallback(
            context,
            provider_name,
            model,
            'llm_constraint_violation',
            'LLM response violated analysis constraints.',
        )

    return _success(context, provider_name, model, analysis)
