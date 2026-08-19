from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from agent.models import InvestmentAgentAnalysis


def success_payload(symbol='AAPL', analysis_marker='analysis'):
    return {
        'symbol': symbol,
        'context_version': 'unified_context_v1',
        'analysis_status': 'success',
        'analysis': {
            'overall_assessment': f'Assessment {analysis_marker}',
            'market_view': {'regime': 'high_volatility', 'direction': 'Mixed'},
        },
        'metadata': {
            'provider': 'fake',
            'model': 'fake-model',
            'as_of_date': '2026-08-14',
            'prompt_version': 'agent_analysis_prompt_v1',
            'analysis_version': 'agent_analysis_v1',
        },
    }


def unavailable_payload(symbol='AAPL', reason='LLM request timed out.'):
    return {
        'symbol': symbol,
        'context_version': 'unified_context_v1',
        'analysis_status': 'unavailable',
        'unavailable_reason': reason,
        'analysis': None,
        'metadata': {
            'provider': 'fake',
            'model': 'fake-model',
            'as_of_date': '2026-08-14',
            'analysis_version': 'agent_analysis_v1',
        },
    }


class AgentAnalysisPersistenceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='persist_user_a', password='pass')
        self.user_b = User.objects.create_user(username='persist_user_b', password='pass')
        self.aapl = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )
        self.jpm = Security.objects.create(
            symbol='JPM',
            name='JPMorgan Chase & Co.',
            asset_type=Security.AssetType.STOCK,
            exchange='NYSE',
            mic_code='XNYS',
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    @patch('agent.views.run_agent_analysis')
    def test_successful_generation_persists_record(self, run):
        run.return_value = success_payload(analysis_marker='first')
        self.authenticate(self.user_a)

        response = self.client.post(
            reverse('agent-analyze'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('generated_at'))
        record = InvestmentAgentAnalysis.objects.get(user=self.user_a, security=self.aapl)
        self.assertEqual(record.status, InvestmentAgentAnalysis.Status.SUCCESS)
        self.assertEqual(record.symbol, 'AAPL')
        self.assertEqual(record.analysis['overall_assessment'], 'Assessment first')
        self.assertEqual(record.analysis_version, 'agent_analysis_v1')
        self.assertEqual(record.context_version, 'unified_context_v1')
        self.assertEqual(str(record.as_of_date), '2026-08-14')
        self.assertEqual(record.provider, 'fake')

    @patch('agent.views.run_agent_analysis')
    def test_latest_endpoint_returns_saved_analysis(self, run):
        run.return_value = success_payload(analysis_marker='saved')
        self.authenticate(self.user_a)
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')

        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['available'])
        self.assertEqual(response.data['symbol'], 'AAPL')
        self.assertEqual(response.data['analysis']['overall_assessment'], 'Assessment saved')
        self.assertEqual(response.data['analysis_version'], 'agent_analysis_v1')
        self.assertEqual(response.data['as_of_date'], '2026-08-14')
        self.assertIn('generated_at', response.data)

    def test_latest_without_history_returns_available_false(self):
        self.authenticate(self.user_a)

        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['available'])
        self.assertIsNone(response.data['analysis'])

    @patch('agent.views.run_agent_analysis')
    def test_user_isolation(self, run):
        run.return_value = success_payload()
        self.authenticate(self.user_a)
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')

        self.authenticate(self.user_b)
        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})

        self.assertFalse(response.data['available'])
        self.assertEqual(InvestmentAgentAnalysis.objects.filter(user=self.user_b).count(), 0)

    @patch('agent.views.run_agent_analysis')
    def test_symbol_isolation(self, run):
        self.authenticate(self.user_a)
        run.return_value = success_payload(symbol='AAPL', analysis_marker='aapl-analysis')
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')
        run.return_value = success_payload(symbol='JPM', analysis_marker='jpm-analysis')
        self.client.post(reverse('agent-analyze'), {'symbol': 'JPM'}, format='json')

        aapl = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})
        jpm = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'JPM'})

        self.assertEqual(aapl.data['analysis']['overall_assessment'], 'Assessment aapl-analysis')
        self.assertEqual(jpm.data['analysis']['overall_assessment'], 'Assessment jpm-analysis')
        self.assertNotEqual(
            InvestmentAgentAnalysis.objects.get(user=self.user_a, security=self.aapl).symbol,
            InvestmentAgentAnalysis.objects.get(user=self.user_a, security=self.jpm).symbol,
        )

    @patch('agent.views.run_agent_analysis')
    def test_two_successful_generations_keep_newest(self, run):
        self.authenticate(self.user_a)
        run.return_value = success_payload(analysis_marker='first')
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')
        run.return_value = success_payload(analysis_marker='second')
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')

        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})

        self.assertEqual(response.data['analysis']['overall_assessment'], 'Assessment second')
        self.assertEqual(
            InvestmentAgentAnalysis.objects.filter(user=self.user_a, security=self.aapl).count(),
            1,
        )

    @patch('agent.views.run_agent_analysis')
    def test_failure_after_success_keeps_previous_analysis(self, run):
        self.authenticate(self.user_a)
        run.return_value = success_payload(analysis_marker='old')
        self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')
        run.return_value = unavailable_payload(reason='LLM request timed out.')

        failure = self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')

        self.assertEqual(failure.status_code, status.HTTP_200_OK)
        self.assertEqual(failure.data['analysis_status'], 'unavailable')
        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})
        self.assertTrue(response.data['available'])
        self.assertEqual(response.data['analysis']['overall_assessment'], 'Assessment old')

    @patch('agent.views.run_agent_analysis')
    def test_invalid_response_not_persisted(self, run):
        self.authenticate(self.user_a)
        run.return_value = unavailable_payload(
            reason='LLM returned an invalid structured response.',
        )

        response = self.client.post(
            reverse('agent-analyze'),
            {'symbol': 'AAPL'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            InvestmentAgentAnalysis.objects.filter(user=self.user_a, security=self.aapl).count(),
            0,
        )

    def test_latest_requires_authentication(self):
        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'AAPL'})
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_latest_invalid_symbol_returns_400(self):
        self.authenticate(self.user_a)
        response = self.client.get(reverse('agent-analysis-latest'), {'symbol': 'INVALID123'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
