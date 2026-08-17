"""Investment Agent orchestration: Context -> LLM -> structured analysis.

The deterministic Agent Context is always available.  The LLM is only the
outermost explanation layer; when it fails, the response degrades to a
deterministic summary with ``analysis_available=false`` instead of breaking
Market Regime, Strategy Selection or Strategy Evaluation.
"""

import logging
import time

from .agent_context_service import AGENT_CONTEXT_VERSION, build_agent_context
from .analysis_schema import ANALYSIS_VERSION, AnalysisValidationError, normalize_analysis
from .llm.base import UnsupportedProviderError
from .llm.provider_factory import get_llm_provider
from .prompt_builder import build_llm_payload, build_prompt, build_repair_prompt

logger = logging.getLogger('agent')

MAX_SCHEMA_REPAIR_ATTEMPTS = 1


def _log_validation_failure(*, provider_name, model, symbol, exc):
    details = getattr(exc, 'details', {}) or {}
    logger.warning(
        'Investment Agent schema validation failed provider=%s model=%s symbol=%s '
        'validation_error_type=%s missing_fields=%s wrong_type_fields=%s extra_fields=%s',
        provider_name,
        model,
        symbol,
        details.get('validation_error_type'),
        details.get('missing_fields'),
        details.get('wrong_type_fields'),
        details.get('extra_fields'),
    )


def _response(
    *,
    context,
    llm_payload,
    provider_name,
    model,
    llm_available,
    analysis_available,
    failure_reason,
    analysis,
):
    return {
        'symbol': context.get('symbol'),
        'as_of_date': context.get('as_of_date'),
        'context_version': context.get('context_version') or AGENT_CONTEXT_VERSION,
        'context_summary': llm_payload,
        'provider': provider_name,
        'model': model,
        'llm_available': llm_available,
        'analysis_available': analysis_available,
        'failure_reason': failure_reason,
        'analysis': analysis,
    }


def _failure(
    *,
    context,
    llm_payload,
    provider_name,
    model,
    failure_reason,
    started,
    symbol,
):
    logger.warning(
        'Investment Agent analysis unavailable provider=%s model=%s symbol=%s '
        'latency_ms=%d failure_reason=%s',
        provider_name,
        model,
        symbol,
        int((time.monotonic() - started) * 1000),
        failure_reason,
    )
    return _response(
        context=context,
        llm_payload=llm_payload,
        provider_name=provider_name,
        model=model,
        llm_available=False,
        analysis_available=False,
        failure_reason=failure_reason,
        analysis=None,
    )


def run_investment_agent(security, *, benchmark=None, provider=None):
    """Build the Agent Context and attach a structured LLM explanation.

    ``provider`` may be injected for tests or future providers; otherwise the
    configured provider is created through the factory.  Errors from the
    deterministic context layer propagate to the caller, while every LLM-layer
    failure is converted into a fallback response.
    """

    started = time.monotonic()
    context = build_agent_context(security, benchmark=benchmark)
    llm_payload = build_llm_payload(context)
    symbol = context.get('symbol')

    llm_provider = provider
    provider_name = None
    model = None
    try:
        if llm_provider is None:
            llm_provider = get_llm_provider()
        provider_name = llm_provider.provider_name
        model = llm_provider.model
        if not llm_provider.is_configured():
            return _failure(
                context=context,
                llm_payload=llm_payload,
                provider_name=provider_name,
                model=model,
                failure_reason='api_key_missing',
                started=started,
                symbol=symbol,
            )

        prompt = build_prompt(llm_payload)
        result = llm_provider.generate_structured_analysis(prompt)
        if result.failure_reason is not None:
            return _failure(
                context=context,
                llm_payload=llm_payload,
                provider_name=provider_name,
                model=model,
                failure_reason=result.failure_reason,
                started=started,
                symbol=symbol,
            )
        if not isinstance(result.analysis, dict):
            return _failure(
                context=context,
                llm_payload=llm_payload,
                provider_name=provider_name,
                model=model,
                failure_reason='invalid_response',
                started=started,
                symbol=symbol,
            )
        try:
            analysis = normalize_analysis(result.analysis)
        except AnalysisValidationError as first_error:
            _log_validation_failure(
                provider_name=provider_name,
                model=model,
                symbol=symbol,
                exc=first_error,
            )
            repair_prompt = build_repair_prompt(
                llm_payload,
                getattr(first_error, 'details', {}) or {},
            )
            repaired = llm_provider.generate_structured_analysis(repair_prompt)
            if repaired.failure_reason is not None:
                return _failure(
                    context=context,
                    llm_payload=llm_payload,
                    provider_name=provider_name,
                    model=model,
                    failure_reason=repaired.failure_reason,
                    started=started,
                    symbol=symbol,
                )
            if not isinstance(repaired.analysis, dict):
                return _failure(
                    context=context,
                    llm_payload=llm_payload,
                    provider_name=provider_name,
                    model=model,
                    failure_reason='invalid_response',
                    started=started,
                    symbol=symbol,
                )
            try:
                analysis = normalize_analysis(repaired.analysis)
            except AnalysisValidationError as second_error:
                _log_validation_failure(
                    provider_name=provider_name,
                    model=model,
                    symbol=symbol,
                    exc=second_error,
                )
                return _failure(
                    context=context,
                    llm_payload=llm_payload,
                    provider_name=provider_name,
                    model=model,
                    failure_reason='schema_invalid',
                    started=started,
                    symbol=symbol,
                )
    except UnsupportedProviderError:
        return _failure(
            context=context,
            llm_payload=llm_payload,
            provider_name=provider_name,
            model=model,
            failure_reason='unsupported_provider',
            started=started,
            symbol=symbol,
        )
    except AnalysisValidationError:
        return _failure(
            context=context,
            llm_payload=llm_payload,
            provider_name=provider_name,
            model=model,
            failure_reason='schema_invalid',
            started=started,
            symbol=symbol,
        )

    logger.info(
        'Investment Agent analysis succeeded provider=%s model=%s symbol=%s '
        'latency_ms=%d version=%s',
        provider_name,
        model,
        symbol,
        int((time.monotonic() - started) * 1000),
        ANALYSIS_VERSION,
    )
    return _response(
        context=context,
        llm_payload=llm_payload,
        provider_name=provider_name,
        model=model,
        llm_available=True,
        analysis_available=True,
        failure_reason=None,
        analysis=analysis,
    )
