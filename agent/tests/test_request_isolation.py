"""Request isolation: consecutive symbols never leak data into the next call."""

import json
from unittest.mock import patch

from django.test import SimpleTestCase

from agent.investment_agent_service import run_investment_agent
from agent.prompt_builder import build_llm_payload, build_prompt
from agent.tests.fakes import (
    FakeProvider,
    mean_reversion_context,
    risk_off_context,
    valid_analysis,
    xom_mean_reversion_context,
)


class RequestIsolationTests(SimpleTestCase):
    def test_sequential_llm_payloads_do_not_leak_previous_symbol_data(self):
        contexts = [
            risk_off_context(),       # AAPL high_volatility risk_off
            mean_reversion_context(), # JPM sideways_range mean_reversion
            xom_mean_reversion_context(),  # XOM sideways_range mean_reversion
        ]
        payloads = [build_llm_payload(context) for context in contexts]

        for index, (context, payload) in enumerate(zip(contexts, payloads)):
            text = json.dumps(payload)
            self.assertIn(context['symbol'], text)
            for other_index, other in enumerate(contexts):
                if other_index == index:
                    continue
                self.assertNotIn(other['symbol'], text)

        aapl = json.dumps(payloads[0])
        jpm = json.dumps(payloads[1])
        xom = json.dumps(payloads[2])

        # Regime / strategy / risk / evaluation facts belong to the current symbol.
        self.assertIn('"regime": "high_volatility"', aapl)
        self.assertIn('"selected_strategy": "risk_off"', aapl)
        self.assertIn('"risk_off": true', aapl)
        self.assertNotIn('"selected_strategy": "mean_reversion"', aapl)

        self.assertIn('"regime": "sideways_range"', jpm)
        self.assertIn('"selected_strategy": "mean_reversion"', jpm)
        self.assertIn('"risk_off": false', jpm)
        self.assertNotIn('"risk_off": true', jpm)
        self.assertIn('"total_return": "0.562230"', jpm)

        self.assertIn('"total_return": "0.566941"', xom)
        self.assertIn('"executed_order_count": 2', xom)

    def test_investment_agent_sequential_responses_are_symbol_isolated(self):
        provider = FakeProvider(analysis=valid_analysis())
        with patch(
            'agent.investment_agent_service.build_agent_context',
            side_effect=[risk_off_context(), mean_reversion_context()],
        ):
            first = run_investment_agent(object(), provider=provider)
            second = run_investment_agent(object(), provider=provider)

        self.assertEqual(first['symbol'], 'AAPL')
        self.assertEqual(second['symbol'], 'JPM')
        self.assertTrue(first['analysis_available'])
        self.assertTrue(second['analysis_available'])

        first_summary = json.dumps(first['context_summary'])
        second_summary = json.dumps(second['context_summary'])
        self.assertNotIn('JPM', first_summary)
        self.assertNotIn('AAPL', second_summary)
        self.assertNotIn('0.562230', first_summary)
        self.assertIn('0.562230', second_summary)

    def test_prompt_contains_only_current_symbol_facts(self):
        contexts = [risk_off_context(), mean_reversion_context()]
        prompts = [build_prompt(build_llm_payload(context)) for context in contexts]

        aapl_prompt = prompts[0]['user']
        jpm_prompt = prompts[1]['user']
        self.assertIn('AAPL', aapl_prompt)
        self.assertNotIn('JPM', aapl_prompt)
        self.assertNotIn('0.562230', aapl_prompt)

        self.assertIn('JPM', jpm_prompt)
        self.assertNotIn('AAPL', jpm_prompt)
        self.assertIn('0.562230', jpm_prompt)
        self.assertIn('percentage_points', jpm_prompt)

    def test_repeated_same_symbol_builds_are_stateless_and_deterministic(self):
        context = mean_reversion_context()
        first_payload = build_llm_payload(context)
        second_payload = build_llm_payload(context)
        self.assertEqual(first_payload, second_payload)

        provider = FakeProvider(analysis=valid_analysis())
        with patch(
            'agent.investment_agent_service.build_agent_context',
            return_value=context,
        ):
            run_investment_agent(object(), provider=provider)
            first_prompt = provider.last_prompt
            run_investment_agent(object(), provider=provider)
            second_prompt = provider.last_prompt

        self.assertEqual(first_prompt, second_prompt)
        self.assertIn('JPM', second_prompt['user'])
        self.assertNotIn('AAPL', second_prompt['user'])
