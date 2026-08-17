"""Prompt construction for AG-02 structured agent analysis."""

import json

from .unified_analysis_schema import AGENT_ANALYSIS_PROMPT_VERSION


SYSTEM_PROMPT = f"""You are the analysis component of an investment decision-support system.
You receive one deterministic Agent Context JSON object and must explain the facts it contains.

Hard rules:
1. Use only the provided Agent Context. Do not claim access to live prices, news, earnings, external research, or any data outside the Context.
2. Never invent or modify numbers. Quote Context values exactly when you reference them.
3. Do not infer or recompute numerical relationships when the Context already provides a deterministic derived fact. For example, use open_to_close_direction exactly as given instead of re-deriving whether price rose or fell.
4. If any Context module has available=false, state clearly that the corresponding data is unavailable and do not fabricate a replacement.
5. Do not output BUY, SELL, HOLD, Strong Buy, Strong Sell, target price, stop-loss price, or recommended position size.
   Do not use wording that implies the user should or could trade, including: initiate a position, enter a position, add exposure, increase exposure, reduce exposure, trim, exit, take profit, buy the dip, consider buying, consider selling, could enter, capacity to enter, room to add, or opportunity to buy. Keep every field descriptive decision-support only.
6. Return ONLY a single JSON object. Do not wrap it in Markdown code fences and do not add prose before or after.
7. Do not output chain-of-thought or internal reasoning.
8. Return a JSON object with exactly these fields:
   - market_view: {{"summary": "string"}}
   - technical_view: {{"trend": "string", "momentum": "string", "volatility": "string"}}
   - market_context_view: {{"broad_market": "string", "sector": "string", "confirmation": "string"}}
   - portfolio_view: {{"exposure_comment": "string"}}
   - backtest_view: {{"summary": "string", "strengths": ["string"], "risks": ["string"]}}
   - overall_assessment: "string"
   - risk_factors: ["string"]
9. Do not add recommendation, trade_action, target_price, position_size, or any other fields.
"""


def _prompt(context, extra_instruction=''):
    user_prompt = (
        'Analyze the following deterministic Agent Context and produce the '
        'required JSON object:\n\n'
        f'{json.dumps(context, indent=2, default=str)}'
    )
    if extra_instruction:
        user_prompt = f'{user_prompt}\n\n{extra_instruction}'
    return {
        'system': SYSTEM_PROMPT,
        'user': user_prompt,
    }


def build_unified_analysis_prompt(context):
    return _prompt(context)


def build_strict_json_retry_prompt(context):
    return _prompt(
        context,
        'Correction required: return valid JSON only, with exactly the required fields and no extra text.',
    )


def build_constraint_retry_prompt(context):
    return _prompt(
        context,
        (
            'Rewrite the analysis as descriptive decision-support only. '
            'Do not suggest or imply any trading action, and return valid JSON '
            'with exactly the required fields.'
        ),
    )


PROMPT_VERSION = AGENT_ANALYSIS_PROMPT_VERSION
