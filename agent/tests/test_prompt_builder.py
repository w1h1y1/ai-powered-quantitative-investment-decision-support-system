import json

from django.test import SimpleTestCase

from agent.prompt_builder import build_llm_payload, build_prompt
from agent.tests.fakes import (
    bearish_trend_context,
    mean_reversion_context,
    risk_off_context,
    unavailable_context,
)

FORBIDDEN_LARGE_FIELDS = ('equity_curve', 'drawdown_curve', 'trades', 'values', 'warmup_values')


def assert_no_large_arrays(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in FORBIDDEN_LARGE_FIELDS, f'forbidden field present: {key}'
            assert_no_large_arrays(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_large_arrays(item)


class PromptBuilderTests(SimpleTestCase):
    def test_payload_prunes_internal_and_debug_fields(self):
        payload = build_llm_payload(mean_reversion_context())

        self.assertNotIn('id', payload['security'])
        self.assertEqual(
            list(payload['security'].keys()),
            ['symbol', 'name', 'exchange', 'currency'],
        )
        self.assertEqual(payload['strategy_evaluation']['data_source'], 'database_cache')
        self.assertNotIn('warmup_debug', payload['strategy_evaluation'])
        self.assertNotIn('provider_error', payload['data_quality']['modules']['market_regime'])
        self.assertNotIn('fetched_from_provider', payload['data_quality']['modules']['market_regime'])
        self.assertNotIn('historical_data_count', payload['data_quality']['modules']['market_regime'])
        assert_no_large_arrays(payload)

    def test_payload_never_contains_large_arrays(self):
        for context in (
            risk_off_context(),
            mean_reversion_context(),
            bearish_trend_context(),
            unavailable_context(),
        ):
            assert_no_large_arrays(build_llm_payload(context))

    def test_risk_off_payload_carries_hard_constraints(self):
        payload = build_llm_payload(risk_off_context())

        self.assertEqual(payload['market_regime']['regime'], 'high_volatility')
        self.assertEqual(payload['strategy_selection']['selected_strategy'], 'risk_off')
        self.assertFalse(payload['strategy_selection']['allow_new_long'])
        self.assertTrue(payload['strategy_selection']['risk_off'])
        self.assertEqual(payload['strategy_evaluation']['status'], 'not_applicable')
        self.assertFalse(payload['strategy_evaluation']['available'])
        self.assertIn(
            'Risk-Off is a defensive state rather than an active trading strategy.',
            payload['strategy_evaluation']['unavailable_reason'],
        )

    def test_mean_reversion_payload_keeps_metrics_and_units(self):
        payload = build_llm_payload(mean_reversion_context())

        evaluation = payload['strategy_evaluation']
        self.assertTrue(evaluation['available'])
        self.assertEqual(evaluation['status'], 'completed')
        self.assertEqual(evaluation['evaluation_strategy'], 'mean_reversion')
        metrics = evaluation['metrics']
        self.assertEqual(metrics['total_return'], '0.562230')
        self.assertEqual(metrics['maximum_drawdown'], '0.086431')
        self.assertEqual(metrics['annualized_volatility'], '0.348989')
        self.assertEqual(metrics['executed_order_count'], 2)
        self.assertEqual(evaluation['units']['total_return'], 'percentage_points')
        self.assertEqual(evaluation['units']['maximum_drawdown'], 'percentage_points')
        self.assertEqual(evaluation['units']['annualized_volatility'], 'percentage_points')
        self.assertEqual(
            payload['technical']['units']['return_20d'],
            'decimal_fraction',
        )

    def test_bearish_trend_facts_are_not_converted_to_risk_off(self):
        payload = build_llm_payload(bearish_trend_context())

        selection = payload['strategy_selection']
        self.assertEqual(payload['market_regime']['regime'], 'bearish_trend')
        self.assertEqual(selection['selected_strategy'], 'trend_following')
        self.assertFalse(selection['risk_off'])
        self.assertFalse(selection['allow_new_long'])
        self.assertEqual(payload['strategy_evaluation']['status'], 'completed')

    def test_unavailable_context_carries_availability_and_reason(self):
        payload = build_llm_payload(unavailable_context())

        market_context = payload['market_context']
        self.assertFalse(market_context['sector_available'])
        self.assertEqual(market_context['sector_reason'], 'sector_metadata_unavailable')
        self.assertIsNone(market_context['sector_regime'])
        self.assertIn('market_context', payload['data_quality']['degraded_modules'])
        self.assertEqual(
            payload['data_quality']['modules']['market_context']['reason'],
            'sector_metadata_unavailable',
        )

    def test_prompt_system_contains_explanation_constraints(self):
        prompt = build_prompt(build_llm_payload(risk_off_context()))
        system = prompt['system']

        self.assertIn('Never output BUY, SELL', system)
        self.assertIn('Never invent numbers', system)
        self.assertIn('percentage_points', system)
        self.assertIn('decimal_fraction', system)
        self.assertIn('allow_new_long', system)
        self.assertIn('risk_off', system)
        self.assertIn('not_applicable', system)
        self.assertIn('exactly these fields', system)
        self.assertIn('market_summary', system)
        self.assertIn('limitations', system)

    def test_prompt_requires_array_of_strings_for_list_fields(self):
        system = build_prompt(build_llm_payload(mean_reversion_context()))['system']

        self.assertIn('MUST each be a JSON array of strings', system)
        self.assertIn('key_reasons', system)
        self.assertIn('risk_factors', system)
        self.assertIn('limitations', system)
        self.assertIn('never a plain string', system)
        self.assertIn('MUST be a JSON string', system)

    def test_prompt_forbids_markdown_code_fences(self):
        system = build_prompt(build_llm_payload(mean_reversion_context()))['system']
        self.assertIn('Do NOT wrap it in Markdown code fences', system)

    def test_prompt_distinguishes_not_applicable_from_unavailable(self):
        system = build_prompt(build_llm_payload(risk_off_context()))['system']
        self.assertIn('not_applicable', system)
        self.assertIn('not an unavailable module', system)
        self.assertIn('not degraded', system)
        self.assertIn('not a failure', system)
        self.assertIn('all_modules_available', system)

    def test_repair_prompt_lists_field_type_problems_without_raw_content(self):
        from agent.prompt_builder import build_repair_prompt

        payload = build_llm_payload(mean_reversion_context())
        repair = build_repair_prompt(payload, {
            'missing_fields': [],
            'wrong_type_fields': [{
                'field': 'limitations',
                'expected_type': 'array of strings',
                'actual_type': 'str',
            }],
        })

        self.assertIn('Correction required', repair['user'])
        self.assertIn("field 'limitations' has type str, expected array of strings", repair['user'])
        self.assertIn('Return the complete corrected JSON object now', repair['user'])
        self.assertEqual(repair['system'], build_prompt(payload)['system'])
        self.assertIn('0.562230', repair['user'])

    def test_prompt_user_embeds_pruned_payload_json(self):
        context = mean_reversion_context()
        prompt = build_prompt(build_llm_payload(context))

        self.assertIn('JPM', prompt['user'])
        self.assertIn('"total_return": "0.562230"', prompt['user'])
        self.assertIn('percentage_points', prompt['user'])
        self.assertNotIn('equity_curve', prompt['user'])
        parsed = json.loads(prompt['user'].split('\n\n', 1)[1])
        self.assertEqual(parsed['symbol'], 'JPM')
