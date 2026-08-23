"""P0 end-to-end pipeline integration test.

Verifies:
    Symbol Resolution -> Unified Agent Context -> Agent Analysis

The external LLM provider and quantitative data providers are mocked, but the
real symbol resolution, unified context builder, and analysis orchestration are
executed.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from market.models import Security, SecurityDailyPrice

from agent.agent_analysis_service import run_agent_analysis
from agent.tests.fakes import FakeProvider
from agent.unified_context_service import (
    AGENT_UNIFIED_CONTEXT_VERSION,
    build_unified_agent_context,
)


def valid_analysis(regime='high_volatility', strategy='risk_off'):
    active_allowed = regime != 'high_volatility'
    comparison = {}
    for candidate in ('trend_following', 'mean_reversion', 'risk_off', 'no_strategy'):
        if not active_allowed and candidate in ('trend_following', 'mean_reversion'):
            suitability = 'not_allowed'
        elif candidate == strategy:
            suitability = 'high'
        else:
            suitability = 'low'
        comparison[candidate] = {
            'suitability': suitability,
            'supporting_factors': [],
            'conflicting_factors': [],
        }
    return {
        'final_market_assessment': {
            'regime': regime,
            'direction': 'mixed' if regime == 'high_volatility' else 'neutral',
            'confidence': 0.61,
            'summary': 'The supplied indicators support the final assessment.',
        },
        'strategy_comparison': comparison,
        'final_strategy_assessment': {
            'selected_strategy': strategy,
            'confidence': 0.61,
            'suitability': 'high',
            'reason': 'The selected strategy best matches the supplied evidence.',
            'why_not_alternatives': [
                f'{candidate} ranks below the selected strategy.'
                for candidate in comparison if candidate != strategy
            ],
        },
        'quantitative_agreement': {'agrees_with_backend': True, 'differences': []},
        'risk_assessment': {
            'risk_level': 'high' if regime == 'high_volatility' else 'medium',
            'risk_off': regime == 'high_volatility',
            'allow_new_long': regime != 'high_volatility',
            'summary': 'Backend hard constraints remain authoritative.',
        },
        'hybrid_backtest_evidence_available': True,
        'supporting_evidence': [{
            'factor': 'Market Data Available',
            'source_path': 'market_data.available',
            'value': True,
            'interpretation': 'Current market data is available for independent assessment.',
        }],
        'limitations': ['The Hybrid result does not provide standalone candidate backtests.'],
    }


def regime_fixture(symbol):
    if symbol == 'AAPL':
        return {
            'symbol': 'AAPL',
            'latest_market_date': '2026-08-14',
            'regime_available': True,
            'regime_unavailable_reason': None,
            'regime': 'high_volatility',
            'confidence': 'medium',
            'confidence_score': 0.614625,
            'trend': {'direction': 'mixed', 'score': -0.076689, 'adx': 22.21},
            'range': {'choppiness': 37.59},
            'momentum': {'rsi': 43.67, 'macd_histogram': -2.65},
            'volatility': {
                'atr': 7.86,
                'atr_percent': 0.025695,
                'realized_volatility_20d': 0.332236,
                'volatility_percentile': 0.890873,
                'percentile_available': True,
            },
            'market_context': {
                'broad_market': 'SPY',
                'broad_market_context_available': True,
                'broad_market_context_reason': None,
                'spy_regime': 'sideways_range',
                'sector': 'Information Technology',
                'sector_source': 'symbol_mapping',
                'sector_benchmark': 'XLK',
                'sector_context_available': True,
                'sector_context_reason': None,
                'sector_regime': 'sideways_range',
                'confirmation_score': 0.5,
            },
            'explanation': ['Deterministic regime explanation.'],
        }
    return {
        'symbol': 'JPM',
        'latest_market_date': '2026-08-14',
        'regime_available': True,
        'regime_unavailable_reason': None,
        'regime': 'sideways_range',
        'confidence': 'low',
        'confidence_score': 0.51,
        'trend': {'direction': 'bullish', 'score': 0.12, 'adx': 16.06},
        'range': {'choppiness': 50.0},
        'momentum': {'rsi': 65.16, 'macd_histogram': 0.05},
        'volatility': {
            'atr': 6.33,
            'atr_percent': 0.0175,
            'realized_volatility_20d': 0.1782,
            'volatility_percentile': 0.21,
            'percentile_available': True,
        },
        'market_context': {
            'broad_market': 'SPY',
            'broad_market_context_available': True,
            'broad_market_context_reason': None,
            'spy_regime': 'sideways_range',
            'sector': 'Financials',
            'sector_source': 'symbol_mapping',
            'sector_benchmark': 'XLF',
            'sector_context_available': True,
            'sector_context_reason': None,
            'sector_regime': 'bullish_trend',
            'confirmation_score': 0.5,
        },
        'explanation': ['Deterministic regime explanation.'],
    }


def backtest_fixture(symbol='AAPL'):
    return {
        'security': {'symbol': symbol},
        'strategy_parameters': {'strategy_id': 'market-regime-core-swing'},
        'data_source': {
            'actual_start_date': '2025-08-14',
            'actual_end_date': '2026-08-14',
        },
        'total_return': '12.407411',
        'maximum_drawdown': '8.307625',
        'annualized_volatility': '12.418187',
        'total_fees': '36.000000',
        'executed_order_count': 36,
        'swing_win_rate': '66.666667',
    }


def aapl_portfolio_fixture():
    return {
        'available_liquidity': '7004.40',
        'total_asset_value': '16051.34',
        'allocations': [{
            'symbol': 'AAPL',
            'quantity': '28.000000',
            'average_price': '434.490000',
            'current_price': '305.930000',
            'current_price_as_of': '2026-08-14',
            'current_price_source': 'database_cache',
            'current_price_is_stale': False,
            'market_value': '8566.040000',
            'unrealized_profit_loss': '-3640.370000',
            'allocation_percent': '53.000000',
        }],
    }


def no_position_portfolio_fixture():
    return {
        'available_liquidity': '7004.40',
        'total_asset_value': '16051.34',
        'allocations': [],
    }


class AgentPipelineIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='agent-pipeline-user',
            password='password123',
        )
        self.securities = {
            symbol: Security.objects.create(
                symbol=symbol,
                name=f'{symbol} Security',
                asset_type=Security.AssetType.STOCK if symbol != 'SPY' else Security.AssetType.ETF,
                exchange='NASDAQ' if symbol != 'JPM' else 'NYSE',
                currency='USD',
            )
            for symbol in ('AAPL', 'JPM', 'SPY')
        }
        for security in self.securities.values():
            self.seed_prices(security)

    def seed_prices(self, security):
        first_date = date(2025, 1, 2)
        SecurityDailyPrice.objects.bulk_create([
            SecurityDailyPrice(
                security=security,
                date=first_date + timedelta(days=index),
                open=Decimal('100') + Decimal(index) / Decimal('10'),
                high=Decimal('101') + Decimal(index) / Decimal('10'),
                low=Decimal('99') + Decimal(index) / Decimal('10'),
                close=Decimal('100') + Decimal(index) / Decimal('10'),
                volume=1000000 + index,
            )
            for index in range(240)
        ])

    def patch_context_dependencies(self, symbol):
        return (
            patch(
                'agent.unified_context_service.get_market_regime',
                return_value=regime_fixture(symbol),
            ),
            patch(
                'agent.unified_context_service.run_market_regime_core_swing_backtest',
                return_value=backtest_fixture(symbol),
            ),
            patch(
                'agent.unified_context_service.get_portfolio_summary',
                return_value=(
                    aapl_portfolio_fixture()
                    if symbol == 'AAPL'
                    else no_position_portfolio_fixture()
                ),
            ),
        )

    def test_aapl_pipeline_preserves_symbol_from_resolution_through_analysis(self):
        security = self.securities['AAPL']
        provider = FakeProvider(analysis=valid_analysis())

        patch_regime, patch_backtest, patch_portfolio = self.patch_context_dependencies('AAPL')
        with patch_regime, patch_backtest, patch_portfolio:
            context = build_unified_agent_context(security, self.user)
            response = run_agent_analysis(security, self.user, provider=provider)

        self.assertEqual(context['symbol'], 'AAPL')
        self.assertEqual(context['context_version'], AGENT_UNIFIED_CONTEXT_VERSION)
        self.assertEqual(context['security']['sector'], 'Information Technology')
        self.assertEqual(context['security']['sector_benchmark'], 'XLK')
        self.assertEqual(context['market_regime']['regime'], 'high_volatility')
        self.assertEqual(response['symbol'], 'AAPL')
        self.assertEqual(response['analysis_status'], 'success')
        self.assertIn('AAPL', provider.last_prompt['user'])
        self.assertNotIn('JPM', provider.last_prompt['user'])

    def test_aapl_to_jpm_pipeline_has_no_context_leakage(self):
        aapl_provider = FakeProvider(analysis=valid_analysis())
        jpm_provider = FakeProvider(analysis=valid_analysis('sideways_range', 'mean_reversion'))

        patch_regime, patch_backtest, patch_portfolio = self.patch_context_dependencies('AAPL')
        with patch_regime, patch_backtest, patch_portfolio:
            aapl_context = build_unified_agent_context(
                self.securities['AAPL'],
                self.user,
            )
            run_agent_analysis(
                self.securities['AAPL'],
                self.user,
                provider=aapl_provider,
            )

        patch_regime, patch_backtest, patch_portfolio = self.patch_context_dependencies('JPM')
        with patch_regime, patch_backtest, patch_portfolio:
            jpm_context = build_unified_agent_context(
                self.securities['JPM'],
                self.user,
            )
            jpm_response = run_agent_analysis(
                self.securities['JPM'],
                self.user,
                provider=jpm_provider,
            )

        self.assertEqual(aapl_context['symbol'], 'AAPL')
        self.assertEqual(jpm_context['symbol'], 'JPM')
        self.assertEqual(jpm_response['symbol'], 'JPM')
        self.assertIn('JPM', jpm_provider.last_prompt['user'])
        self.assertNotIn('AAPL', jpm_provider.last_prompt['user'])
        self.assertNotIn('Apple', jpm_provider.last_prompt['user'])
        self.assertIn('Financials', jpm_provider.last_prompt['user'])

    def test_llm_judgment_cannot_override_django_risk_constraints(self):
        conflicting_analysis = valid_analysis('sideways_range', 'trend_following')
        conflicting_analysis['quantitative_agreement'] = {
            'agrees_with_backend': False,
            'differences': ['Final regime and strategy differ from the preliminary assessment.'],
        }
        conflicting_analysis['risk_assessment']['risk_off'] = False
        conflicting_analysis['risk_assessment']['allow_new_long'] = True
        conflicting_analysis['supporting_evidence'] = [{
            'factor': 'ADX',
            'value': 22.21,
            'interpretation': 'Trend strength contributes to the independent comparison.',
        }]
        provider = FakeProvider(analysis=conflicting_analysis)

        patch_regime, patch_backtest, patch_portfolio = self.patch_context_dependencies('AAPL')
        with patch_regime, patch_backtest, patch_portfolio:
            response = run_agent_analysis(
                self.securities['AAPL'],
                self.user,
                provider=provider,
            )

        self.assertEqual(response['analysis_status'], 'success')
        self.assertEqual(response['decision_source'], 'llm_synthesis_with_constraint_override')
        self.assertEqual(response['symbol'], 'AAPL')
        self.assertEqual(
            response['analysis']['validated_system_decision']['validated_final_strategy'],
            'risk_off',
        )
        self.assertEqual(
            response['analysis']['validated_system_decision']['llm_selected_strategy'],
            'trend_following',
        )
        self.assertFalse(response['analysis']['risk_assessment']['allow_new_long'])
        self.assertTrue(response['analysis']['risk_assessment']['risk_off'])
