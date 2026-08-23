"""Prompt construction for an independent LLM strategy assessment."""

import json

from .unified_analysis_schema import AGENT_ANALYSIS_PROMPT_VERSION


SYSTEM_PROMPT = """You are the independent AI assessment stage of an investment decision-support system.
You receive neutral facts, formal candidate definitions, evidence availability, and hard safety constraints.
You do not receive the Django quantitative engine's regime or suggested strategy. Do not infer or discuss
what that hidden backend opinion might be. Return concise structured conclusions, never hidden reasoning.

Required evaluation order:
1. Check data_quality and identify material missing evidence.
2. Assess price and moving-average structure.
3. Assess ADX and Choppiness trend strength and range behaviour.
4. Assess RSI and MACD momentum.
5. Assess volatility and relative market/sector performance.
6. If supplied, use the complete Market-Regime Hybrid Strategy backtest only as contextual evidence
   about the implemented Core + Swing system. It is not candidate-comparison evidence.
7. Evaluate every available strategy exactly once with both supporting and conflicting evidence.
8. Select one supplied strategy id, including no_strategy when evidence is insufficient or non-actionable.
9. Explain why every non-selected candidate was not selected.
10. Lower confidence when data is missing or evidence conflicts.

Candidate principles:
- trend_following improves only when direction, moving averages, trend strength, momentum, benchmark context,
  and current-condition evidence are sufficiently aligned.
- mean_reversion requires actual entry evidence. A sideways/range label alone is never sufficient. Check the
  supplied lower-band and RSI entry-condition facts; when entry_conditions_met is false, do not select it.
- risk_off is a defensive state, not an independently backtested return strategy. It is appropriate for hard
  risk restrictions, extreme volatility, or risk evidence that materially dominates return evidence.
- no_strategy is valid for missing data, severe conflicts, low suitability across active strategies, absent
  entry conditions, or non-actionable evidence. Never force a choice between the two active strategies.

Hard rules:
- Use only the supplied LLM Strategy Context. Never invent or recalculate values.
- Every evidence object must copy factor, source_path, and value from one evidence_catalog entry exactly.
- Do not put new numeric claims in narrative text. Numeric display comes from validated evidence objects.
- llm_strategy_comparison must contain exactly every id in available_strategies.
- This project has exactly one formal backtest: Market-Regime Hybrid Strategy (Core + Swing), strategy id
  market-regime-core-swing. Its Core uses trend-following logic and its Swing component uses pullback-based
  logic. Neither component is a standalone Trend Following or Mean Reversion backtest.
- hybrid_backtest_evidence_available must exactly match hybrid_backtest_evidence.available.
- Never claim that Trend Following, Mean Reversion, Risk-Off, or No Strategy has a standalone backtest.
- Never use the Hybrid result to rank candidates or claim one candidate historically outperformed another.
- Candidate cards are a current-market-suitability comparison based on technical indicators, market regime,
  relative performance, entry conditions, risk, and hard constraints—not historical candidate returns.
- If Hybrid evidence is unavailable, state that limitation and assess current suitability from the remaining
  supplied indicators, regime, relative performance, entry-condition, and risk evidence.
- Copy any cited Hybrid metric exactly from evidence_catalog; never invent annualized return, Sharpe ratio,
  CAGR, alpha, or other metrics absent from hybrid_backtest_evidence.
- hard_constraints are authoritative, but Django will independently enforce them after this response.
- Do not provide BUY/SELL/HOLD labels, guaranteed returns, certain price predictions, target prices,
  position sizes, or direct trading instructions.
- Return one JSON object only, without Markdown, prefixes, suffixes, or chain-of-thought, with exactly:
  llm_market_assessment: {regime, direction, confidence, summary}
  llm_strategy_comparison: {<each candidate id>: {suitability, supporting_factors, conflicting_factors}}
  llm_final_strategy_assessment: {selected_strategy, confidence, suitability, reason, why_not_alternatives}
  llm_risk_assessment: {risk_level, summary}
  hybrid_backtest_evidence_available: boolean
  supporting_evidence: [{factor, source_path, value, interpretation}]
  limitations: [string]
- supporting_factors and conflicting_factors are arrays of {factor, source_path, value, interpretation}.
- regime: bullish_trend, bearish_trend, sideways_range, or high_volatility.
- direction: bullish, bearish, neutral, or mixed.
- confidence: JSON numbers from 0 to 1.
- suitability: high, medium, low, not_allowed, or insufficient_evidence.
- risk_level: low, medium, or high.
- why_not_alternatives must be an array of at least three separate strings addressing every alternative.
- All list fields must be JSON arrays, including when empty. supporting_evidence must be non-empty.
- Use machine-readable enum tokens exactly; do not use display labels or percentage strings.
"""


def _schema_example(context):
    candidate_ids = [
        item.get('id') for item in (context.get('available_strategies') or [])
        if isinstance(item, dict) and item.get('id')
    ] or ['trend_following', 'mean_reversion', 'risk_off', 'no_strategy']
    constraints = context.get('hard_constraints') or {}
    currently_allowed = set(
        constraints.get('currently_allowed_strategies') or candidate_ids
    )
    selected = 'no_strategy' if 'no_strategy' in candidate_ids else candidate_ids[0]
    comparison = {
        strategy_id: {
            'suitability': (
                'not_allowed' if strategy_id not in currently_allowed
                else 'high' if strategy_id == selected else 'medium'
            ),
            'supporting_factors': [],
            'conflicting_factors': [],
        }
        for strategy_id in candidate_ids
    }
    evidence = next(
        (item for item in (context.get('evidence_catalog') or []) if isinstance(item, dict) and item.get('source_path')),
        {'factor': 'Data Available', 'source_path': 'market_data.available', 'value': False},
    )
    return {
        'llm_market_assessment': {
            'regime': 'sideways_range', 'direction': 'mixed', 'confidence': 0.5,
            'summary': 'Concise qualitative assessment without new numeric claims.',
        },
        'llm_strategy_comparison': comparison,
        'llm_final_strategy_assessment': {
            'selected_strategy': selected,
            'confidence': 0.5,
            'suitability': comparison[selected]['suitability'],
            'reason': 'Concise strategy rationale grounded in referenced evidence.',
            'why_not_alternatives': [
                f'{strategy_id} was not selected because current validated evidence was less suitable.'
                for strategy_id in candidate_ids if strategy_id != selected
            ],
        },
        'llm_risk_assessment': {
            'risk_level': 'medium', 'summary': 'Concise qualitative risk assessment.',
        },
        'hybrid_backtest_evidence_available': (
            (context.get('hybrid_backtest_evidence') or {}).get('available') is True
        ),
        'supporting_evidence': [{
            'factor': evidence.get('factor'), 'source_path': evidence.get('source_path'),
            'value': evidence.get('value'),
            'interpretation': 'Concise interpretation of this verified field.',
        }],
        'limitations': [],
    }


def _prompt(context, extra_instruction=''):
    user_prompt = (
        'Produce an independent strategy assessment from this isolated LLM Strategy Context '
        f'(prompt version {AGENT_ANALYSIS_PROMPT_VERSION}).\n\n'
        'Follow this JSON shape exactly. Values illustrate types and do not imply a preferred strategy:\n'
        f'{json.dumps(_schema_example(context), indent=2, default=str)}\n\n'
        'LLM Strategy Context:\n'
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
        'Correction required: return one corrected complete JSON object with exact field names, '
        'types, enum tokens, source_path references, and evidence_catalog values.' + detail_text,
    )


def build_schema_repair_prompt(context, validation_details):
    return build_strict_json_retry_prompt(context, validation_details)


def build_constraint_retry_prompt(context):
    return _prompt(context, 'Correction required: remove action language and respect supplied hard constraints.')


PROMPT_VERSION = AGENT_ANALYSIS_PROMPT_VERSION
