from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security
from market.regime_config import REGIME_HIGH_VOLATILITY
from market.regime_service import (
    MarketRegimeDataRateLimited,
    MarketRegimeDataUnavailable,
)
from market.strategy_selection_service import STRATEGY_RISK_OFF

from agent.agent_context_service import AGENT_CONTEXT_VERSION


def minimal_context():
    return {
        'context_version': AGENT_CONTEXT_VERSION,
        'symbol': 'AAPL',
        'as_of_date': '2026-08-14',
        'security': {
            'id': 1,
            'symbol': 'AAPL',
            'name': 'Apple Inc.',
            'exchange': 'NASDAQ',
            'currency': 'USD',
        },
        'technical': {'latest': {}, 'relative_strength': {}, 'units': {}},
        'market_context': {},
        'market_regime': {'available': True, 'regime': REGIME_HIGH_VOLATILITY},
        'strategy_selection': {
            'available': True,
            'selected_strategy': STRATEGY_RISK_OFF,
            'allow_new_long': False,
            'risk_off': True,
        },
        'strategy_evaluation': {
            'available': False,
            'status': 'not_applicable',
            'metrics': {},
        },
        'data_quality': {
            'all_modules_available': True,
            'degraded_modules': [],
            'as_of_date': '2026-08-14',
            'modules': {},
        },
    }


class AgentContextApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='agent-context-user',
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
        Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSE Arca',
            mic_code='ARCX',
        )

    @patch('agent.views.build_agent_context')
    def test_valid_symbol_returns_deterministic_context(self, build):
        build.return_value = minimal_context()

        response = self.client.post(
            reverse('agent-context'),
            {'symbol': 'aapl'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['context_version'], AGENT_CONTEXT_VERSION)
        self.assertEqual(response.data['symbol'], 'AAPL')
        build.assert_called_once()
        self.assertEqual(build.call_args.args[0], self.security)

    @patch('agent.views.build_agent_context')
    def test_jpm_and_xom_resolve_to_their_own_contexts(self, build):
        jpm = Security.objects.create(
            symbol='JPM',
            name='JPMorgan Chase & Co.',
            asset_type=Security.AssetType.STOCK,
            exchange='NYSE',
            mic_code='XNYS',
        )
        xom = Security.objects.create(
            symbol='XOM',
            name='Exxon Mobil Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NYSE',
            mic_code='XNYS',
        )

        def context_for(security):
            return {
                **minimal_context(),
                'symbol': security.symbol,
                'security': {
                    'id': security.id,
                    'symbol': security.symbol,
                    'name': security.name,
                    'exchange': security.exchange,
                    'currency': 'USD',
                },
            }

        build.side_effect = context_for

        for symbol, expected_security in (('JPM', jpm), ('XOM', xom)):
            with self.subTest(symbol=symbol):
                response = self.client.post(
                    reverse('agent-context'),
                    {'symbol': symbol},
                    format='json',
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['symbol'], symbol)
                self.assertEqual(response.data['security']['symbol'], symbol)
                self.assertEqual(response.data['security']['id'], expected_security.id)
                self.assertEqual(build.call_args.args[0], expected_security)

    def test_missing_symbol_returns_400_without_building(self):
        response = self.client.post(reverse('agent-context'), {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('symbol', response.data)

    def test_invalid_symbol_returns_400_without_building(self):
        response = self.client.post(
            reverse('agent-context'),
            {'symbol': 'UNKNOWN'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('symbol', response.data)
        self.assertIn('Security is not available.', response.data['symbol'][0])

    @patch('agent.views.build_agent_context')
    def test_provider_rate_limit_maps_to_429(self, build):
        build.side_effect = MarketRegimeDataRateLimited('rate limited')

        response = self.client.post(
            reverse('agent-context'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['detail'], 'rate limited')

    @patch('agent.views.build_agent_context')
    def test_provider_unavailable_maps_to_503(self, build):
        build.side_effect = MarketRegimeDataUnavailable('provider unavailable')

        response = self.client.post(
            reverse('agent-context'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['detail'], 'provider unavailable')

    @patch('agent.views.build_agent_context')
    def test_not_applicable_context_remains_http_200(self, build):
        context = minimal_context()
        context['strategy_evaluation']['status'] = 'not_applicable'
        build.return_value = context

        response = self.client.post(
            reverse('agent-context'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['strategy_evaluation']['status'], 'not_applicable')
        self.assertEqual(response.data['data_quality']['all_modules_available'], True)
