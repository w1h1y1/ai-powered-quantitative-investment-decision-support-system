import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from agent.analysis_schema import ANALYSIS_VERSION
from agent.llm.base import ProviderResult, UnsupportedProviderError
from agent.tests.fakes import (
    FakeProvider,
    SequenceProvider,
    bearish_trend_context,
    deepseek_like_analysis_with_string_limitations,
    mean_reversion_context,
    risk_off_context,
    valid_analysis,
    xom_mean_reversion_context,
)
from agent.investment_agent_service import run_investment_agent


class InvestmentAgentServiceTests(SimpleTestCase):
    def run_with_context(self, context, provider=None):
        with patch(
            'agent.investment_agent_service.build_agent_context',
            return_value=context,
        ) as build:
            response = run_investment_agent(object(), provider=provider)
        return response, build

    def test_successful_analysis_with_fake_provider(self):
        context = mean_reversion_context()
        response, build = self.run_with_context(
            context,
            provider=FakeProvider(analysis=valid_analysis()),
        )

        self.assertTrue(response['llm_available'])
        self.assertTrue(response['analysis_available'])
        self.assertIsNone(response['failure_reason'])
        self.assertEqual(response['provider'], 'fake')
        self.assertEqual(response['model'], 'fake-model')
        self.assertEqual(response['symbol'], 'JPM')
        self.assertEqual(response['analysis']['analysis_version'], ANALYSIS_VERSION)
        self.assertEqual(response['analysis']['market_summary'], valid_analysis()['market_summary'])
        self.assertEqual(response['context_summary']['symbol'], 'JPM')
        build.assert_called_once()

    def test_provider_can_be_replaced_without_business_changes(self):
        first, _ = self.run_with_context(
            risk_off_context(),
            provider=FakeProvider(analysis=valid_analysis(), configured=True),
        )
        second, _ = self.run_with_context(
            risk_off_context(),
            provider=FakeProvider(analysis=valid_analysis(), configured=True),
        )

        self.assertTrue(first['analysis_available'])
        self.assertTrue(second['analysis_available'])
        self.assertEqual(first['analysis'], second['analysis'])

    def test_factory_is_not_used_when_provider_is_injected(self):
        with patch(
            'agent.investment_agent_service.get_llm_provider',
            side_effect=AssertionError('factory must not be called'),
        ):
            response, _ = self.run_with_context(
                risk_off_context(),
                provider=FakeProvider(analysis=valid_analysis()),
            )
        self.assertTrue(response['analysis_available'])

    def test_missing_key_falls_back_without_breaking_context(self):
        response, _ = self.run_with_context(
            risk_off_context(),
            provider=FakeProvider(analysis=valid_analysis(), configured=False),
        )

        self.assertFalse(response['llm_available'])
        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'api_key_missing')
        self.assertIsNone(response['analysis'])
        self.assertEqual(response['context_summary']['symbol'], 'AAPL')
        self.assertTrue(
            response['context_summary']['strategy_selection']['risk_off'],
        )

    def test_llm_failure_matrix_preserves_reason_and_context(self):
        for reason in (
            'timeout',
            'rate_limited',
            'http_5xx',
            'network_error',
            'invalid_json',
            'invalid_response',
        ):
            with self.subTest(reason=reason):
                response, _ = self.run_with_context(
                    risk_off_context(),
                    provider=FakeProvider(failure_reason=reason),
                )
                self.assertFalse(response['analysis_available'])
                self.assertEqual(response['failure_reason'], reason)
                self.assertIsNone(response['analysis'])
                self.assertEqual(response['context_summary']['symbol'], 'AAPL')

    def test_missing_field_is_schema_invalid(self):
        analysis = valid_analysis()
        del analysis['market_summary']
        response, _ = self.run_with_context(
            mean_reversion_context(),
            provider=FakeProvider(analysis=analysis),
        )
        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'schema_invalid')

    def test_wrong_type_is_schema_invalid(self):
        analysis = valid_analysis()
        analysis['key_reasons'] = 'not a list'
        response, _ = self.run_with_context(
            mean_reversion_context(),
            provider=FakeProvider(analysis=analysis),
        )
        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'schema_invalid')

    def test_empty_analysis_is_invalid_response(self):
        response, _ = self.run_with_context(
            mean_reversion_context(),
            provider=FakeProvider(analysis=None),
        )
        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'invalid_response')

    def test_unsupported_provider_falls_back(self):
        with patch(
            'agent.investment_agent_service.get_llm_provider',
            side_effect=UnsupportedProviderError('unsupported'),
        ):
            with patch(
                'agent.investment_agent_service.build_agent_context',
                return_value=risk_off_context(),
            ):
                response = run_investment_agent(object())

        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'unsupported_provider')
        self.assertEqual(response['context_summary']['symbol'], 'AAPL')

    def test_unsupported_provider_through_real_factory(self):
        with self.settings(LLM_PROVIDER='openai'):
            with patch(
                'agent.investment_agent_service.build_agent_context',
                return_value=risk_off_context(),
            ):
                response = run_investment_agent(object())

        self.assertEqual(response['failure_reason'], 'unsupported_provider')

    def test_metrics_in_context_summary_are_not_modified(self):
        context = mean_reversion_context()
        response, _ = self.run_with_context(
            context,
            provider=FakeProvider(analysis=valid_analysis()),
        )
        summary_metrics = response['context_summary']['strategy_evaluation']['metrics']
        self.assertEqual(summary_metrics, context['strategy_evaluation']['metrics'])
        self.assertEqual(summary_metrics['total_return'], '0.562230')

    def test_response_never_contains_api_key(self):
        response, _ = self.run_with_context(
            risk_off_context(),
            provider=FakeProvider(analysis=valid_analysis(), configured=True),
        )
        dumped = json.dumps(response)
        self.assertNotIn('DEEPSEEK_API_KEY', dumped)
        self.assertNotIn('Authorization', dumped)
        self.assertNotIn('api_key', dumped)

    def test_aapl_risk_off_structured_response_passes(self):
        response, _ = self.run_with_context(
            risk_off_context(),
            provider=FakeProvider(analysis=valid_analysis()),
        )
        self.assertTrue(response['analysis_available'])
        self.assertEqual(response['context_summary']['market_regime']['regime'], 'high_volatility')
        self.assertEqual(response['context_summary']['strategy_evaluation']['status'], 'not_applicable')

    def test_jpm_mean_reversion_structured_response_passes(self):
        response, _ = self.run_with_context(
            mean_reversion_context(),
            provider=FakeProvider(analysis=valid_analysis()),
        )
        self.assertTrue(response['analysis_available'])
        self.assertEqual(response['context_summary']['strategy_evaluation']['evaluation_strategy'], 'mean_reversion')
        self.assertEqual(
            response['context_summary']['strategy_evaluation']['metrics']['total_return'],
            '0.562230',
        )

    def test_xom_mean_reversion_equivalent_path_passes(self):
        response, _ = self.run_with_context(
            xom_mean_reversion_context(),
            provider=FakeProvider(analysis=valid_analysis()),
        )
        self.assertTrue(response['analysis_available'])
        self.assertEqual(response['symbol'], 'XOM')
        self.assertEqual(response['context_summary']['strategy_selection']['selected_strategy'], 'mean_reversion')

    def test_real_deepseek_shape_recovers_with_one_schema_repair_retry(self):
        provider = SequenceProvider(
            ProviderResult(analysis=deepseek_like_analysis_with_string_limitations()),
            ProviderResult(analysis=valid_analysis()),
        )
        response, _ = self.run_with_context(mean_reversion_context(), provider=provider)

        self.assertTrue(response['analysis_available'])
        self.assertIsNone(response['failure_reason'])
        self.assertEqual(len(provider.calls), 2)
        self.assertIn('Correction required', provider.calls[1]['user'])
        self.assertIn("field 'limitations' has type str, expected array of strings", provider.calls[1]['user'])

    def test_schema_repair_retry_never_exceeds_one(self):
        provider = SequenceProvider(
            ProviderResult(analysis=deepseek_like_analysis_with_string_limitations()),
            ProviderResult(analysis=deepseek_like_analysis_with_string_limitations()),
        )
        response, _ = self.run_with_context(mean_reversion_context(), provider=provider)

        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'schema_invalid')
        self.assertEqual(len(provider.calls), 2)

    def test_schema_repair_second_call_failure_uses_that_reason(self):
        provider = SequenceProvider(
            ProviderResult(analysis=deepseek_like_analysis_with_string_limitations()),
            ProviderResult(failure_reason='timeout'),
        )
        response, _ = self.run_with_context(mean_reversion_context(), provider=provider)

        self.assertFalse(response['analysis_available'])
        self.assertEqual(response['failure_reason'], 'timeout')
        self.assertEqual(len(provider.calls), 2)

    def test_percentage_points_value_is_kept_with_its_unit_in_prompt(self):
        context = mean_reversion_context()
        response, _ = self.run_with_context(
            context,
            provider=FakeProvider(analysis=valid_analysis()),
        )
        summary = response['context_summary']['strategy_evaluation']
        self.assertEqual(summary['metrics']['total_return'], '0.562230')
        self.assertEqual(summary['units']['total_return'], 'percentage_points')

        provider = FakeProvider(analysis=valid_analysis())
        with patch(
            'agent.investment_agent_service.build_agent_context',
            return_value=context,
        ):
            run_investment_agent(object(), provider=provider)
        prompt_text = provider.last_prompt['user']
        self.assertIn('"total_return": "0.562230"', prompt_text)
        self.assertIn('percentage_points', prompt_text)
        self.assertNotIn('"total_return": "56.223', prompt_text)

    def test_analysis_response_contains_no_numeric_fields(self):
        response, _ = self.run_with_context(
            mean_reversion_context(),
            provider=FakeProvider(analysis=valid_analysis()),
        )
        analysis = response['analysis']
        for field, value in analysis.items():
            if field == 'analysis_version':
                self.assertIsInstance(value, str)
            elif field in ('key_reasons', 'risk_factors', 'limitations'):
                self.assertIsInstance(value, list)
            else:
                self.assertIsInstance(value, str)
