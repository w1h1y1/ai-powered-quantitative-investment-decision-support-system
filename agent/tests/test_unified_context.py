from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from backtest.services import BacktestDataError, BacktestInsufficientHistoryError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from market.models import Security, SecurityDailyPrice

from agent.unified_context_service import (
    AGENT_UNIFIED_CONTEXT_VERSION,
    _confirmation_level,
)


TOP_LEVEL_KEYS = (
    'symbol',
    'as_of_date',
    'context_version',
    'security',
    'market_data',
    'technical_analysis',
    'market_regime',
    'market_context',
    'portfolio_context',
    'backtest_context',
    'data_quality',
)


def regime_result(
    symbol='AAPL',
    regime='sideways_range',
    sector='Information Technology',
    sector_benchmark='XLK',
):
    return {
        'symbol': symbol,
        'latest_market_date': '2026-08-14',
        'regime_available': True,
        'regime_unavailable_reason': None,
        'regime': regime,
        'confidence': 'high',
        'confidence_score': 0.75,
        'trend': {'direction': 'mixed', 'score': 0.1, 'adx': 22.5},
        'range': {'choppiness': 50.0},
        'momentum': {'rsi': 55.0, 'macd_histogram': 0.5},
        'volatility': {
            'atr': 2.0,
            'atr_percent': 0.02,
            'realized_volatility_20d': 0.25,
            'volatility_percentile': 0.55,
            'percentile_available': True,
        },
        'market_context': {
            'broad_market': 'SPY',
            'broad_market_context_available': True,
            'broad_market_context_reason': None,
            'spy_regime': 'sideways_range',
            'sector': sector,
            'sector_source': 'symbol_mapping',
            'sector_benchmark': sector_benchmark,
            'sector_context_available': True,
            'sector_context_reason': None,
            'sector_regime': 'bullish_trend',
            'confirmation_score': 0.6,
        },
        'explanation': ['Deterministic regime explanation.'],
    }


def hybrid_backtest_result():
    return {
        'total_return': '12.407411',
        'maximum_drawdown': '8.307625',
        'annualized_volatility': '12.418187',
        'total_fees': '36.000000',
        'executed_order_count': 3,
        'swing_win_rate': '66.666667',
    }


def no_position_summary():
    return {
        'available_liquidity': '10000.00',
        'allocations': [],
    }


class UnifiedAgentContextServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='unified-context-user',
            password='password123',
        )
        self.securities = {
            symbol: Security.objects.create(
                symbol=symbol,
                name=f'{symbol} Security',
                asset_type=Security.AssetType.STOCK,
                exchange='NASDAQ',
                currency='USD',
            )
            for symbol in ('AAPL', 'JPM', 'XOM', 'AMZN', 'UNKNOWN')
        }
        self.benchmark = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NYSE Arca',
            currency='USD',
        )

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

    def build(self, symbol, *, regime=None, portfolio_summary=None):
        security = self.securities[symbol]
        regime = regime or regime_result(
            symbol=symbol,
            sector='Information Technology' if symbol == 'AAPL' else 'Financials' if symbol == 'JPM' else 'Energy' if symbol == 'XOM' else 'Consumer Discretionary' if symbol == 'AMZN' else None,
            sector_benchmark='XLK' if symbol == 'AAPL' else 'XLF' if symbol == 'JPM' else 'XLE' if symbol == 'XOM' else 'XLY' if symbol == 'AMZN' else None,
        )
        with (
            patch('agent.unified_context_service.get_market_regime', return_value=regime),
            patch(
                'agent.unified_context_service.run_market_regime_core_swing_backtest',
                return_value=hybrid_backtest_result(),
            ),
            patch(
                'agent.unified_context_service.get_portfolio_summary',
                return_value=portfolio_summary if portfolio_summary is not None else no_position_summary(),
            ),
        ):
            from agent.unified_context_service import build_unified_agent_context
            return build_unified_agent_context(
                security,
                self.user,
                benchmark=self.benchmark,
            )

    def test_valid_stock_has_full_schema_and_version(self):
        self.seed_prices(self.securities['AAPL'])
        context = self.build('AAPL')

        for key in TOP_LEVEL_KEYS:
            self.assertIn(key, context)
        self.assertEqual(context['symbol'], 'AAPL')
        self.assertEqual(context['context_version'], AGENT_UNIFIED_CONTEXT_VERSION)
        self.assertEqual(context['as_of_date'], '2026-08-14')
        self.assertTrue(context['market_data']['available'])
        self.assertTrue(context['technical_analysis']['available'])
        self.assertIsNotNone(context['technical_analysis']['moving_averages']['ma20'])

    def test_market_regime_reuses_regime_service_result(self):
        self.seed_prices(self.securities['AAPL'])
        bullish_fixture = regime_result('AAPL', 'bullish_trend')
        bullish_fixture['trend']['direction'] = 'bullish'
        context = self.build('AAPL', regime=bullish_fixture)

        self.assertEqual(context['market_regime']['regime'], 'bullish_trend')
        self.assertEqual(context['market_regime']['direction'], 'Bullish')
        self.assertEqual(context['market_context']['broad_market']['regime'], 'sideways_range')

    def test_sector_benchmark_reuses_existing_mapping(self):
        expected = {
            'AAPL': 'XLK',
            'JPM': 'XLF',
            'XOM': 'XLE',
            'AMZN': 'XLY',
        }
        for symbol, benchmark in expected.items():
            with self.subTest(symbol=symbol):
                context = self.build(symbol)
                self.assertEqual(context['security']['sector_benchmark'], benchmark)
                self.assertEqual(context['market_context']['sector']['benchmark'], benchmark)

    def test_no_position_is_not_unavailable(self):
        self.seed_prices(self.securities['AAPL'])
        context = self.build('AAPL', portfolio_summary=no_position_summary())

        self.assertTrue(context['portfolio_context']['available'])
        self.assertFalse(context['portfolio_context']['has_position'])
        self.assertEqual(context['portfolio_context']['quantity'], 0)
        self.assertTrue(context['data_quality']['portfolio_context_available'])

    def test_portfolio_weight_uses_total_portfolio_value(self):
        self.seed_prices(self.securities['AAPL'])
        summary = {
            'available_liquidity': '7500.00',
            'total_asset_value': '10000.00',
            'allocations': [{
                'symbol': 'AAPL',
                'quantity': '1.000000',
                'average_price': '2500.0000',
                'market_value': '2500.00',
                'unrealized_profit_loss': '0.00',
                'allocation_percent': '100.00',
            }],
        }
        context = self.build('AAPL', portfolio_summary=summary)

        self.assertEqual(context['portfolio_context']['portfolio_total_value'], 10000.0)
        self.assertEqual(context['portfolio_context']['portfolio_weight'], 0.25)

    def test_portfolio_weight_with_multiple_holdings(self):
        self.seed_prices(self.securities['AAPL'])
        summary = {
            'available_liquidity': '5000.00',
            'total_asset_value': '10000.00',
            'allocations': [
                {
                    'symbol': 'AAPL',
                    'quantity': '1.000000',
                    'average_price': '2500.0000',
                    'market_value': '2500.00',
                    'unrealized_profit_loss': '0.00',
                    'allocation_percent': '50.00',
                },
                {
                    'symbol': 'MSFT',
                    'quantity': '1.000000',
                    'average_price': '2500.0000',
                    'market_value': '2500.00',
                    'unrealized_profit_loss': '0.00',
                    'allocation_percent': '50.00',
                },
            ],
        }
        context = self.build('AAPL', portfolio_summary=summary)

        self.assertEqual(context['portfolio_context']['portfolio_weight'], 0.25)

    def test_backtest_context_uses_hybrid_engine_summary(self):
        self.seed_prices(self.securities['AAPL'])
        context = self.build('AAPL')

        self.assertTrue(context['backtest_context']['available'])
        self.assertEqual(
            context['backtest_context']['strategy'],
            'Market-Regime Hybrid Strategy (Core + Swing)',
        )
        self.assertEqual(context['backtest_context']['strategy_components'], ['Core', 'Swing'])
        self.assertEqual(context['backtest_context']['benchmark'], 'SPY')
        self.assertEqual(context['backtest_context']['trade_count'], 3)
        self.assertTrue(context['data_quality']['backtest_context_available'])

    def test_risk_off_regime_does_not_mark_backtest_not_applicable(self):
        self.seed_prices(self.securities['AAPL'])
        risk_off_fixture = regime_result('AAPL', 'high_volatility')
        context = self.build('AAPL', regime=risk_off_fixture)

        self.assertTrue(context['backtest_context']['available'])
        self.assertEqual(context['backtest_context']['strategy'], 'Market-Regime Hybrid Strategy (Core + Swing)')

    def test_genuine_backtest_unavailable_keeps_other_modules(self):
        self.seed_prices(self.securities['AAPL'])
        with (
            patch('agent.unified_context_service.get_market_regime', return_value=regime_result()),
            patch(
                'agent.unified_context_service.get_portfolio_summary',
                return_value=no_position_summary(),
            ),
            patch(
                'agent.unified_context_service.run_market_regime_core_swing_backtest',
                side_effect=BacktestInsufficientHistoryError(
                    asset={
                        'symbol': 'AAPL',
                        'available_rows': 10,
                        'first_available_date': '2026-01-01',
                        'last_available_date': '2026-08-14',
                        'upstream_error': None,
                    },
                    benchmark={
                        'symbol': 'SPY',
                        'available_rows': 10,
                        'first_available_date': '2026-01-01',
                        'last_available_date': '2026-08-14',
                        'upstream_error': None,
                    },
                    required_warmup_rows=220,
                    requested_start_date=date(2025, 8, 14),
                    warmup_start_date=date(2024, 8, 14),
                ),
            ),
        ):
            from agent.unified_context_service import build_unified_agent_context
            context = build_unified_agent_context(
                self.securities['AAPL'],
                self.user,
                benchmark=self.benchmark,
            )

        self.assertFalse(context['backtest_context']['available'])
        self.assertEqual(
            context['backtest_context']['unavailable_reason'],
            'Insufficient historical data.',
        )
        self.assertTrue(context['market_regime']['available'])

    def test_partial_failure_does_not_break_other_modules(self):
        self.seed_prices(self.securities['AAPL'])
        with (
            patch('agent.unified_context_service.get_market_regime', return_value=regime_result()),
            patch(
                'agent.unified_context_service.get_portfolio_summary',
                side_effect=RuntimeError('portfolio failed'),
            ),
            patch(
                'agent.unified_context_service.run_market_regime_core_swing_backtest',
                side_effect=BacktestDataError('backtest failed'),
            ),
        ):
            from agent.unified_context_service import build_unified_agent_context
            context = build_unified_agent_context(
                self.securities['AAPL'],
                self.user,
                benchmark=self.benchmark,
            )

        self.assertFalse(context['portfolio_context']['available'])
        self.assertFalse(context['backtest_context']['available'])
        self.assertTrue(context['market_data']['available'])
        self.assertTrue(context['market_regime']['available'])
        self.assertTrue(context['technical_analysis']['available'])
        self.assertFalse(context['data_quality']['portfolio_context_available'])
        self.assertFalse(context['data_quality']['backtest_context_available'])
        self.assertTrue(context['data_quality']['market_regime_available'])

    def test_build_is_deterministic_for_same_state(self):
        self.seed_prices(self.securities['AAPL'])
        first = self.build('AAPL')
        second = self.build('AAPL')
        self.assertEqual(first, second)

    def test_confirmation_level_is_deterministic_for_same_score(self):
        self.assertEqual(_confirmation_level(0.5), 'Neutral')
        self.assertEqual(_confirmation_level(0.5), 'Neutral')
        self.assertEqual(_confirmation_level(0.2), 'Weak')
        self.assertEqual(_confirmation_level(0.7), 'Strong')

    def test_market_data_open_close_derived_facts(self):
        today = date(2026, 8, 14)
        SecurityDailyPrice.objects.create(
            security=self.securities['AAPL'],
            date=today,
            open=Decimal('363.00'),
            high=Decimal('364.00'),
            low=Decimal('361.00'),
            close=Decimal('362.84'),
            volume=1000,
        )

        context = self.build('AAPL')

        self.assertEqual(context['market_data']['open_to_close_direction'], 'Down')
        self.assertEqual(context['market_data']['open_to_close_change'], -0.16)
        self.assertLess(context['market_data']['open_to_close_change_percent'], 0)

    def test_market_data_open_close_equal_is_flat(self):
        today = date(2026, 8, 14)
        SecurityDailyPrice.objects.create(
            security=self.securities['AAPL'],
            date=today,
            open=Decimal('100.00'),
            high=Decimal('101.00'),
            low=Decimal('99.00'),
            close=Decimal('100.00'),
            volume=1000,
        )

        context = self.build('AAPL')

        self.assertEqual(context['market_data']['open_to_close_direction'], 'Flat')
        self.assertEqual(context['market_data']['open_to_close_change'], 0)

    def test_portfolio_valuation_metadata_is_exposed(self):
        self.seed_prices(self.securities['AAPL'])
        summary = {
            'available_liquidity': '8360.00',
            'total_asset_value': '11113.37',
            'allocations': [{
                'symbol': 'AAPL',
                'quantity': '9.000000',
                'average_price': '309.710000',
                'current_price': '305.930000',
                'current_price_as_of': '2026-08-14',
                'current_price_source': 'database_cache',
                'current_price_is_stale': False,
                'market_value': '2753.370000',
                'unrealized_profit_loss': '-34.060000',
                'allocation_percent': '24.760000',
            }],
        }
        context = self.build('AAPL', portfolio_summary=summary)

        portfolio = context['portfolio_context']
        self.assertEqual(portfolio['valuation_price'], 305.93)
        self.assertEqual(portfolio['valuation_as_of_date'], '2026-08-14')
        self.assertEqual(portfolio['valuation_source'], 'database_cache')
        self.assertAlmostEqual(
            float(portfolio['quantity']) * portfolio['valuation_price'],
            portfolio['market_value'],
            places=2,
        )


class UnifiedAgentContextApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='unified-context-api-user',
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

    @patch('agent.views.build_unified_agent_context')
    def test_valid_symbol_returns_unified_context(self, build):
        build.return_value = {
            'symbol': 'AAPL',
            'as_of_date': '2026-08-14',
            'context_version': AGENT_UNIFIED_CONTEXT_VERSION,
            'security': {},
            'market_data': {},
            'technical_analysis': {},
            'market_regime': {},
            'market_context': {},
            'portfolio_context': {},
            'backtest_context': {},
            'data_quality': {},
        }

        response = self.client.get(reverse('unified-agent-context'), {'symbol': 'AAPL'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['symbol'], 'AAPL')
        self.assertEqual(response.data['context_version'], AGENT_UNIFIED_CONTEXT_VERSION)
        build.assert_called_once()

    def test_invalid_symbol_returns_400(self):
        response = self.client.get(reverse('unified-agent-context'), {'symbol': 'INVALID123'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('symbol', response.data)
