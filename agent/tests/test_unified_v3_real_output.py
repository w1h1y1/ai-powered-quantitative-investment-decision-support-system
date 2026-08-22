from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase

from agent.agent_analysis_service import run_agent_analysis
from agent.llm.base import ProviderResult
from agent.tests.fakes import SequenceProvider
from agent.tests.test_agent_analysis import context_fixture, valid_analysis
from agent.unified_analysis_schema import (
    UnifiedAnalysisValidationError,
    normalize_unified_analysis,
)
from agent.unified_context_service import build_llm_strategy_context


class RealOutputShapeCompatibilityTests(SimpleTestCase):
    def normalize(self, analysis, *, active=False):
        context = build_llm_strategy_context(context_fixture(active=active))
        return normalize_unified_analysis(analysis, context)

    def run_sequence(self, *analyses, active=False):
        provider = SequenceProvider(*[
            ProviderResult(analysis=analysis) for analysis in analyses
        ])
        with patch(
            'agent.agent_analysis_service.build_unified_agent_context',
            return_value=context_fixture(active=active),
        ):
            response = run_agent_analysis(object(), object(), provider=provider)
        return response, provider

    def test_completely_valid_provider_response_succeeds(self):
        normalized = self.normalize(valid_analysis())
        self.assertEqual(normalized['llm_final_strategy_assessment']['selected_strategy'], 'risk_off')

    def test_display_names_and_case_are_canonically_normalized(self):
        data = valid_analysis()
        data['final_market_assessment'].update({
            'regime': 'High Volatility', 'direction': 'Mixed',
        })
        data['strategy_comparison'] = {
            'Trend Following': data['strategy_comparison']['trend_following'],
            'Mean Reversion': data['strategy_comparison']['mean_reversion'],
            'Risk Off': data['strategy_comparison']['risk_off'],
            'No Suitable Strategy': data['strategy_comparison']['no_strategy'],
        }
        for candidate in data['strategy_comparison'].values():
            candidate['suitability'] = candidate['suitability'].replace('_', ' ').title()
        data['final_strategy_assessment']['selected_strategy'] = 'Risk Off'
        data['final_strategy_assessment']['suitability'] = 'High'
        data['risk_assessment']['risk_level'] = 'High'

        normalized = self.normalize(data)

        self.assertEqual(normalized['llm_market_assessment']['regime'], 'high_volatility')
        self.assertEqual(normalized['llm_market_assessment']['direction'], 'mixed')
        self.assertEqual(normalized['llm_final_strategy_assessment']['selected_strategy'], 'risk_off')
        self.assertEqual(
            set(normalized['llm_strategy_comparison']),
            {'trend_following', 'mean_reversion', 'risk_off', 'no_strategy'},
        )

    def test_percentage_string_confidence_is_normalized(self):
        data = valid_analysis()
        data['final_market_assessment']['confidence'] = '69.93%'
        data['final_strategy_assessment']['confidence'] = '74%'
        normalized = self.normalize(data)
        self.assertEqual(normalized['llm_market_assessment']['confidence'], 0.6993)
        self.assertEqual(normalized['llm_final_strategy_assessment']['confidence'], 0.74)

    def test_zero_to_one_numeric_string_confidence_is_normalized(self):
        data = valid_analysis()
        data['final_market_assessment']['confidence'] = '0.6993'
        normalized = self.normalize(data)
        self.assertEqual(normalized['llm_market_assessment']['confidence'], 0.6993)

    def test_zero_to_one_hundred_numeric_confidence_is_normalized(self):
        data = valid_analysis()
        data['final_market_assessment']['confidence'] = 69.93
        data['final_strategy_assessment']['confidence'] = 74
        normalized = self.normalize(data)
        self.assertEqual(normalized['llm_market_assessment']['confidence'], 0.6993)
        self.assertEqual(normalized['llm_final_strategy_assessment']['confidence'], 0.74)

    def test_confidence_above_one_hundred_remains_invalid(self):
        data = valid_analysis()
        data['final_market_assessment']['confidence'] = 150
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            self.normalize(data)
        self.assertEqual(raised.exception.error_code, 'out_of_range')
        self.assertEqual(raised.exception.path, 'llm_market_assessment.confidence')

    def test_evidence_source_path_is_retained_when_exactly_copied(self):
        data = valid_analysis()
        data['supporting_evidence'] = [{
            'factor': 'ADX',
            'source_path': 'technical_analysis.trend.adx',
            'value': 18.4,
            'interpretation': 'The supplied trend-strength value is verified.',
        }]
        normalized = self.normalize(data)
        self.assertEqual(normalized['supporting_evidence'][0]['source_path'], 'technical_analysis.trend.adx')

    def test_empty_allowed_arrays_remain_valid(self):
        data = valid_analysis()
        data['limitations'] = []
        data['strategy_comparison']['no_strategy']['supporting_factors'] = []
        data['strategy_comparison']['no_strategy']['conflicting_factors'] = []
        normalized = self.normalize(data)
        self.assertEqual(normalized['limitations'], [])

    def test_illegal_suitability_is_rejected_with_path(self):
        data = valid_analysis()
        data['strategy_comparison']['risk_off']['suitability'] = 'excellent'
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            self.normalize(data)
        self.assertEqual(raised.exception.error_code, 'invalid_enum')
        self.assertEqual(raised.exception.path, 'llm_strategy_comparison.risk_off.suitability')

    def test_illegal_direction_is_rejected_with_path(self):
        data = valid_analysis()
        data['final_market_assessment']['direction'] = 'upward'
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            self.normalize(data)
        self.assertEqual(raised.exception.error_code, 'invalid_enum')
        self.assertEqual(raised.exception.path, 'llm_market_assessment.direction')

    def test_illegal_strategy_id_is_rejected_with_safe_diagnostic(self):
        data = valid_analysis()
        data['final_strategy_assessment']['selected_strategy'] = 'defensive'
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            self.normalize(data)
        details = raised.exception.safe_details()
        self.assertEqual(details['validation_error_code'], 'invalid_enum')
        self.assertEqual(details['illegal_strategy_id'], 'defensive')

    def test_real_deepseek_string_shape_repairs_once_and_succeeds(self):
        first = deepcopy(valid_analysis())
        first['final_strategy_assessment']['why_not_alternatives'] = (
            'Trend Following and Mean Reversion are prohibited, while No Suitable Strategy ranks lower.'
        )
        response, provider = self.run_sequence(first, valid_analysis())

        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(response['decision_source'], 'llm_synthesis')
        self.assertIsNone(response['fallback_reason'])
        self.assertTrue(response['metadata']['schema_repair_attempted'])
        self.assertTrue(response['metadata']['schema_repair_succeeded'])
        self.assertEqual(len(provider.calls), 2)
        repair_prompt = provider.calls[1]['user']
        self.assertIn('llm_final_strategy_assessment.why_not_alternatives', repair_prompt)
        self.assertIn('array of strings', repair_prompt)

    def test_failed_repair_returns_safe_schema_diagnostics_and_fallback(self):
        invalid = deepcopy(valid_analysis())
        invalid['final_strategy_assessment']['why_not_alternatives'] = 'One combined sentence.'
        response, provider = self.run_sequence(invalid, invalid)

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['decision_source'], 'quantitative_fallback')
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')
        self.assertEqual(response['validation_stage'], 'schema')
        self.assertEqual(response['validation_error_code'], 'invalid_type')
        self.assertEqual(
            response['validation_error_path'],
            'llm_final_strategy_assessment.why_not_alternatives',
        )
        self.assertTrue(response['metadata']['schema_repair_attempted'])
        self.assertFalse(response['metadata']['schema_repair_succeeded'])
        self.assertEqual(len(provider.calls), 2)

    def test_hard_constraint_override_preserves_successful_llm_judgment(self):
        analysis = deepcopy(valid_analysis())
        analysis['strategy_comparison']['trend_following']['suitability'] = 'not_allowed'
        analysis['final_strategy_assessment'].update({
            'selected_strategy': 'trend_following', 'suitability': 'not_allowed',
        })
        response, _ = self.run_sequence(analysis)

        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(response['decision_source'], 'llm_synthesis_with_constraint_override')
        self.assertTrue(response['hard_constraint_override_applied'])
        decision = response['analysis']['validated_system_decision']
        self.assertEqual(decision['llm_selected_strategy'], 'trend_following')
        self.assertEqual(decision['validated_final_strategy'], 'risk_off')
