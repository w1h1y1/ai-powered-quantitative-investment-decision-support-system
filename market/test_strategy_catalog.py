from django.test import SimpleTestCase

from market.strategy_catalog import (
    AGENT_STRATEGY_IDS,
    DETERMINISTIC_STRATEGY_IDS,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_NO_STRATEGY,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    get_agent_strategy_catalog,
    get_related_backtest_strategy,
    get_strategy_definition,
)
from market.strategy_selection_service import STRATEGIES, select_strategy


class StrategyCatalogTests(SimpleTestCase):
    def test_catalog_has_all_agent_candidates_in_stable_order(self):
        self.assertEqual(
            AGENT_STRATEGY_IDS,
            (
                STRATEGY_TREND_FOLLOWING, STRATEGY_MEAN_REVERSION,
                STRATEGY_RISK_OFF, STRATEGY_NO_STRATEGY,
            ),
        )
        self.assertEqual(
            [item['id'] for item in get_agent_strategy_catalog()],
            list(AGENT_STRATEGY_IDS),
        )

    def test_deterministic_selector_keeps_only_implemented_policy_states(self):
        self.assertEqual(STRATEGIES, DETERMINISTIC_STRATEGY_IDS)
        self.assertNotIn(STRATEGY_NO_STRATEGY, STRATEGIES)

    def test_trend_following_documents_core_only_engine_and_real_controls(self):
        strategy = get_strategy_definition(STRATEGY_TREND_FOLLOWING)
        self.assertIn('Core-only', strategy['description'])
        self.assertIn('Swing disabled', strategy['description'])
        self.assertIn('2% of equity', ' '.join(strategy['position_risk_controls']))
        self.assertTrue(strategy['backtest_available'])
        self.assertTrue(strategy['executable'])

    def test_mean_reversion_documents_real_entry_exit_and_parameters(self):
        strategy = get_strategy_definition(STRATEGY_MEAN_REVERSION)
        entry = ' '.join(strategy['entry_conditions'])
        exit_conditions = ' '.join(strategy['exit_conditions'])
        self.assertIn('RSI14 is at or below 35', entry)
        self.assertIn('RSI14 reaches 55', exit_conditions)
        self.assertIn('fixed 2 ATR stop', exit_conditions)
        self.assertIn('50%', ' '.join(strategy['position_risk_controls']))

    def test_risk_off_and_no_strategy_are_non_executable_states(self):
        risk_off = get_strategy_definition(STRATEGY_RISK_OFF)
        no_strategy = get_strategy_definition(STRATEGY_NO_STRATEGY)
        self.assertEqual(risk_off['kind'], 'defensive_state')
        self.assertEqual(no_strategy['kind'], 'abstention_state')
        self.assertFalse(risk_off['executable'])
        self.assertFalse(no_strategy['executable'])
        self.assertFalse(risk_off['backtest_available'])
        self.assertFalse(no_strategy['backtest_available'])

    def test_related_core_swing_backtest_is_not_an_agent_candidate(self):
        related = get_related_backtest_strategy()
        self.assertEqual(related['id'], 'market-regime-core-swing')
        self.assertFalse(related['agent_candidate'])
        self.assertIn('core', related['components'])
        self.assertIn('swing', related['components'])

    def test_selector_exposes_definition_from_the_shared_catalog(self):
        result = select_strategy({
            'symbol': 'AAPL', 'regime_available': True,
            'regime': 'bullish_trend', 'confidence': 'medium',
            'confidence_score': 0.7,
        })
        self.assertEqual(
            result['strategy_definition'],
            get_strategy_definition(STRATEGY_TREND_FOLLOWING),
        )
        self.assertEqual(result['strategy_catalog'], get_agent_strategy_catalog())
