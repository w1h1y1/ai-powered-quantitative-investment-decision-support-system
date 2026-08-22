"""Prompt construction for hybrid quantitative + LLM decision synthesis."""

import json

from .unified_analysis_schema import AGENT_ANALYSIS_PROMPT_VERSION


SYSTEM_PROMPT = """You are the final synthesis layer of an investment decision-support system.
The Django Context is authoritative for data, candidate definitions, implementation capabilities,
preliminary quantitative opinions, and hard risk constraints. Produce a concise decision record,
not hidden reasoning or a mechanical regime-to-strategy mapping.

Required analysis order:
1. Read every available_strategies entry, including its real indicators, rules, risks, executable flag, and current permission.
2. Check data_quality and identify material missing evidence.
3. Independently assess price and moving-average structure.
4. Independently assess RSI and MACD momentum.
5. Independently assess ADX and Choppiness trend strength.
6. Independently assess volatility and relative performance.
7. Form final_market_assessment before relying on the preliminary conclusion.
8. Treat preliminary_regime and suggested_strategy only as opinions to test, never as final answers.
9. Evaluate every candidate in available_strategies exactly once, including risk_off and no_strategy.
10. For every candidate, record supporting and conflicting verified factors, then assign one suitability value.
11. Compare candidates relatively: trend evidence can favour Trend Following, range/deviation evidence can favour Mean Reversion, extreme risk can favour Risk-Off, and weak/conflicting/non-actionable evidence can favour No Suitable Strategy. None of these associations is absolute.
12. Select only a currently allowed candidate and state why every alternative was not selected.
13. State whether both final regime and strategy agree with the deterministic preliminary opinions; document concrete differences when either does not.
14. Apply hard risk constraints and explicitly disclose whether comparable candidate backtest evidence exists.

Hard rules:
- Use only the supplied Context. Never invent, recalculate, rename, or alter numerical values.
- Every factor object anywhere in the response must use an exact evidence_catalog factor and copy its value exactly.
- strategy_comparison must contain exactly the strategy ids supplied by available_strategies.
- If comparable candidate backtests are unavailable, backtest_evidence_available must be false. Do not invent performance metrics and do not use the related Core + Swing result as evidence comparing independent candidates.
- Missing data and missing comparable backtests must be reflected in confidence and limitations.
- hard_constraints are authoritative. A candidate outside currently_allowed_strategies can never be selected. allow_new_long=false or risk_off=true prohibits active long strategies and requires risk_off, no_strategy, or another supplied defensive equivalent.
- risk_off is a non-executable defensive state. no_strategy is a valid abstention when evidence is insufficient, conflicting, or non-actionable.
- Do not provide BUY/SELL/HOLD labels, guaranteed returns, certain price predictions, target prices, position sizes, or direct trading instructions.
- Return one JSON object only, without Markdown or chain-of-thought, with exactly these top-level fields:
  final_market_assessment: {regime, direction, confidence, summary}
  strategy_comparison: {<each candidate id>: {suitability, supporting_factors, conflicting_factors}}
  final_strategy_assessment: {selected_strategy, confidence, suitability, reason, why_not_alternatives}
  quantitative_agreement: {agrees_with_backend, differences}
  risk_assessment: {risk_level, risk_off, allow_new_long, summary}
  backtest_evidence_available: boolean
  supporting_evidence: [{factor, value, interpretation}]
  limitations: [string]
- Every supporting_factors and conflicting_factors value is an array of {factor, value, interpretation}; an empty array is allowed when no verified factor exists.
- regime: bullish_trend, bearish_trend, sideways_range, or high_volatility.
- direction: bullish, bearish, neutral, or mixed.
- both confidence fields: numbers from 0 to 1.
- every suitability field: high, medium, low, not_allowed, or insufficient_evidence.
- risk_level: low, medium, or high.
- why_not_alternatives must address every non-selected candidate. supporting_evidence must be non-empty.
"""


def _prompt(context, extra_instruction=''):
    user_prompt = (
        'Produce the final hybrid decision from this deterministic Agent Context '
        f'(prompt version {AGENT_ANALYSIS_PROMPT_VERSION}):\n\n'
        f'{json.dumps(context, indent=2, default=str)}'
    )
    if extra_instruction:
        user_prompt = f'{user_prompt}\n\n{extra_instruction}'
    return {'system': SYSTEM_PROMPT, 'user': user_prompt}


def build_unified_analysis_prompt(context):
    return _prompt(context)


def build_strict_json_retry_prompt(context):
    return _prompt(
        context,
        'Correction required: return valid JSON with every required field and exact evidence_catalog values.',
    )


def build_constraint_retry_prompt(context):
    return _prompt(
        context,
        'Correction required: remove action language and respect every Django hard constraint.',
    )


PROMPT_VERSION = AGENT_ANALYSIS_PROMPT_VERSION
