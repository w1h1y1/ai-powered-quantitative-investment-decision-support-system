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
- why_not_alternatives must be a JSON array of at least three separate strings, never one string or an object, and must address every non-selected candidate.
- differences, limitations, supporting_factors, and conflicting_factors must always be JSON arrays, including when empty. Never use null or a single string for an array field.
- supporting_evidence must be a non-empty JSON array. Evidence value may be a JSON number, string, or boolean only when copied exactly from evidence_catalog.
- Use the machine-readable enum tokens exactly as written above; do not output display labels, spaces, hyphens, title case, or percentage strings.
"""


def _schema_example(context):
    candidate_ids = [
        item.get('id') for item in (context.get('available_strategies') or [])
        if isinstance(item, dict) and item.get('id')
    ]
    candidate_ids = candidate_ids or [
        'trend_following', 'mean_reversion', 'risk_off', 'no_strategy',
    ]
    constraints = context.get('hard_constraints') or {}
    currently_allowed = set(
        constraints.get('currently_allowed_strategies') or candidate_ids
    )
    quantitative = context.get('quantitative_assessment') or {}
    selected = quantitative.get('suggested_strategy')
    if selected not in currently_allowed:
        selected = 'risk_off' if constraints.get('risk_off') is True else 'no_strategy'
    if selected not in candidate_ids:
        selected = candidate_ids[0]
    comparison = {}
    for strategy_id in candidate_ids:
        if strategy_id not in currently_allowed:
            suitability = 'not_allowed'
        elif strategy_id == selected:
            suitability = 'high'
        else:
            suitability = 'medium'
        comparison[strategy_id] = {
            'suitability': suitability,
            'supporting_factors': [],
            'conflicting_factors': [],
        }
    evidence_catalog = context.get('evidence_catalog') or []
    evidence_source = next(
        (item for item in evidence_catalog if isinstance(item, dict) and item.get('factor')),
        {'factor': 'Preliminary Regime', 'value': quantitative.get('preliminary_regime')},
    )
    confidence = quantitative.get('confidence')
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = 0.5
    direction = str((context.get('market_regime') or {}).get('direction') or 'neutral').lower()
    if direction not in {'bullish', 'bearish', 'neutral', 'mixed'}:
        direction = 'neutral'
    regime = quantitative.get('preliminary_regime')
    if regime not in {'bullish_trend', 'bearish_trend', 'sideways_range', 'high_volatility'}:
        regime = 'high_volatility'
    return {
        'final_market_assessment': {
            'regime': regime,
            'direction': direction,
            'confidence': confidence,
            'summary': 'Concise assessment using only supplied evidence.',
        },
        'strategy_comparison': comparison,
        'final_strategy_assessment': {
            'selected_strategy': selected,
            'confidence': confidence,
            'suitability': comparison[selected]['suitability'],
            'reason': 'Concise relative strategy rationale.',
            'why_not_alternatives': [
                f'{strategy_id} was not selected because it ranked below {selected}.'
                for strategy_id in candidate_ids if strategy_id != selected
            ],
        },
        'quantitative_agreement': {
            'agrees_with_backend': selected == quantitative.get('suggested_strategy'),
            'differences': (
                [] if selected == quantitative.get('suggested_strategy')
                else ['Final strategy differs because the preliminary candidate is currently prohibited.']
            ),
        },
        'risk_assessment': {
            'risk_level': 'high' if constraints.get('risk_off') is True else 'medium',
            'risk_off': constraints.get('risk_off') is True,
            'allow_new_long': constraints.get('allow_new_long') is True,
            'summary': 'Django hard constraints remain authoritative.',
        },
        'backtest_evidence_available': (
            (context.get('strategy_evidence') or {}).get('backtest_evidence_available') is True
        ),
        'supporting_evidence': [{
            'factor': evidence_source.get('factor'),
            'value': evidence_source.get('value'),
            'interpretation': 'Concise interpretation of the copied value.',
        }],
        'limitations': [],
    }


def _prompt(context, extra_instruction=''):
    user_prompt = (
        'Produce the final hybrid decision from this deterministic Agent Context '
        f'(prompt version {AGENT_ANALYSIS_PROMPT_VERSION}):\n\n'
        'Follow this complete JSON shape exactly. The example uses current Context values '
        'only to demonstrate types; still perform the required independent comparison:\n'
        f'{json.dumps(_schema_example(context), indent=2, default=str)}\n\n'
        'Agent Context:\n'
        f'{json.dumps(context, indent=2, default=str)}'
    )
    if extra_instruction:
        user_prompt = f'{user_prompt}\n\n{extra_instruction}'
    return {'system': SYSTEM_PROMPT, 'user': user_prompt}


def build_unified_analysis_prompt(context):
    return _prompt(context)


def build_strict_json_retry_prompt(context, validation_details=None):
    detail_text = ''
    if validation_details:
        detail_text = (
            ' The previous response failed this safe validation diagnostic: '
            f'{json.dumps(validation_details, default=str)}.'
        )
    return _prompt(
        context,
        'Correction required: return a corrected complete JSON object only, with every '
        'required field, exact machine enum tokens, correct JSON types, and exact '
        f'evidence_catalog values.{detail_text}',
    )


def build_schema_repair_prompt(context, validation_details):
    return build_strict_json_retry_prompt(context, validation_details)


def build_constraint_retry_prompt(context):
    return _prompt(
        context,
        'Correction required: remove action language and respect every Django hard constraint.',
    )


PROMPT_VERSION = AGENT_ANALYSIS_PROMPT_VERSION
