from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from portfolio.models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction

from .models import Security
from .regime_config import (
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
)
from .regime_service import MarketRegimeDataRateLimited, MarketRegimeDataUnavailable
from .strategy_selection_service import (
    EXECUTION_MODE_LONG_ONLY,
    REGIME_STRATEGY_MAP,
    STRATEGIES,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_MODE_ACTIVE,
    STRATEGY_MODE_DEFENSIVE,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    select_strategy,
)


def market_regime_payload(
    regime=REGIME_BULLISH,
    *,
    available=True,
    confidence='high',
    confidence_score=0.8,
):
    return {
        'symbol': 'AAPL',
        'security_id': 1,
        'regime_available': available,
        'regime_unavailable_reason': None if available else 'insufficient_history',
        'regime': regime if available else None,
        'confidence': confidence if available else None,
        'confidence_score': confidence_score if available else None,
        'trend': {'score': 0.7},
        'market_context': {'spy_regime': REGIME_SIDEWAYS},
    }


class StrategySelectionRuleTests(SimpleTestCase):
    def test_v1_mapping_contains_exactly_four_regimes_and_three_strategies(self):
        self.assertEqual(
            set(REGIME_STRATEGY_MAP),
            {REGIME_BULLISH, REGIME_BEARISH, REGIME_SIDEWAYS, REGIME_HIGH_VOLATILITY},
        )
        self.assertEqual(
            {rule.selected_strategy for rule in REGIME_STRATEGY_MAP.values()},
            set(STRATEGIES),
        )

    def test_each_regime_activates_exactly_one_complete_strategy_path(self):
        expected_paths = {
            REGIME_BULLISH: (STRATEGY_TREND_FOLLOWING, STRATEGY_MODE_ACTIVE, True, False),
            REGIME_BEARISH: (STRATEGY_TREND_FOLLOWING, STRATEGY_MODE_ACTIVE, False, False),
            REGIME_SIDEWAYS: (STRATEGY_MEAN_REVERSION, STRATEGY_MODE_ACTIVE, True, False),
            REGIME_HIGH_VOLATILITY: (STRATEGY_RISK_OFF, STRATEGY_MODE_DEFENSIVE, False, True),
        }
        for regime, expected in expected_paths.items():
            with self.subTest(regime=regime):
                result = select_strategy(market_regime_payload(regime))
                actual = (
                    result['selected_strategy'],
                    result['strategy_mode'],
                    result['allow_new_long'],
                    result['risk_off'],
                )
                self.assertEqual(actual, expected)

    def test_reason_and_confidence_are_isolated_to_each_regime(self):
        for regime in (
            REGIME_BULLISH,
            REGIME_BEARISH,
            REGIME_SIDEWAYS,
            REGIME_HIGH_VOLATILITY,
        ):
            with self.subTest(regime=regime):
                payload = market_regime_payload(
                    regime,
                    confidence='medium',
                    confidence_score=0.63,
                )
                payload['explanation'] = ['UPSTREAM_SENTINEL']

                result = select_strategy(payload)

                rule_reasons = list(REGIME_STRATEGY_MAP[regime].reason)
                self.assertEqual(result['reason'][0], rule_reasons[0])
                self.assertEqual(result['reason'][2:], rule_reasons[1:])
                self.assertEqual(
                    result['reason'][1],
                    result['strategy_definition']['preliminary_selection_rationale'],
                )
                self.assertNotIn('UPSTREAM_SENTINEL', ' '.join(result['reason']))
                self.assertEqual(result['regime_confidence'], 'medium')
                self.assertEqual(result['selection_confidence'], 'medium')
                self.assertEqual(result['regime_confidence_score'], 0.63)

    def test_bullish_trend_selects_active_trend_following(self):
        result = select_strategy(market_regime_payload(
            REGIME_BULLISH,
            confidence='medium',
            confidence_score=0.68,
        ))

        self.assertTrue(result['strategy_selection_available'])
        self.assertEqual(result['market_regime'], REGIME_BULLISH)
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(result['strategy_mode'], STRATEGY_MODE_ACTIVE)
        self.assertEqual(result['execution_mode'], EXECUTION_MODE_LONG_ONLY)
        self.assertTrue(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assertEqual(result['selection_confidence'], 'medium')
        self.assertEqual(result['regime_confidence_score'], 0.68)
        explanation = ' '.join(result['reason'])
        self.assertIn('Bullish Trend', explanation)
        self.assertIn('Trend Following', explanation)
        for unrelated_text in (
            'Sideways', 'Mean Reversion', 'High Volatility', 'Risk-Off',
        ):
            self.assertNotIn(unrelated_text, explanation)

    def test_sideways_range_selects_active_mean_reversion(self):
        result = select_strategy(market_regime_payload(REGIME_SIDEWAYS))

        self.assertTrue(result['strategy_selection_available'])
        self.assertEqual(result['market_regime'], REGIME_SIDEWAYS)
        self.assertEqual(result['selected_strategy'], STRATEGY_MEAN_REVERSION)
        self.assertEqual(result['strategy_mode'], STRATEGY_MODE_ACTIVE)
        self.assertTrue(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        explanation = ' '.join(result['reason'])
        self.assertIn('Sideways / Range', explanation)
        self.assertIn('Mean Reversion', explanation)
        self.assertNotIn('Trend Following', explanation)
        self.assertNotIn('High Volatility', explanation)

    def test_high_volatility_selects_defensive_risk_off(self):
        result = select_strategy(market_regime_payload(REGIME_HIGH_VOLATILITY))

        self.assertTrue(result['strategy_selection_available'])
        self.assertEqual(result['market_regime'], REGIME_HIGH_VOLATILITY)
        self.assertEqual(result['selected_strategy'], STRATEGY_RISK_OFF)
        self.assertEqual(result['strategy_mode'], STRATEGY_MODE_DEFENSIVE)
        self.assertFalse(result['allow_new_long'])
        self.assertTrue(result['risk_off'])
        explanation = ' '.join(result['reason'])
        self.assertIn('High Volatility', explanation)
        self.assertIn('Risk control', explanation)
        self.assertNotIn('Trend Following', explanation)
        self.assertNotIn('Mean Reversion', explanation)

    def test_bearish_trend_keeps_trend_following_with_long_only_entry_constraint(self):
        result = select_strategy(market_regime_payload(
            REGIME_BEARISH,
            confidence='medium',
            confidence_score=0.64,
        ))

        self.assertTrue(result['strategy_selection_available'])
        self.assertEqual(result['market_regime'], REGIME_BEARISH)
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertNotEqual(result['selected_strategy'], STRATEGY_MEAN_REVERSION)
        self.assertEqual(result['strategy_mode'], STRATEGY_MODE_ACTIVE)
        self.assertEqual(result['execution_mode'], EXECUTION_MODE_LONG_ONLY)
        self.assertFalse(result['allow_new_long'])
        self.assertFalse(result['risk_off'])
        self.assertEqual(result['selection_confidence'], 'medium')
        self.assertEqual(result['regime_confidence_score'], 0.64)
        explanation = ' '.join(result['reason'])
        self.assertIn('Bearish Trend', explanation)
        self.assertIn('long-only', explanation)
        self.assertIn('Trend Following', explanation)
        for unrelated_text in (
            'Sideways', 'Mean Reversion', 'High Volatility', 'Risk-Off',
        ):
            self.assertNotIn(unrelated_text, explanation)

    def test_market_regime_unavailable_does_not_invent_a_strategy(self):
        result = select_strategy(market_regime_payload(available=False))

        self.assertFalse(result['strategy_selection_available'])
        self.assertEqual(
            result['strategy_selection_unavailable_reason'],
            'market_regime_unavailable',
        )
        self.assertEqual(result['market_regime_unavailable_reason'], 'insufficient_history')
        for field in (
            'selected_strategy', 'strategy_mode', 'allow_new_long', 'risk_off',
            'selection_confidence',
        ):
            self.assertIsNone(result[field])

    def test_low_regime_confidence_is_preserved_without_changing_strategy(self):
        result = select_strategy(market_regime_payload(
            REGIME_SIDEWAYS,
            confidence='low',
            confidence_score=0.42,
        ))

        self.assertEqual(result['selected_strategy'], STRATEGY_MEAN_REVERSION)
        self.assertEqual(result['regime_confidence'], 'low')
        self.assertEqual(result['regime_confidence_score'], 0.42)
        self.assertEqual(result['selection_confidence'], 'low')

    def test_unknown_or_missing_available_regime_returns_unavailable_without_key_error(self):
        unknown = market_regime_payload('new_future_regime')
        missing = market_regime_payload()
        missing.pop('regime')

        for payload in (unknown, missing):
            result = select_strategy(payload)
            self.assertFalse(result['strategy_selection_available'])
            self.assertEqual(
                result['strategy_selection_unavailable_reason'],
                'unsupported_market_regime',
            )
            self.assertIsNone(result['selected_strategy'])

    @patch('market.regime_service.compute_core_regime')
    def test_selector_treats_market_regime_as_read_only_and_recalculates_no_indicators(
        self,
        compute_core_regime,
    ):
        payload = market_regime_payload(REGIME_BULLISH)
        original = deepcopy(payload)

        select_strategy(payload)

        self.assertEqual(payload, original)
        compute_core_regime.assert_not_called()


class StrategySelectionApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='strategy-selection-user',
            password='password123',
        )
        self.client.force_authenticate(self.user)
        self.security = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )

    @patch('market.views.select_strategy', wraps=select_strategy)
    @patch('market.views.get_market_regime')
    def test_api_resolves_security_calls_market_regime_once_and_returns_full_schema(
        self,
        get_market_regime,
        select_strategy_mock,
    ):
        get_market_regime.return_value = market_regime_payload(
            REGIME_BULLISH,
            confidence='medium',
            confidence_score=0.68,
        )

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'aapl'})

        self.assertEqual(response.status_code, 200)
        get_market_regime.assert_called_once_with(self.security)
        select_strategy_mock.assert_called_once_with(get_market_regime.return_value)
        self.assertEqual(response.data['symbol'], 'AAPL')
        self.assertTrue(response.data['strategy_selection_available'])
        self.assertEqual(response.data['market_regime'], REGIME_BULLISH)
        self.assertEqual(response.data['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(response.data['strategy_mode'], STRATEGY_MODE_ACTIVE)
        self.assertTrue(response.data['allow_new_long'])
        self.assertFalse(response.data['risk_off'])
        self.assertEqual(response.data['selection_confidence'], 'medium')
        explanation = ' '.join(response.data['reason'])
        self.assertIn('Bullish Trend', explanation)
        self.assertIn('Trend Following', explanation)
        self.assertNotIn('Mean Reversion', explanation)
        self.assertNotIn('High Volatility', explanation)
        expected_fields = {
            'symbol',
            'strategy_selection_available',
            'strategy_selection_unavailable_reason',
            'market_regime',
            'regime_confidence',
            'regime_confidence_score',
            'selected_strategy',
            'strategy_mode',
            'execution_mode',
            'allow_new_long',
            'risk_off',
            'selection_confidence',
            'reason',
        }
        self.assertTrue(expected_fields.issubset(response.data))

    @patch('market.views.get_market_regime')
    def test_api_mocked_bearish_trend_preserves_long_only_trend_following(
        self,
        get_market_regime,
    ):
        get_market_regime.return_value = market_regime_payload(
            REGIME_BEARISH,
            confidence='high',
            confidence_score=0.81,
        )

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 200)
        get_market_regime.assert_called_once_with(self.security)
        self.assertTrue(response.data['strategy_selection_available'])
        self.assertEqual(response.data['market_regime'], REGIME_BEARISH)
        self.assertEqual(response.data['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertNotEqual(response.data['selected_strategy'], STRATEGY_MEAN_REVERSION)
        self.assertEqual(response.data['strategy_mode'], STRATEGY_MODE_ACTIVE)
        self.assertEqual(response.data['execution_mode'], EXECUTION_MODE_LONG_ONLY)
        self.assertFalse(response.data['allow_new_long'])
        self.assertFalse(response.data['risk_off'])
        self.assertEqual(response.data['selection_confidence'], 'high')
        explanation = ' '.join(response.data['reason'])
        self.assertIn('Bearish Trend', explanation)
        self.assertIn('long-only', explanation)
        self.assertIn('Trend Following', explanation)
        self.assertNotIn('Risk-Off', explanation)
        self.assertNotIn('Mean Reversion', explanation)

    @patch('market.views.get_market_regime')
    def test_api_returns_200_unavailable_when_market_regime_is_unavailable(
        self,
        get_market_regime,
    ):
        get_market_regime.return_value = market_regime_payload(available=False)

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['strategy_selection_available'])
        self.assertIsNone(response.data['selected_strategy'])

    @patch('market.views.select_strategy')
    @patch('market.views.get_market_regime')
    def test_rate_limit_returns_429_without_selecting_a_fallback_strategy(
        self,
        get_market_regime,
        select_strategy_mock,
    ):
        get_market_regime.side_effect = MarketRegimeDataRateLimited('Provider rate limit reached.')

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['detail'], 'Provider rate limit reached.')
        get_market_regime.assert_called_once_with(self.security)
        select_strategy_mock.assert_not_called()

    @patch('market.views.select_strategy')
    @patch('market.views.get_market_regime')
    def test_market_data_failure_returns_503_without_selecting_a_fallback_strategy(
        self,
        get_market_regime,
        select_strategy_mock,
    ):
        get_market_regime.side_effect = MarketRegimeDataUnavailable('Market data unavailable.')

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['detail'], 'Market data unavailable.')
        get_market_regime.assert_called_once_with(self.security)
        select_strategy_mock.assert_not_called()

    def test_unknown_security_returns_400_validation_error(self):
        response = self.client.get(reverse('strategy-selection'), {'symbol': 'MISSING'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Security is not available.', response.data['symbol'])

    @patch('market.views.get_market_regime')
    def test_risk_off_does_not_create_trades_or_change_portfolio_state(
        self,
        get_market_regime,
    ):
        portfolio = Portfolio.objects.create(
            user=self.user,
            name='Strategy isolation portfolio',
            available_funds=Decimal('10000.00'),
            initial_balance=Decimal('10000.00'),
        )
        holding = Holding.objects.create(
            portfolio=portfolio,
            security=self.security,
            quantity=Decimal('5.000000'),
            average_cost=Decimal('150.0000'),
        )
        get_market_regime.return_value = market_regime_payload(REGIME_HIGH_VOLATILITY)
        before_counts = {
            'holdings': Holding.objects.count(),
            'transactions': TradeTransaction.objects.count(),
            'cash_flows': PortfolioCashFlow.objects.count(),
        }

        response = self.client.get(reverse('strategy-selection'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['selected_strategy'], STRATEGY_RISK_OFF)
        self.assertFalse(response.data['allow_new_long'])
        portfolio.refresh_from_db()
        holding.refresh_from_db()
        self.assertEqual(portfolio.available_funds, Decimal('10000.00'))
        self.assertEqual(holding.quantity, Decimal('5.000000'))
        self.assertEqual(Holding.objects.count(), before_counts['holdings'])
        self.assertEqual(TradeTransaction.objects.count(), before_counts['transactions'])
        self.assertEqual(PortfolioCashFlow.objects.count(), before_counts['cash_flows'])
        self.assertTrue(
            {'order', 'transaction', 'sell', 'close_position'}.isdisjoint(response.data)
        )
