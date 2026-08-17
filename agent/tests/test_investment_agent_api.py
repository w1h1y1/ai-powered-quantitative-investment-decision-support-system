from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security
from market.regime_service import MarketRegimeDataRateLimited


def success_payload():
    return {
        'symbol': 'AAPL',
        'as_of_date': '2026-08-14',
        'context_version': 'agent_context_v1',
        'context_summary': {'symbol': 'AAPL'},
        'provider': 'deepseek',
        'model': 'deepseek-chat',
        'llm_available': True,
        'analysis_available': True,
        'failure_reason': None,
        'analysis': {
            'analysis_version': 'investment_agent_analysis_v1',
            'market_summary': 'Elevated volatility.',
            'market_regime_summary': 'High volatility.',
            'technical_summary': 'Negative momentum.',
            'market_context_summary': 'Broad market sideways.',
            'historical_evidence_summary': 'Not applicable.',
            'risk_assessment': 'Elevated downside risk.',
            'key_reasons': ['Risk-Off'],
            'risk_factors': ['Volatility'],
            'limitations': ['Evaluation not applicable'],
        },
    }


def fallback_payload(reason):
    payload = success_payload()
    payload.update({
        'llm_available': False,
        'analysis_available': False,
        'failure_reason': reason,
        'analysis': None,
    })
    return payload


class InvestmentAgentApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='investment-agent-user',
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

    @patch('agent.views.run_investment_agent')
    def test_valid_symbol_returns_structured_analysis(self, run):
        run.return_value = success_payload()

        response = self.client.post(
            reverse('investment-agent'),
            {'symbol': 'aapl'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['provider'], 'deepseek')
        self.assertTrue(response.data['llm_available'])
        self.assertTrue(response.data['analysis_available'])
        self.assertEqual(
            response.data['analysis']['analysis_version'],
            'investment_agent_analysis_v1',
        )
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], self.security)

    def test_missing_symbol_returns_400(self):
        response = self.client.post(reverse('investment-agent'), {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('symbol', response.data)

    def test_invalid_symbol_returns_400(self):
        response = self.client.post(
            reverse('investment-agent'),
            {'symbol': 'UNKNOWN'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Security is not available.', response.data['symbol'][0])

    @patch('agent.views.run_investment_agent')
    def test_llm_failure_returns_200_fallback(self, run):
        run.return_value = fallback_payload('timeout')

        response = self.client.post(
            reverse('investment-agent'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['llm_available'])
        self.assertFalse(response.data['analysis_available'])
        self.assertEqual(response.data['failure_reason'], 'timeout')
        self.assertIsNone(response.data['analysis'])

    @patch('agent.views.run_investment_agent')
    def test_context_provider_error_maps_to_429(self, run):
        run.side_effect = MarketRegimeDataRateLimited('rate limited')

        response = self.client.post(
            reverse('investment-agent'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['detail'], 'rate limited')

    @patch('agent.views.run_investment_agent')
    def test_response_never_contains_secret_fields(self, run):
        run.return_value = success_payload()

        response = self.client.post(
            reverse('investment-agent'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertNotIn('DEEPSEEK_API_KEY', response.content.decode('utf-8'))
        self.assertNotIn('Authorization', response.content.decode('utf-8'))
        self.assertNotIn('api_key', response.content.decode('utf-8'))
