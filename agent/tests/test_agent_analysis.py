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


STRATEGY_IDS = ['trend_following', 'mean_reversion', 'risk_off', 'no_strategy']


def context_fixture(*, active=False):
    preliminary_regime = 'bullish_trend' if active else 'high_volatility'
    suggested_strategy = 'trend_following' if active else 'risk_off'
    currently_allowed = STRATEGY_IDS if active else ['risk_off', 'no_strategy']
    return {
        'symbol': 'AAPL',
        'as_of_date': '2026-08-14',
        'context_version': 'agent_context_v2',
        'market_data': {'open_to_close_direction': 'Down'},
        'market_regime': {
            'regime': preliminary_regime,
            'direction': 'Bullish' if active else 'Mixed',
            'volatility': {'volatility_percentile': 0.9},
        },
        'quantitative_assessment': {
            'preliminary_regime': preliminary_regime,
            'suggested_strategy': suggested_strategy,
            'confidence': 0.78,
            'risk_off': not active,
            'allow_new_long': active,
            'explanation': ['Volatility is elevated.', 'Risk control has priority.'],
        },
        'hard_constraints': {
            'allowed_strategies': STRATEGY_IDS,
            'currently_allowed_strategies': currently_allowed,
            'active_strategy_ids': ['trend_following', 'mean_reversion'],
            'allow_new_long': active,
            'risk_off': not active,
            'actual_trading_allowed': False,
        },
        'available_strategies': [
            {
                'id': strategy_id,
                'name': strategy_id.replace('_', ' ').title(),
                'currently_allowed': strategy_id in currently_allowed,
            }
            for strategy_id in STRATEGY_IDS
        ],
        'strategy_evidence': {'backtest_evidence_available': False},
        'evidence_catalog': [
            {'factor': 'ADX', 'value': 18.4, 'source_path': 'technical_analysis.trend.adx'},
            {'factor': 'Volatility Percentile', 'value': 0.9, 'source_path': 'market_regime.volatility.volatility_percentile'},
            {'factor': 'Preliminary Regime', 'value': preliminary_regime, 'source_path': 'quantitative_assessment.preliminary_regime'},
            {'factor': 'Suggested Strategy', 'value': suggested_strategy, 'source_path': 'quantitative_assessment.suggested_strategy'},
        ],
        'data_quality': {
            'market_data_available': True,
            'technical_analysis_available': True,
            'market_regime_available': True,
        },
    }


def valid_analysis(**overrides):
    analysis = {
        'final_market_assessment': {
            'regime': 'high_volatility',
            'direction': 'mixed',
            'confidence': 0.76,
            'summary': 'Volatility dominates otherwise mixed evidence.',
        },
        'strategy_comparison': {
            'trend_following': {
                'suitability': 'not_allowed', 'supporting_factors': [],
                'conflicting_factors': [],
            },
            'mean_reversion': {
                'suitability': 'not_allowed', 'supporting_factors': [],
                'conflicting_factors': [],
            },
            'risk_off': {
                'suitability': 'high',
                'supporting_factors': [{
                    'factor': 'Volatility Percentile', 'value': 0.9,
                    'interpretation': 'Elevated volatility supports the defensive state.',
                }],
                'conflicting_factors': [],
            },
            'no_strategy': {
                'suitability': 'medium', 'supporting_factors': [],
                'conflicting_factors': [],
            },
        },
        'final_strategy_assessment': {
            'selected_strategy': 'risk_off',
            'confidence': 0.74,
            'suitability': 'high',
            'reason': 'Risk control is the most suitable supported state.',
            'why_not_alternatives': [
                'trend_following is prohibited by the hard constraint.',
                'mean_reversion is prohibited by the hard constraint.',
                'no_strategy is less suitable than the explicit defensive state.',
            ],
        },
        'quantitative_agreement': {
            'agrees_with_backend': True,
            'differences': [],
        },
        'risk_assessment': {
            'risk_level': 'high',
            'risk_off': True,
            'allow_new_long': False,
            'summary': 'New long exposure remains disabled.',
        },
        'backtest_evidence_available': False,
        'supporting_evidence': [{
            'factor': 'Volatility Percentile',
            'value': 0.9,
            'interpretation': 'Elevated volatility supports a defensive result.',
        }],
        'limitations': ['Strategy-specific comparison backtests are unavailable.'],
    }
    analysis.update(overrides)
    return analysis


def disagreeing_analysis():
    data = valid_analysis()
    data['final_market_assessment'] = {
        'regime': 'sideways_range',
        'direction': 'neutral',
        'confidence': 0.58,
        'summary': 'Weak trend strength supports a range assessment.',
    }
    data['final_strategy_assessment'] = {
        'selected_strategy': 'mean_reversion',
        'confidence': 0.58,
        'suitability': 'high',
        'reason': 'Mean reversion better fits the weak directional evidence.',
        'why_not_alternatives': [
            'trend_following has weaker support in the supplied evidence.',
            'risk_off is not required by the supplied risk evidence.',
            'no_strategy is unnecessary because evidence supports mean_reversion.',
        ],
    }
    data['strategy_comparison'] = {
        'trend_following': {
            'suitability': 'low', 'supporting_factors': [],
            'conflicting_factors': [{
                'factor': 'ADX', 'value': 18.4,
                'interpretation': 'Weak trend strength conflicts with trend following.',
            }],
        },
        'mean_reversion': {
            'suitability': 'high', 'supporting_factors': [{
                'factor': 'ADX', 'value': 18.4,
                'interpretation': 'Weak trend strength supports range-oriented evaluation.',
            }],
            'conflicting_factors': [],
        },
        'risk_off': {'suitability': 'low', 'supporting_factors': [], 'conflicting_factors': []},
        'no_strategy': {'suitability': 'low', 'supporting_factors': [], 'conflicting_factors': []},
    }
    data['quantitative_agreement'] = {
        'agrees_with_backend': False,
        'differences': ['Final regime is sideways_range rather than high_volatility.'],
    }
    data['supporting_evidence'] = [{
        'factor': 'ADX',
        'value': 18.4,
        'interpretation': 'Weak trend strength supports a range assessment.',
    }]
    data['risk_assessment'] = {
        'risk_level': 'high',
        'risk_off': False,
        'allow_new_long': True,
        'summary': 'The model sees a range, subject to backend risk limits.',
    }
    return data


def trend_analysis():
    data = disagreeing_analysis()
    data['final_market_assessment'] = {
        'regime': 'bullish_trend',
        'direction': 'bullish',
        'confidence': 0.68,
        'summary': 'Directional evidence supports a bullish trend assessment.',
    }
    data['strategy_comparison']['trend_following']['suitability'] = 'high'
    data['strategy_comparison']['trend_following']['conflicting_factors'] = []
    data['strategy_comparison']['trend_following']['supporting_factors'] = [{
        'factor': 'ADX', 'value': 18.4,
        'interpretation': 'The supplied trend factor is included in the comparison.',
    }]
    data['strategy_comparison']['mean_reversion']['suitability'] = 'low'
    data['strategy_comparison']['mean_reversion']['supporting_factors'] = []
    data['final_strategy_assessment'] = {
        'selected_strategy': 'trend_following',
        'confidence': 0.68,
        'suitability': 'high',
        'reason': 'Trend Following has the strongest relative support.',
        'why_not_alternatives': [
            'mean_reversion has weaker relative support.',
            'risk_off is not required by the supplied risk evidence.',
            'no_strategy is unnecessary because an active candidate is supported.',
        ],
    }
    data['quantitative_agreement'] = {'agrees_with_backend': True, 'differences': []}
    return data


def no_strategy_analysis():
    data = trend_analysis()
    for candidate in data['strategy_comparison'].values():
        candidate['suitability'] = 'low'
        candidate['supporting_factors'] = []
        candidate['conflicting_factors'] = []
    data['strategy_comparison']['no_strategy']['suitability'] = 'high'
    data['strategy_comparison']['no_strategy']['supporting_factors'] = [{
        'factor': 'ADX', 'value': 18.4,
        'interpretation': 'The supplied evidence is not decisive across active candidates.',
    }]
    data['final_strategy_assessment'] = {
        'selected_strategy': 'no_strategy',
        'confidence': 0.52,
        'suitability': 'high',
        'reason': 'Conflicting evidence does not justify an active candidate.',
        'why_not_alternatives': [
            'trend_following lacks decisive support.',
            'mean_reversion lacks decisive support.',
            'risk_off is not required by the supplied hard constraints.',
        ],
    }
    data['quantitative_agreement'] = {
        'agrees_with_backend': False,
        'differences': ['Final strategy abstains instead of selecting trend_following.'],
    }
    data['risk_assessment']['allow_new_long'] = False
    return data


class AgentAnalysisServiceTests(SimpleTestCase):
    def run_with_context(self, provider, context=None):
        with patch(
            'agent.agent_analysis_service.build_unified_agent_context',
            return_value=context or context_fixture(),
        ) as build:
            response = run_agent_analysis(object(), object(), provider=provider)
        return response, build

    def test_llm_agrees_with_preliminary_assessment(self):
        response, build = self.run_with_context(FakeProvider(analysis=valid_analysis()))

        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(response['decision_source'], 'llm_synthesis')
        self.assertTrue(response['analysis']['quantitative_agreement']['agrees_with_backend'])
        self.assertEqual(response['analysis']['final_strategy_assessment']['selected_strategy'], 'risk_off')
        self.assertEqual(response['metadata']['analysis_version'], 'investment_agent_analysis_v3')
        build.assert_called_once()

    def test_prompt_requires_independent_comparison_and_hard_constraints(self):
        provider = FakeProvider(analysis=valid_analysis())
        self.run_with_context(provider)

        system = provider.last_prompt['system']
        user = provider.last_prompt['user']
        self.assertIn('opinions to test, never as final answers', system)
        self.assertIn('Evaluate every candidate', system)
        self.assertIn('None of these associations is absolute', system)
        self.assertIn('allow_new_long=false or risk_off=true prohibits active long strategies', system)
        self.assertIn('evidence_catalog', system)
        self.assertIn('"factor": "ADX"', user)

    def test_llm_may_disagree_using_supplied_evidence(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=disagreeing_analysis()), context_fixture(active=True),
        )

        self.assertEqual(response['analysis_status'], 'success')
        analysis = response['analysis']
        self.assertFalse(analysis['quantitative_agreement']['agrees_with_backend'])
        self.assertTrue(analysis['quantitative_agreement']['differences'])
        self.assertEqual(analysis['final_strategy_assessment']['selected_strategy'], 'mean_reversion')
        self.assertEqual(analysis['supporting_evidence'][0]['factor'], 'ADX')

    def test_disagreement_without_differences_falls_back(self):
        data = disagreeing_analysis()
        data['quantitative_agreement']['differences'] = []
        response, _ = self.run_with_context(
            FakeProvider(analysis=data), context_fixture(active=True),
        )

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['decision_source'], 'quantitative_fallback')
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_backend_allow_new_long_false_forces_defensive_fallback(self):
        response, _ = self.run_with_context(FakeProvider(analysis=disagreeing_analysis()))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(
            response['analysis']['final_strategy_assessment']['selected_strategy'],
            'risk_off',
        )
        risk = response['analysis']['risk_assessment']
        self.assertFalse(risk['allow_new_long'])
        self.assertTrue(risk['risk_off'])

    def test_illegal_strategy_falls_back(self):
        data = valid_analysis()
        data['final_strategy_assessment']['selected_strategy'] = 'magic_strategy'
        response, _ = self.run_with_context(FakeProvider(analysis=data))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['analysis']['final_strategy_assessment']['selected_strategy'], 'risk_off')

    def test_invalid_json_falls_back_after_controlled_retry(self):
        provider = SequenceProvider(
            ProviderResult(failure_reason='invalid_json'),
            ProviderResult(failure_reason='invalid_json'),
        )
        response, _ = self.run_with_context(provider)

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_invalid_json')
        self.assertEqual(len(provider.calls), 2)

    def test_missing_required_fields_fall_back(self):
        provider = SequenceProvider(
            ProviderResult(analysis={'final_market_assessment': {}}),
            ProviderResult(analysis={'final_market_assessment': {}}),
        )
        response, _ = self.run_with_context(provider)

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_timeout_uses_quantitative_fallback(self):
        response, _ = self.run_with_context(FakeProvider(failure_reason='timeout'))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['decision_source'], 'quantitative_fallback')
        self.assertEqual(response['fallback_reason'], 'llm_timeout')
        self.assertEqual(response['analysis']['final_market_assessment']['regime'], 'high_volatility')

    def test_fabricated_evidence_value_falls_back(self):
        data = valid_analysis()
        data['supporting_evidence'][0]['value'] = 0.42
        response, _ = self.run_with_context(FakeProvider(analysis=data))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_evidence_validation_failed')

    def test_narrative_number_absent_from_context_falls_back(self):
        data = valid_analysis()
        data['final_market_assessment']['summary'] = 'ADX is 99.9, indicating a strong trend.'
        response, _ = self.run_with_context(FakeProvider(analysis=data))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_evidence_validation_failed')

    def test_extra_schema_field_falls_back(self):
        data = valid_analysis()
        data['trade_action'] = 'none'
        response, _ = self.run_with_context(FakeProvider(analysis=data))

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_forbidden_action_language_falls_back(self):
        data = valid_analysis()
        data['risk_assessment']['summary'] = 'Consider buying after volatility falls.'
        provider = SequenceProvider(
            ProviderResult(analysis=data),
            ProviderResult(analysis=data),
        )
        response, _ = self.run_with_context(provider)

        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertEqual(response['fallback_reason'], 'llm_constraint_violation')

    def test_auth_error_is_key_free(self):
        response, _ = self.run_with_context(FakeProvider(failure_reason='auth_error'))
        self.assertEqual(response['analysis_status'], 'fallback')
        self.assertNotIn('DEEPSEEK_API_KEY', json.dumps(response))
        self.assertNotIn('api_key', json.dumps(response))

    def test_unsupported_provider_uses_fallback(self):
        with patch('agent.agent_analysis_service.get_llm_provider', side_effect=UnsupportedProviderError('bad')):
            with patch('agent.agent_analysis_service.build_unified_agent_context', return_value=context_fixture()):
                response = run_agent_analysis(object(), object())
        self.assertEqual(response['analysis_status'], 'fallback')

    def test_strong_trend_can_select_trend_following(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=trend_analysis()), context_fixture(active=True),
        )
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(
            response['analysis']['final_strategy_assessment']['selected_strategy'],
            'trend_following',
        )

    def test_range_evidence_can_select_mean_reversion(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=disagreeing_analysis()), context_fixture(active=True),
        )
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(
            response['analysis']['final_strategy_assessment']['selected_strategy'],
            'mean_reversion',
        )

    def test_conflicting_evidence_can_select_no_strategy(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=no_strategy_analysis()), context_fixture(active=True),
        )
        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(
            response['analysis']['final_strategy_assessment']['selected_strategy'],
            'no_strategy',
        )

    def test_every_available_candidate_is_preserved_in_comparison(self):
        response, _ = self.run_with_context(
            FakeProvider(analysis=trend_analysis()), context_fixture(active=True),
        )
        self.assertEqual(
            list(response['analysis']['strategy_comparison']), STRATEGY_IDS,
        )

    def test_missing_candidate_comparison_falls_back(self):
        data = trend_analysis()
        data['strategy_comparison'].pop('no_strategy')
        response, _ = self.run_with_context(
            FakeProvider(analysis=data), context_fixture(active=True),
        )
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_confidence_and_suitability_must_match_selected_comparison(self):
        data = trend_analysis()
        data['final_strategy_assessment']['suitability'] = 'medium'
        response, _ = self.run_with_context(
            FakeProvider(analysis=data), context_fixture(active=True),
        )
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_why_not_alternatives_must_cover_all_other_candidates(self):
        data = trend_analysis()
        data['final_strategy_assessment']['why_not_alternatives'] = ['Only one alternative addressed.']
        response, _ = self.run_with_context(
            FakeProvider(analysis=data), context_fixture(active=True),
        )
        self.assertEqual(response['fallback_reason'], 'llm_schema_validation_failed')

    def test_comparable_backtest_flag_cannot_be_fabricated(self):
        data = trend_analysis()
        data['backtest_evidence_available'] = True
        response, _ = self.run_with_context(
            FakeProvider(analysis=data), context_fixture(active=True),
        )
        self.assertEqual(response['fallback_reason'], 'llm_evidence_validation_failed')

    def test_related_hybrid_metrics_cannot_compare_agent_candidates(self):
        context = context_fixture(active=True)
        context['evidence_catalog'].append({
            'factor': 'Hybrid Backtest Total Return', 'value': 12.4,
            'source_path': 'backtest_context.total_return',
        })
        data = trend_analysis()
        data['strategy_comparison']['trend_following']['supporting_factors'] = [{
            'factor': 'Hybrid Backtest Total Return', 'value': 12.4,
            'interpretation': 'The related result is treated as candidate evidence.',
        }]
        response, _ = self.run_with_context(FakeProvider(analysis=data), context)
        self.assertEqual(response['fallback_reason'], 'llm_evidence_validation_failed')

    def test_disallowed_candidate_must_be_marked_not_allowed(self):
        data = valid_analysis()
        data['strategy_comparison']['trend_following']['suitability'] = 'high'
        response, _ = self.run_with_context(FakeProvider(analysis=data))
        self.assertEqual(response['fallback_reason'], 'llm_strategy_not_allowed')


class AgentAnalysisApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='agent-analysis-api-user', password='password123',
        )
        self.client.force_authenticate(self.user)
        self.security = Security.objects.create(
            symbol='AAPL', name='Apple Inc.', asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ', mic_code='XNAS',
        )

    @patch('agent.views.run_agent_analysis')
    def test_valid_symbol_returns_analysis(self, run):
        run.return_value = {
            'symbol': 'AAPL', 'context_version': 'agent_context_v1',
            'analysis_status': 'fallback', 'decision_source': 'quantitative_fallback',
            'analysis': {'final_market_assessment': {}}, 'metadata': {},
        }
        response = self.client.post(reverse('agent-analyze'), {'symbol': 'AAPL'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['analysis_status'], 'fallback')
        run.assert_called_once()

    @patch('agent.views.run_agent_analysis')
    def test_invalid_symbol_rejects_before_llm(self, run):
        response = self.client.post(reverse('agent-analyze'), {'symbol': 'INVALID123'}, format='json')
        self.assertEqual(response.status_code, 400)
        run.assert_not_called()
