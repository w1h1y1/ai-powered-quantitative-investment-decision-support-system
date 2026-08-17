import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security

from agent.agent_analysis_service import run_agent_analysis
from agent.llm.base import ProviderResult, UnsupportedProviderError
from agent.tests.fakes import FakeProvider, SequenceProvider


def context_fixture():
    return {
        'symbol': 'AAPL',
        'as_of_date': '2026-08-14',
        'context_version': 'agent_context_v1',
        'market_data': {'open_to_close_direction': 'Down'},
        'market_regime': {'regime': 'high_volatility', 'direction': 'Mixed'},
        'market_context': {
            'confirmation': {'score': 0.5, 'level': 'Neutral'},
        },
        'portfolio_context': {
            'available': True,
            'has_position': True,
            'portfolio_weight': 0.2372,
        },
        'backtest_context': {'available': True},
    }


def valid_analysis():
    return {
        'market_view': {'summary': 'High volatility with mixed direction.'},
        'technical_view': {'trend': 'Mixed', 'momentum': 'Weak', 'volatility': 'Elevated'},
        'market_context_view': {
            'broad_market': 'Sideways',
            'sector': 'Sideways',
            'confirmation': 'Weak',
        },
        'portfolio_view': {'exposure_comment': 'AAPL is an existing portfolio position.'},
        'backtest_view': {
            'summary': 'Positive historical return with drawdown risk.',
            'strengths': ['Positive return'],
            'risks': ['Historical drawdown'],
        },
        'overall_assessment': 'Elevated volatility dominates the setup.',
        'risk_factors': ['High volatility', 'Weak momentum'],
    }


def action_language_analysis():
    analysis = valid_analysis()
    analysis['portfolio_view']['exposure_comment'] = (
        'There is ample capacity to initiate a position if desired.'
    )
    return analysis


def open_close_contradiction_analysis():
    analysis = valid_analysis()
    analysis['market_view']['summary'] = (
        'The stock closed higher than it opened during the session.'
    )
    return analysis


class AgentAnalysisServiceTests(SimpleTestCase):
    def run_with_context(self, provider, context=None):
        with patch(
            'agent.agent_analysis_service.build_unified_agent_context',
            return_value=context or context_fixture(),
        ) as build:
            response = run_agent_analysis(object(), object(), provider=provider)
        return response, build

    def test_analysis_reuses_unified_context_service(self):
        response, build = self.run_with_context(
            FakeProvider(analysis=valid_analysis()),
        )
        self.assertEqual(response['context_version'], 'agent_context_v1')
        build.assert_called_once()

    def test_successful_structured_analysis(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=valid_analysis()),
        )
        self.assertEqual(response['analysis_status'], 'success')
        self.assertIn('market_view', response['analysis'])
        self.assertIn('technical_view', response['analysis'])
        self.assertIn('market_context_view', response['analysis'])
        self.assertIn('portfolio_view', response['analysis'])
        self.assertIn('backtest_view', response['analysis'])
        self.assertIn('overall_assessment', response['analysis'])
        self.assertIn('risk_factors', response['analysis'])

    def test_django_controls_facts_and_drops_advice_fields(self):
        data = valid_analysis()
        data['market_view']['regime'] = 'bullish_trend'
        data['market_view']['direction'] = 'Bullish'
        data['portfolio_view']['has_position'] = False
        data['backtest_view']['available'] = False
        data['recommendation'] = 'BUY'
        data['trade_action'] = 'Buy now'
        data['target_price'] = 350
        data['position_size'] = '10%'

        response, _ = self.run_with_context(FakeProvider(analysis=data))

        analysis = response['analysis']
        self.assertEqual(analysis['market_view']['regime'], 'high_volatility')
        self.assertEqual(analysis['market_view']['direction'], 'Mixed')
        self.assertTrue(analysis['portfolio_view']['has_position'])
        self.assertTrue(analysis['backtest_view']['available'])
        self.assertNotIn('recommendation', analysis)
        self.assertNotIn('trade_action', analysis)
        self.assertNotIn('target_price', analysis)
        self.assertNotIn('position_size', analysis)

    def test_missing_portfolio_keeps_analysis_success(self):
        context = context_fixture()
        context['portfolio_context'] = {
            'available': False,
            'has_position': False,
            'portfolio_weight': None,
        }
        response, _ = self.run_with_context(
            FakeProvider(analysis=valid_analysis()),
            context=context,
        )
        self.assertEqual(response['analysis_status'], 'success')
        self.assertFalse(response['analysis']['portfolio_view']['has_position'])
        self.assertIsNone(response['analysis']['portfolio_view']['portfolio_weight'])

    def test_missing_backtest_blocks_fabricated_strengths(self):
        context = context_fixture()
        context['backtest_context'] = {'available': False}
        response, _ = self.run_with_context(
            FakeProvider(analysis=valid_analysis()),
            context=context,
        )
        backtest = response['analysis']['backtest_view']
        self.assertFalse(backtest['available'])
        self.assertEqual(backtest['strengths'], [])
        self.assertEqual(backtest['risks'], [])

    def test_confirmation_level_is_django_controlled(self):
        data = valid_analysis()
        data['market_context_view']['confirmation'] = 'moderate alignment'
        data['market_context_view']['confirmation_level'] = 'Strong'

        response, _ = self.run_with_context(FakeProvider(analysis=data))

        self.assertEqual(
            response['analysis']['market_context_view']['confirmation_score'],
            0.5,
        )
        self.assertEqual(
            response['analysis']['market_context_view']['confirmation_level'],
            'Neutral',
        )

    def test_action_language_retries_once_then_succeeds(self):
        provider = SequenceProvider(
            ProviderResult(analysis=action_language_analysis()),
            ProviderResult(analysis=valid_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(len(provider.calls), 2)

    def test_action_language_violation_returns_unavailable(self):
        provider = SequenceProvider(
            ProviderResult(analysis=action_language_analysis()),
            ProviderResult(analysis=action_language_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(
            response['unavailable_reason'],
            'LLM response violated analysis constraints.',
        )

    def test_open_close_contradiction_retries_once_then_succeeds(self):
        provider = SequenceProvider(
            ProviderResult(analysis=open_close_contradiction_analysis()),
            ProviderResult(analysis=valid_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(len(provider.calls), 2)

    def test_open_close_contradiction_returns_unavailable(self):
        provider = SequenceProvider(
            ProviderResult(analysis=open_close_contradiction_analysis()),
            ProviderResult(analysis=open_close_contradiction_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(
            response['unavailable_reason'],
            'LLM response violated analysis constraints.',
        )

    def test_invalid_json_retries_once_then_succeeds(self):
        provider = SequenceProvider(
            ProviderResult(failure_reason='invalid_json'),
            ProviderResult(analysis=valid_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(len(provider.calls), 2)

    def test_invalid_json_retries_exhausted_returns_unavailable(self):
        provider = SequenceProvider(
            ProviderResult(failure_reason='invalid_json'),
            ProviderResult(failure_reason='invalid_json'),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(
            response['unavailable_reason'],
            'LLM returned an invalid structured response.',
        )

    def test_timeout_returns_unavailable(self):
        response, _ = self.run_with_context(
            FakeProvider(failure_reason='timeout'),
        )
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(response['unavailable_reason'], 'LLM request timed out.')

    def test_auth_error_is_controlled_and_key_free(self):
        response, _ = self.run_with_context(
            FakeProvider(failure_reason='auth_error'),
        )
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(
            response['unavailable_reason'],
            'LLM service authentication failed.',
        )
        self.assertNotIn('DEEPSEEK_API_KEY', json.dumps(response))
        self.assertNotIn('api_key', json.dumps(response))

    def test_missing_key_returns_unavailable(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=valid_analysis(), configured=False),
        )
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(response['unavailable_reason'], 'LLM service is not configured.')

    def test_schema_invalid_retries_once(self):
        provider = SequenceProvider(
            ProviderResult(analysis={'market_view': {}}),
            ProviderResult(analysis=valid_analysis()),
        )
        response, _ = self.run_with_context(provider)
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(len(provider.calls), 2)

    def test_facts_are_stable_across_calls(self):
        first, _ = self.run_with_context(FakeProvider(analysis=valid_analysis()))
        second, _ = self.run_with_context(FakeProvider(analysis=valid_analysis()))
        self.assertEqual(first['analysis']['market_view']['regime'], 'high_volatility')
        self.assertEqual(second['analysis']['market_view']['regime'], 'high_volatility')
        self.assertEqual(first['analysis']['portfolio_view']['has_position'], True)
        self.assertEqual(second['analysis']['portfolio_view']['has_position'], True)

    def test_unsupported_provider_returns_unavailable(self):
        with patch(
            'agent.agent_analysis_service.get_llm_provider',
            side_effect=UnsupportedProviderError('unknown provider'),
        ):
            with patch(
                'agent.agent_analysis_service.build_unified_agent_context',
                return_value=context_fixture(),
            ):
                response = run_agent_analysis(object(), object())
        self.assertEqual(response['analysis_status'], 'unavailable')
        self.assertEqual(response['unavailable_reason'], 'LLM service is not configured.')


class AgentAnalysisApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='agent-analysis-api-user',
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

    @patch('agent.views.run_agent_analysis')
    def test_valid_symbol_returns_analysis(self, run):
        run.return_value = {
            'symbol': 'AAPL',
            'context_version': 'agent_context_v1',
            'analysis_status': 'success',
            'analysis': {},
            'metadata': {},
        }
        response = self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['analysis_status'], 'success')
        run.assert_called_once()

    @patch('agent.views.run_agent_analysis')
    def test_invalid_symbol_rejects_before_llm(self, run):
        response = self.client.post(
            reverse('agent-analyze'),
            {'symbol': 'INVALID123'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        run.assert_not_called()
