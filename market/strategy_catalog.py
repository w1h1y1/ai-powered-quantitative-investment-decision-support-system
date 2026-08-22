"""Single source of truth for formal strategy names and capabilities.

The descriptions below document the strategies that already exist in the
selector and backtest engines.  They do not implement signals themselves;
signal calculations remain in ``backtest.services`` and
``backtest.strategy_evaluation_service``.
"""

from copy import deepcopy


STRATEGY_TREND_FOLLOWING = 'trend_following'
STRATEGY_MEAN_REVERSION = 'mean_reversion'
STRATEGY_RISK_OFF = 'risk_off'
STRATEGY_NO_STRATEGY = 'no_strategy'

DETERMINISTIC_STRATEGY_IDS = (
    STRATEGY_TREND_FOLLOWING,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RISK_OFF,
)
AGENT_STRATEGY_IDS = DETERMINISTIC_STRATEGY_IDS + (STRATEGY_NO_STRATEGY,)


STRATEGY_CATALOG = {
    STRATEGY_TREND_FOLLOWING: {
        'id': STRATEGY_TREND_FOLLOWING,
        'name': 'Trend Following',
        'kind': 'active_long_strategy',
        'description': (
            'The existing Core-only medium-term trend evaluator. It uses the '
            'layered strategy engine with Swing disabled; it is not the full '
            'Core + Swing Backtest-page strategy.'
        ),
        'indicators': [
            'EMA10', 'MA20', 'MA60', 'RSI14', 'MACD', 'ATR14',
            'benchmark MA50/MA200 regime',
        ],
        'entry_conditions': [
            'Two consecutive bullish Core trend states, or a confirmed reversal into a bullish state.',
            'The benchmark-derived market regime must not be Bear.',
            'Signals formed at the close execute at the next trading-day open.',
        ],
        'exit_conditions': [
            'A Bear trend state triggers a full Core exit.',
            'An ATR risk event or a new weak-bull state can reduce, rather than fully close, Core exposure.',
        ],
        'supporting_conditions': [
            'Strong directional trend and consistent moving-average structure.',
            'Momentum and trend-state evidence aligned in the same direction.',
            'A non-bearish benchmark regime.',
        ],
        'conflicting_conditions': [
            'Weak trend strength or highly choppy price behaviour.',
            'A bearish benchmark regime or deteriorating momentum.',
        ],
        'risk_considerations': [
            'Sideways conditions can produce whipsaw losses.',
            'The evaluator is long-only and cannot express a short bearish view.',
        ],
        'position_risk_controls': [
            'Default Core risk fraction is 2% of equity with a 2.5 ATR stop distance.',
            'Default Core exposure is capped at 80%; weak/ATR reductions default to 25%.',
        ],
        'parameter_source': 'backtest.services.StrategyParameters',
        'implementation_reference': 'backtest.strategy_evaluation_service.evaluate_trend_following',
        'backtest_available': True,
        'agent_selectable': True,
        'executable': True,
        'preliminary_selection_rationale': (
            'Trend Following is generally favoured when directional structure, '
            'trend strength, and momentum evidence are aligned.'
        ),
    },
    STRATEGY_MEAN_REVERSION: {
        'id': STRATEGY_MEAN_REVERSION,
        'name': 'Mean Reversion',
        'kind': 'active_long_strategy',
        'description': (
            'The independent long-only Mean Reversion v1 evaluator using a '
            '20-day mean, RSI14, Bollinger Bands, and ATR risk control.'
        ),
        'indicators': ['MA20', 'RSI14', 'Bollinger Bands (20, 2)', 'ATR14'],
        'entry_conditions': [
            'Close is at or below the 20-day lower Bollinger Band and RSI14 is at or below 35.',
            'Signals formed at the close execute at the next trading-day open.',
        ],
        'exit_conditions': [
            'Close reaches MA20, RSI14 reaches 55, or the fixed 2 ATR stop is hit.',
        ],
        'supporting_conditions': [
            'Weak directional strength and range-bound or choppy behaviour.',
            'A temporary downside deviation from the 20-day mean with oversold RSI.',
        ],
        'conflicting_conditions': [
            'A strong persistent directional trend.',
            'Momentum that continues to deteriorate after the apparent deviation.',
        ],
        'risk_considerations': [
            'Price may continue moving away from the mean during a persistent trend.',
            'The strategy is long-only and only models downside-deviation entries.',
        ],
        'position_risk_controls': [
            'Default risk fraction is 1% of equity with a fixed 2 ATR stop distance.',
            'Default maximum exposure is 50%.',
        ],
        'parameter_source': 'backtest.strategy_evaluation_service.MEAN_REVERSION_*',
        'implementation_reference': 'backtest.strategy_evaluation_service.evaluate_mean_reversion',
        'backtest_available': True,
        'agent_selectable': True,
        'executable': True,
        'preliminary_selection_rationale': (
            'Mean Reversion is generally favoured when directional strength is '
            'weak and range/deviation evidence is present.'
        ),
    },
    STRATEGY_RISK_OFF: {
        'id': STRATEGY_RISK_OFF,
        'name': 'Defensive / Risk-Off',
        'kind': 'defensive_state',
        'description': (
            'A defensive state used when normal long-strategy deployment is '
            'prohibited. It has no independent trading evaluator.'
        ),
        'indicators': ['Volatility percentile', 'ATR volatility', 'hard risk constraints'],
        'entry_conditions': [],
        'exit_conditions': [],
        'supporting_conditions': [
            'Excessive volatility or material downside risk.',
            'A hard risk constraint that prohibits new long exposure.',
        ],
        'conflicting_conditions': [
            'Normal volatility with complete, consistently supportive evidence.',
        ],
        'risk_considerations': [
            'This is a non-executable defensive state, not a return-seeking strategy.',
        ],
        'position_risk_controls': ['New long exposure remains disabled when hard Risk-Off is active.'],
        'parameter_source': None,
        'implementation_reference': 'market.strategy_selection_service.select_strategy',
        'backtest_available': False,
        'agent_selectable': True,
        'executable': False,
        'preliminary_selection_rationale': (
            'Risk control favours Risk-Off when volatility is extreme or hard '
            'constraints prohibit active long strategies.'
        ),
    },
    STRATEGY_NO_STRATEGY: {
        'id': STRATEGY_NO_STRATEGY,
        'name': 'No Suitable Strategy',
        'kind': 'abstention_state',
        'description': (
            'An Agent abstention state for insufficient, materially conflicting, '
            'or non-actionable evidence. It is not a backtest strategy.'
        ),
        'indicators': ['data-quality flags', 'cross-indicator consistency', 'hard risk constraints'],
        'entry_conditions': [],
        'exit_conditions': [],
        'supporting_conditions': [
            'Key indicators or history are missing.',
            'Candidate evidence is materially conflicting or all active candidates have low suitability.',
            'Hard constraints prohibit every active candidate.',
        ],
        'conflicting_conditions': [
            'Complete, consistent evidence strongly supports an allowed active strategy.',
        ],
        'risk_considerations': ['Abstention avoids forcing a strategy choice from weak evidence.'],
        'position_risk_controls': ['No new executable strategy is selected.'],
        'parameter_source': None,
        'implementation_reference': 'agent.unified_analysis_schema.normalize_unified_analysis',
        'backtest_available': False,
        'agent_selectable': True,
        'executable': False,
        'preliminary_selection_rationale': (
            'No Suitable Strategy is considered when data is insufficient, '
            'evidence is materially conflicting, or active strategies are prohibited.'
        ),
    },
}


RELATED_BACKTEST_STRATEGY = {
    'id': 'market-regime-core-swing',
    'name': 'Market-Regime Core and Swing Strategy',
    'description': (
        'The Backtest-page layered strategy: a Core trend position plus an '
        'optional pullback-rebound Swing layer. It is separate from the '
        'independent Mean Reversion evaluator.'
    ),
    'components': {
        'core': (
            'Medium-term trend layer using trend states, MA20/MA60, EMA10, '
            'RSI14, MACD, ATR14, and benchmark MA50/MA200 regime.'
        ),
        'swing': (
            'A smaller pullback-rebound layer allowed only while an eligible '
            'Core position exists; it uses EMA10/SMA10, RSI14, MACD, Bollinger '
            'resistance, ATR stops, and trend-failure exits.'
        ),
    },
    'parameter_source': 'backtest.services.StrategyParameters',
    'implementation_reference': 'backtest.services.run_market_regime_core_swing_backtest',
    'backtest_page_available': True,
    'agent_candidate': False,
}


def get_strategy_definition(strategy_id):
    definition = STRATEGY_CATALOG.get(strategy_id)
    return deepcopy(definition) if definition else None


def get_agent_strategy_catalog():
    return [deepcopy(STRATEGY_CATALOG[strategy_id]) for strategy_id in AGENT_STRATEGY_IDS]


def get_related_backtest_strategy():
    return deepcopy(RELATED_BACKTEST_STRATEGY)


__all__ = [
    'AGENT_STRATEGY_IDS', 'DETERMINISTIC_STRATEGY_IDS',
    'STRATEGY_CATALOG', 'STRATEGY_MEAN_REVERSION', 'STRATEGY_NO_STRATEGY',
    'STRATEGY_RISK_OFF', 'STRATEGY_TREND_FOLLOWING',
    'get_agent_strategy_catalog', 'get_related_backtest_strategy',
    'get_strategy_definition',
]
