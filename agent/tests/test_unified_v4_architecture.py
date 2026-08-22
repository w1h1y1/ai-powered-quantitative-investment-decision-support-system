from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase

from agent.agent_analysis_service import run_agent_analysis
from agent.llm.base import ProviderResult
from agent.recommended_action_service import build_recommended_action
from agent.tests.fakes import FakeProvider, SequenceProvider
from agent.tests.test_agent_analysis import context_fixture, trend_analysis, valid_analysis
from agent.unified_analysis_prompt import build_unified_analysis_prompt
from agent.unified_analysis_schema import (
    UnifiedAnalysisValidationError,
    build_quantitative_fallback,
    build_validated_system_analysis,
    normalize_unified_analysis,
)
from agent.unified_context_service import (
    LLM_STRATEGY_CONTEXT_VERSION,
    backend_suggestion_exposed_to_llm,
    build_llm_strategy_context,
)
from market.strategy_catalog import get_strategy_definition


class IndependentContextTests(SimpleTestCase):
    def setUp(self):
        self.backend_context = context_fixture(active=True)
        self.llm_context = build_llm_strategy_context(self.backend_context)

    def test_llm_context_excludes_backend_opinions_and_rankings(self):
        prompt = build_unified_analysis_prompt(self.llm_context)
        user = prompt['user']
        self.assertEqual(self.llm_context['llm_context_version'], LLM_STRATEGY_CONTEXT_VERSION)
        self.assertNotIn('suggested_strategy', user)
        self.assertNotIn('preliminary_regime', user)
        self.assertNotIn('quantitative_assessment', user)
        self.assertNotIn('quantitative_agreement', user)
        self.assertNotIn('preliminary_selection_rationale', user)
        self.assertFalse(backend_suggestion_exposed_to_llm(self.llm_context))

    def test_strategy_catalog_exposes_only_neutral_guidance(self):
        for strategy in self.llm_context['available_strategies']:
            self.assertNotIn('preliminary_selection_rationale', strategy)
            if 'general_evaluation_guidance' in strategy:
                self.assertIsInstance(strategy['general_evaluation_guidance'], str)

    def test_prompt_requires_all_candidates_and_structured_source_paths(self):
        system = build_unified_analysis_prompt(self.llm_context)['system']
        for strategy_id in ('trend_following', 'mean_reversion', 'risk_off', 'no_strategy'):
            self.assertIn(strategy_id, system)
        self.assertIn('source_path', system)
        self.assertNotIn('quantitative_agreement:', system)


class EvidenceValidationV4Tests(SimpleTestCase):
    def setUp(self):
        self.context = build_llm_strategy_context(context_fixture(active=True))

    def test_source_path_value_allows_reasonable_float_precision(self):
        data = trend_analysis()
        data['supporting_evidence'] = [{
            'factor': 'ADX', 'source_path': 'technical_analysis.trend.adx',
            'value': 18.4000005,
            'interpretation': 'Trend strength is evaluated from the supplied field.',
        }]
        normalized = normalize_unified_analysis(data, self.context)
        self.assertEqual(normalized['supporting_evidence'][0]['value'], 18.4)

    def test_unverified_value_reports_exact_field_and_source_path(self):
        data = trend_analysis()
        data['supporting_evidence'] = [{
            'factor': 'ADX', 'source_path': 'technical_analysis.trend.adx',
            'value': 123.45, 'interpretation': 'Fabricated value.',
        }]
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            normalize_unified_analysis(data, self.context)
        details = raised.exception.safe_details()
        self.assertEqual(details['validation_stage'], 'evidence')
        self.assertEqual(details['validation_error_code'], 'unverified_numeric_value')
        self.assertEqual(details['validation_error_path'], 'supporting_evidence[0].value')
        self.assertEqual(details['validation_error_value'], 123.45)
        self.assertEqual(details['validation_source_path'], 'technical_analysis.trend.adx')

    def test_indicator_names_dates_versions_and_parameters_are_not_scanned(self):
        data = trend_analysis()
        data['final_market_assessment']['summary'] = (
            'MA20, MA60, MA200, RSI14, MACD(12,26,9), a 20 trading day window, '
            'a 2.5 ATR parameter, 2026-08-14, and context v1 are labels or supplied definitions.'
        )
        normalized = normalize_unified_analysis(data, self.context)
        self.assertIn('MA20', normalized['llm_market_assessment']['summary'])

    def test_mean_reversion_requires_actual_entry_conditions(self):
        context = deepcopy(self.context)
        context.setdefault('technical_analysis', {})['mean_reversion_entry'] = {
            'entry_conditions_met': False,
        }
        data = trend_analysis()
        data['strategy_comparison']['mean_reversion']['suitability'] = 'high'
        data['final_strategy_assessment'].update({
            'selected_strategy': 'mean_reversion', 'suitability': 'high',
        })
        with self.assertRaises(UnifiedAnalysisValidationError) as raised:
            normalize_unified_analysis(data, context)
        self.assertEqual(raised.exception.error_code, 'mean_reversion_entry_not_met')


class DjangoMergeV4Tests(SimpleTestCase):
    def test_django_merge_does_not_call_llm_twice(self):
        backend = context_fixture(active=True)
        provider = SequenceProvider(ProviderResult(analysis=trend_analysis()))
        with patch('agent.agent_analysis_service.build_unified_agent_context', return_value=backend):
            response = run_agent_analysis(object(), object(), provider=provider)
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(len(provider.calls), 1)

    def test_django_computes_regime_and_strategy_agreement_separately(self):
        backend = context_fixture(active=True)
        llm_context = build_llm_strategy_context(backend)
        llm = normalize_unified_analysis(trend_analysis(), llm_context)
        merged = build_validated_system_analysis(backend, llm)
        agreement = merged['quantitative_agreement']
        self.assertTrue(agreement['regime_agreement'])
        self.assertTrue(agreement['strategy_agreement'])
        self.assertTrue(agreement['agrees_with_backend'])

        changed = deepcopy(llm)
        changed['llm_final_strategy_assessment']['selected_strategy'] = 'no_strategy'
        merged = build_validated_system_analysis(backend, changed)
        agreement = merged['quantitative_agreement']
        self.assertTrue(agreement['regime_agreement'])
        self.assertFalse(agreement['strategy_agreement'])
        self.assertEqual(agreement['differences'][0]['field'], 'selected_strategy')

    def test_hard_constraint_override_is_success_and_preserves_ai_choice(self):
        backend = context_fixture(active=False)
        data = trend_analysis()
        with patch('agent.agent_analysis_service.build_unified_agent_context', return_value=backend):
            response = run_agent_analysis(object(), object(), provider=FakeProvider(analysis=data))
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(response['decision_source'], 'llm_synthesis_with_constraint_override')
        decision = response['analysis']['validated_system_decision']
        self.assertEqual(decision['llm_selected_strategy'], 'trend_following')
        self.assertEqual(decision['validated_final_strategy'], 'risk_off')
        self.assertTrue(decision['hard_constraint_override_applied'])

    def test_llm_failure_keeps_safe_quantitative_fallback(self):
        backend = context_fixture(active=False)
        with patch('agent.agent_analysis_service.build_unified_agent_context', return_value=backend):
            response = run_agent_analysis(
                object(), object(), provider=FakeProvider(failure_reason='timeout'),
            )
        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['decision_source'], 'quantitative_fallback')
        self.assertIsNone(response['analysis']['llm_independent_assessment'])
        self.assertTrue(response['analysis']['validated_system_decision']['fallback_used'])

    def test_evidence_failure_response_contains_safe_field_diagnostics(self):
        backend = context_fixture(active=True)
        invalid = trend_analysis()
        invalid['supporting_evidence'] = [{
            'factor': 'ADX', 'source_path': 'technical_analysis.trend.adx',
            'value': 123.45, 'interpretation': 'Fabricated value.',
        }]
        provider = SequenceProvider(
            ProviderResult(analysis=invalid), ProviderResult(analysis=invalid),
        )
        with patch('agent.agent_analysis_service.build_unified_agent_context', return_value=backend):
            response = run_agent_analysis(object(), object(), provider=provider)
        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['validation_stage'], 'evidence')
        self.assertEqual(response['validation_error_code'], 'unverified_numeric_value')
        self.assertEqual(response['validation_error_path'], 'supporting_evidence[0].value')
        self.assertEqual(response['validation_error_value'], 123.45)
        self.assertEqual(response['validation_source_path'], 'technical_analysis.trend.adx')


class RecommendedActionTests(SimpleTestCase):
    def context(self, *, has_position, risk_off=False, allow_new_long=True):
        context = context_fixture(active=not risk_off and allow_new_long)
        context['portfolio_context'] = {
            'available': True,
            'has_position': has_position,
            'quantity': 12 if has_position else 0,
        }
        context['hard_constraints'].update({
            'risk_off': risk_off,
            'allow_new_long': allow_new_long,
        })
        return context

    def test_no_strategy_without_position_waits(self):
        action = build_recommended_action(
            self.context(has_position=False), 'no_strategy',
        )
        self.assertEqual(action['action'], 'wait')
        self.assertEqual(action['label'], 'Wait / No New Entry')
        self.assertEqual(action['position_context'], 'no_position')
        self.assertNotIn('Hold', action['label'])

    def test_no_strategy_with_position_holds_and_monitors(self):
        action = build_recommended_action(
            self.context(has_position=True), 'no_strategy',
        )
        self.assertEqual(action['action'], 'hold_and_monitor')
        self.assertEqual(action['label'], 'Hold and Monitor')
        self.assertEqual(action['suggested_exposure_change'], 'none')

    def test_positive_quantity_is_treated_as_an_existing_position(self):
        context = self.context(has_position=False)
        context['portfolio_context'].pop('has_position')
        context['portfolio_context']['quantity'] = 3.5
        action = build_recommended_action(context, 'no_strategy')
        self.assertEqual(action['action'], 'hold_and_monitor')

    def test_risk_off_without_position_avoids_new_entry(self):
        action = build_recommended_action(
            self.context(has_position=False, risk_off=True, allow_new_long=False),
            'risk_off',
        )
        self.assertEqual(action['action'], 'avoid_new_entry')
        self.assertFalse(action['new_entry_allowed'])

    def test_risk_off_with_position_reduces_risk_without_sizing_order(self):
        action = build_recommended_action(
            self.context(has_position=True, risk_off=True, allow_new_long=False),
            'risk_off',
        )
        self.assertEqual(action['action'], 'reduce_risk')
        self.assertEqual(action['label'], 'Reduce Risk / No New Long')
        self.assertFalse(action['automatic_execution'])
        self.assertNotIn('quantity', action)

    def test_active_strategies_produce_cautious_consider_guidance(self):
        for strategy_id, expected_label in (
            ('trend_following', 'Consider Trend Following'),
            ('mean_reversion', 'Consider Mean Reversion'),
        ):
            with self.subTest(strategy_id=strategy_id):
                action = build_recommended_action(
                    self.context(has_position=False), strategy_id,
                )
                self.assertEqual(action['action'], 'consider_strategy')
                self.assertEqual(action['label'], expected_label)
                self.assertIn('not an order', action['summary'])

    def test_disallow_new_long_never_produces_active_entry_guidance(self):
        action = build_recommended_action(
            self.context(has_position=False, allow_new_long=False),
            'trend_following',
        )
        self.assertEqual(action['action'], 'avoid_new_entry')
        self.assertFalse(action['new_entry_allowed'])

    def test_missing_portfolio_uses_safe_neutral_guidance(self):
        context = context_fixture(active=True)
        context['portfolio_context'] = {
            'available': False,
            'unavailable_reason': 'Portfolio data unavailable.',
        }
        action = build_recommended_action(context, 'no_strategy')
        self.assertEqual(action['action'], 'monitor')
        self.assertEqual(action['position_context'], 'portfolio_unavailable')
        self.assertEqual(action['suggested_exposure_change'], 'none')

    def test_monitoring_triggers_copy_real_catalog_conditions(self):
        action = build_recommended_action(
            self.context(has_position=False), 'no_strategy',
        )
        conditions = {
            item['factor']: item['condition']
            for item in action['monitoring_triggers']
        }
        self.assertEqual(
            conditions['Trend Following'],
            get_strategy_definition('trend_following')['entry_conditions'][0],
        )
        self.assertEqual(
            conditions['Mean Reversion'],
            get_strategy_definition('mean_reversion')['entry_conditions'][0],
        )

    def test_merge_embeds_recommended_action_under_validated_decision(self):
        backend = self.context(has_position=False)
        llm_context = build_llm_strategy_context(backend)
        llm = normalize_unified_analysis(trend_analysis(), llm_context)
        llm['llm_final_strategy_assessment']['selected_strategy'] = 'no_strategy'
        merged = build_validated_system_analysis(backend, llm)
        action = merged['validated_system_decision']['recommended_action']
        self.assertEqual(action['action'], 'wait')

    def test_fallback_is_distinct_from_normal_no_strategy(self):
        backend = self.context(has_position=False)
        backend['quantitative_assessment']['suggested_strategy'] = 'no_strategy'
        fallback = build_quantitative_fallback(backend, 'llm_invalid_json')
        decision = fallback['validated_system_decision']
        self.assertTrue(decision['fallback_used'])
        self.assertEqual(decision['decision_source'], 'quantitative_fallback')
        self.assertEqual(decision['recommended_action']['action'], 'wait')
