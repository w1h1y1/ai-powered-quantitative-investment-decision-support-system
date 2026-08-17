"""LLM Context payload pruning and prompt construction.

The full ``agent_context_v1`` object is never sent to the LLM.  Only the
summary facts the model may explain are extracted here, and the prompt
enforces the hard constraints of the decision-support system.
"""

import json

from .analysis_schema import (
    ALL_ANALYSIS_FIELDS,
    ANALYSIS_VERSION,
    SUMMARY_FIELDS,
)


SYSTEM_PROMPT = f"""You are the explanation layer of an AI Quantitative Investment Decision Support System.
You receive one deterministic Agent Context JSON object and must explain the evidence it already contains.

Hard rules:
1. Explain only evidence present in the Context. Never recalculate Market Regime, never re-derive the selected strategy, and never run or invent a backtest.
2. Never change or question the formal selected_strategy, allow_new_long or risk_off values. They are hard constraint facts.
3. Never output BUY, SELL, STRONG BUY, STRONG SELL, position sizing, or any other trade instruction.
4. Never invent numbers. Only reference values that exist in the Context, and apply the Context units exactly. For example a decimal_fraction of 0.08 means 8 percent, while a percentage_points value of 0.56 means 0.56 percent.
5. Never create confidence values. You may only quote the regime_confidence and selection_confidence already present in the Context.
6. If any module is truly unavailable (for example missing sector context, an unavailable evaluation, stale data or provider issues), state it explicitly and never guess the missing information.
7. A strategy_evaluation status of not_applicable (for example Risk-Off) is a normal business status, not an unavailable module, not degraded, and not a failure. Never describe a not_applicable module as unavailable, degraded, missing, or failed, and never write that a module is unavailable when data_quality.all_modules_available is true.
8. Return ONLY a single JSON object. Do NOT wrap it in Markdown code fences, do NOT add prose before or after the JSON, and do NOT add any other fields, including action bias, confidence scores, or trade signals.
9. The JSON object must contain exactly these fields: {", ".join(ALL_ANALYSIS_FIELDS)}.
10. Type requirements: every summary field ({", ".join(SUMMARY_FIELDS)}) MUST be a JSON string. key_reasons, risk_factors and limitations MUST each be a JSON array of strings; use [] when there is nothing to report, never a plain string.
"""

def build_llm_payload(agent_context):
    """Extract the minimal, unit-annotated summary facts for the LLM."""

    context = agent_context or {}
    security = context.get('security') or {}
    market_regime = context.get('market_regime') or {}
    technical = context.get('technical') or {}
    market_context = context.get('market_context') or {}
    selection = context.get('strategy_selection') or {}
    evaluation = context.get('strategy_evaluation') or {}
    data_quality = context.get('data_quality') or {}
    modules = data_quality.get('modules') or {}
    evaluation_data_source = evaluation.get('data_source')

    return {
        'symbol': context.get('symbol'),
        'as_of_date': context.get('as_of_date'),
        'security': {
            'symbol': security.get('symbol'),
            'name': security.get('name'),
            'exchange': security.get('exchange'),
            'currency': security.get('currency'),
        },
        'market_regime': {
            'available': market_regime.get('available'),
            'unavailable_reason': market_regime.get('unavailable_reason'),
            'regime': market_regime.get('regime'),
            'confidence': market_regime.get('confidence'),
            'confidence_score': market_regime.get('confidence_score'),
            'explanation': market_regime.get('explanation') or [],
        },
        'technical': {
            'latest': technical.get('latest') or {},
            'relative_strength': technical.get('relative_strength') or {},
            'units': technical.get('units') or {},
        },
        'market_context': {
            'broad_market': market_context.get('broad_market'),
            'broad_market_available': market_context.get('broad_market_available'),
            'broad_market_reason': market_context.get('broad_market_reason'),
            'spy_regime': market_context.get('spy_regime'),
            'sector': market_context.get('sector'),
            'sector_benchmark': market_context.get('sector_benchmark'),
            'sector_available': market_context.get('sector_available'),
            'sector_reason': market_context.get('sector_reason'),
            'sector_regime': market_context.get('sector_regime'),
            'confirmation_score': market_context.get('confirmation_score'),
        },
        'strategy_selection': {
            'available': selection.get('available'),
            'selected_strategy': selection.get('selected_strategy'),
            'strategy_mode': selection.get('strategy_mode'),
            'execution_mode': selection.get('execution_mode'),
            'allow_new_long': selection.get('allow_new_long'),
            'risk_off': selection.get('risk_off'),
            'selection_confidence': selection.get('selection_confidence'),
            'reason': selection.get('reason') or [],
        },
        'strategy_evaluation': {
            'available': evaluation.get('available'),
            'status': evaluation.get('status'),
            'unavailable_reason': evaluation.get('unavailable_reason'),
            'evaluation_strategy': evaluation.get('evaluation_strategy'),
            'metrics': evaluation.get('metrics') or {},
            'evaluation_window': evaluation.get('evaluation_window'),
            'data_source': (
                evaluation_data_source.get('source')
                if isinstance(evaluation_data_source, dict)
                else None
            ),
            'units': evaluation.get('units') or {},
        },
        'data_quality': {
            'all_modules_available': data_quality.get('all_modules_available'),
            'degraded_modules': data_quality.get('degraded_modules') or [],
            'as_of_date': data_quality.get('as_of_date'),
            'modules': {
                module_name: {
                    'available': module.get('available'),
                    'status': module.get('status'),
                    'reason': module.get('reason'),
                    'latest_market_date': module.get('latest_market_date'),
                    'data_source': module.get('data_source'),
                }
                for module_name, module in modules.items()
            },
        },
    }


def build_prompt(llm_payload):
    """Return the provider-agnostic system/user prompt pair."""

    user_prompt = (
        'Analyze the following deterministic Agent Context and produce the '
        f'required JSON (schema version {ANALYSIS_VERSION}):\n\n'
        f'{json.dumps(llm_payload, indent=2, default=str)}'
    )
    return {
        'system': SYSTEM_PROMPT,
        'user': user_prompt,
    }


def build_repair_prompt(llm_payload, validation_details):
    """Build a one-shot repair prompt listing the exact schema problems.

    Only field names and expected/actual types are included; the raw provider
    output is never embedded here and never logged.
    """

    lines = []
    missing = validation_details.get('missing_fields') or []
    wrong_type = validation_details.get('wrong_type_fields') or []
    if missing:
        lines.append(f"- missing fields: {', '.join(missing)}")
    for problem in wrong_type:
        lines.append(
            f"- field '{problem['field']}' has type {problem['actual_type']}, "
            f"expected {problem['expected_type']}"
        )
    if not lines:
        lines.append('- the previous JSON did not match the required schema')

    correction = (
        'Correction required. The previous JSON was rejected because:\n'
        + '\n'.join(lines)
        + '\nReturn the complete corrected JSON object now, following every '
        'original instruction exactly. Do not repeat the mistake.'
    )
    original = build_prompt(llm_payload)
    return {
        'system': original['system'],
        'user': f'{original["user"]}\n\n{correction}',
    }
