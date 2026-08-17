from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from backtest.services import DailyBacktestBar

from .models import Security
from .regime_config import (
    HIGH_VOLATILITY_PERCENTILE_THRESHOLD,
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
    TREND_DIRECTION_BEARISH,
    TREND_DIRECTION_BULLISH,
    TREND_DIRECTION_MIXED,
    get_security_sector,
    get_sector_benchmark,
    normalize_sector_name,
)
from .regime_indicators import (
    calculate_adx,
    calculate_choppiness_index,
)
from .regime_service import (
    MarketRegimeDataLoader,
    _relative_strength,
    classify_core_regime,
    compute_core_regime,
    determine_trend_direction,
    get_market_regime,
)
from .serializers import MarketRegimeQuerySerializer


def make_bars(count=320, *, daily_change=Decimal('0.0015')):
    bars = []
    close = Decimal('100')
    start = date(2025, 1, 1)
    for index in range(count):
        close *= Decimal('1') + daily_change
        bars.append(DailyBacktestBar(
            date=start + timedelta(days=index),
            open=close * Decimal('0.999'),
            high=close * Decimal('1.004'),
            low=close * Decimal('0.996'),
            close=close,
        ))
    return tuple(bars)


def core_result(regime=REGIME_BULLISH):
    return {
        'regime_available': True,
        'regime_unavailable_reason': None,
        'regime': regime,
        'confidence': 'high',
        'confidence_score': 0.8,
        'trend': {'direction': TREND_DIRECTION_BULLISH, 'score': 0.8},
        'range': {'score': 0.1},
        'momentum': {'score': 0.6, 'return_20d': 0.10, 'return_60d': 0.30},
        'volatility': {'score': 0.4},
        'explanation': ['Deterministic core explanation.'],
    }


class MarketRegimeRuleTests(SimpleTestCase):
    def test_full_indicator_pipeline_classifies_rising_history_as_bullish(self):
        result = compute_core_regime(make_bars(daily_change=Decimal('0.0015')))
        self.assertTrue(result['regime_available'])
        self.assertEqual(result['regime'], REGIME_BULLISH)
        self.assertEqual(result['trend']['direction'], TREND_DIRECTION_BULLISH)
        self.assertGreater(result['trend']['score'], 0)
        self.assertGreaterEqual(result['trend']['adx'], 25)
        self.assertGreater(result['momentum']['score'], 0)
        self.assertTrue({
            'score', 'strength_score', 'price_vs_ma20', 'ma20_vs_ma60',
            'price_vs_ma200', 'ma20_slope', 'ma60_slope', 'adx',
        }.issubset(result['trend']))

    def test_full_indicator_pipeline_classifies_falling_history_as_bearish(self):
        result = compute_core_regime(make_bars(daily_change=Decimal('-0.0015')))
        self.assertTrue(result['regime_available'])
        self.assertEqual(result['regime'], REGIME_BEARISH)
        self.assertEqual(result['trend']['direction'], TREND_DIRECTION_BEARISH)
        self.assertLess(result['trend']['score'], 0)
        self.assertGreaterEqual(result['trend']['adx'], 25)
        self.assertLess(result['momentum']['score'], 0)

    def test_full_indicator_pipeline_classifies_flat_history_as_sideways(self):
        result = compute_core_regime(make_bars(daily_change=Decimal('0')))
        self.assertTrue(result['regime_available'])
        self.assertEqual(result['regime'], REGIME_SIDEWAYS)
        self.assertEqual(result['trend']['direction'], TREND_DIRECTION_MIXED)
        self.assertAlmostEqual(result['trend']['score'], 0.0)
        self.assertLess(result['trend']['adx'], 20)

    def test_mixed_trend_components_return_mixed_direction(self):
        direction = determine_trend_direction(
            {
                'price_vs_ma20': -0.045344,
                'ma20_vs_ma60': 0.034787,
                'price_vs_ma200': 0.089268,
                'ma20_slope': -0.011464,
                'ma60_slope': 0.002385,
            },
            trend_score=-0.018106,
        )

        self.assertEqual(direction, TREND_DIRECTION_MIXED)

    def test_direction_reuses_existing_trend_threshold_for_near_neutral_consensus(self):
        direction = determine_trend_direction(
            {
                'price_vs_ma20': 0.001,
                'ma20_vs_ma60': 0.001,
                'price_vs_ma200': 0.001,
                'ma20_slope': 0.001,
                'ma60_slope': 0.001,
            },
            trend_score=0.05,
        )

        self.assertEqual(direction, TREND_DIRECTION_MIXED)

    def test_clear_bullish_trend(self):
        regime = classify_core_regime(
            trend_score=0.80,
            adx=32.0,
            choppiness=39.0,
            momentum_score=0.60,
            volatility_percentile_value=0.50,
        )
        self.assertEqual(regime, REGIME_BULLISH)

    def test_clear_bearish_trend(self):
        regime = classify_core_regime(
            trend_score=-0.82,
            adx=35.0,
            choppiness=38.0,
            momentum_score=-0.65,
            volatility_percentile_value=0.55,
        )
        self.assertEqual(regime, REGIME_BEARISH)

    def test_sideways_range(self):
        regime = classify_core_regime(
            trend_score=0.04,
            adx=15.0,
            choppiness=64.0,
            momentum_score=0.02,
            volatility_percentile_value=0.45,
        )
        self.assertEqual(regime, REGIME_SIDEWAYS)

    def test_high_volatility_has_priority_over_positive_trend(self):
        regime = classify_core_regime(
            trend_score=0.90,
            adx=40.0,
            choppiness=32.0,
            momentum_score=0.80,
            volatility_percentile_value=HIGH_VOLATILITY_PERCENTILE_THRESHOLD + 0.01,
        )
        self.assertEqual(regime, REGIME_HIGH_VOLATILITY)

    def test_sector_aliases_map_to_dynamic_sector_etfs_not_qqq(self):
        expectations = {
            'Technology': 'XLK',
            'Information Technology': 'XLK',
            'Financials': 'XLF',
            'Financial Services': 'XLF',
            'Energy': 'XLE',
            'Health Care': 'XLV',
            'Healthcare': 'XLV',
        }
        for sector, expected_etf in expectations.items():
            with self.subTest(sector=sector):
                self.assertIsNotNone(normalize_sector_name(sector))
                self.assertEqual(get_sector_benchmark(sector), expected_etf)
                self.assertNotEqual(expected_etf, 'QQQ')

    def test_existing_symbol_mapping_covers_jpm_and_xom(self):
        jpm_sector, jpm_source = get_security_sector(SimpleNamespace(symbol='JPM'))
        xom_sector, xom_source = get_security_sector(SimpleNamespace(symbol='XOM'))

        self.assertEqual(jpm_sector, 'Financials')
        self.assertEqual(jpm_source, 'symbol_mapping')
        self.assertEqual(get_sector_benchmark(jpm_sector), 'XLF')
        self.assertEqual(xom_sector, 'Energy')
        self.assertEqual(xom_source, 'symbol_mapping')
        self.assertEqual(get_sector_benchmark(xom_sector), 'XLE')

    def test_relative_strength_is_stock_return_minus_benchmark_return(self):
        start = date(2026, 1, 1)
        spy = list(make_bars(61, daily_change=Decimal('0')))
        sector = list(make_bars(61, daily_change=Decimal('0')))
        spy[0] = spy[0].__class__(start, Decimal('92.857143'), Decimal('92.857143'), Decimal('92.857143'), Decimal('92.857143'))
        spy[40] = spy[40].__class__(start + timedelta(days=40), Decimal('100'), Decimal('100'), Decimal('100'), Decimal('100'))
        spy[60] = spy[60].__class__(start + timedelta(days=60), Decimal('104'), Decimal('104'), Decimal('104'), Decimal('104'))
        sector[0] = sector[0].__class__(start, Decimal('89.830508'), Decimal('89.830508'), Decimal('89.830508'), Decimal('89.830508'))
        sector[40] = sector[40].__class__(start + timedelta(days=40), Decimal('100'), Decimal('100'), Decimal('100'), Decimal('100'))
        sector[60] = sector[60].__class__(start + timedelta(days=60), Decimal('106'), Decimal('106'), Decimal('106'), Decimal('106'))
        as_of = start + timedelta(days=60)
        stock_core = core_result()

        result = _relative_strength(stock_core, tuple(spy), tuple(sector), as_of)

        self.assertAlmostEqual(result['vs_spy_20d'], 0.06, places=6)
        self.assertAlmostEqual(result['vs_spy_60d'], 0.18, places=6)
        self.assertAlmostEqual(result['vs_sector_20d'], 0.04, places=6)
        self.assertAlmostEqual(result['vs_sector_60d'], 0.12, places=6)

    def test_trailing_indicators_are_prefix_invariant(self):
        prefix = make_bars(240)
        extended = (*prefix, *make_bars(30, daily_change=Decimal('-0.002')))
        self.assertEqual(calculate_adx(prefix)[-1], calculate_adx(extended)[len(prefix) - 1])
        self.assertEqual(
            calculate_choppiness_index(prefix)[-1],
            calculate_choppiness_index(extended)[len(prefix) - 1],
        )

    def test_insufficient_history_returns_availability_state(self):
        result = compute_core_regime(make_bars(120))
        self.assertFalse(result['regime_available'])
        self.assertIsNone(result['regime'])
        self.assertEqual(result['regime_unavailable_reason'], 'insufficient_history')
        self.assertIsNone(result['trend']['direction'])
        self.assertIsNone(result['volatility']['volatility_percentile'])


class MarketRegimeContextTests(TestCase):
    def setUp(self):
        self.stock = Security.objects.create(
            symbol='ZZZZ',
            name='Unmapped Stock',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )
        self.spy = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            mic_code='ARCX',
        )

    @patch('market.regime_service.compute_core_regime', side_effect=lambda bars: core_result())
    def test_missing_sector_degrades_gracefully_while_spy_context_remains(self, _compute):
        bars = make_bars(61, daily_change=Decimal('0.001'))

        class FakeLoader:
            def __init__(self):
                self.calls = []

            def load(inner_self, security):
                inner_self.calls.append(security.symbol)
                return bars, {'symbol': security.symbol, 'record_count': len(bars)}

        loader = FakeLoader()
        result = get_market_regime(self.stock, loader=loader)

        self.assertTrue(result['regime_available'])
        self.assertEqual(result['regime'], REGIME_BULLISH)
        self.assertTrue(result['market_context']['broad_market_context_available'])
        self.assertFalse(result['sector_context_available'])
        self.assertEqual(result['sector_context_reason'], 'sector_metadata_unavailable')
        self.assertIsNone(result['sector_benchmark'])
        self.assertEqual(loader.calls, ['ZZZZ', 'SPY'])

    @patch('market.regime_service.compute_core_regime', side_effect=lambda bars: core_result())
    def test_stock_spy_and_dynamic_sector_are_each_loaded_once_without_recursion(self, compute):
        stock = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )
        bars = make_bars(320)

        class FakeLoader:
            def __init__(self):
                self.calls = []

            def load(inner_self, security):
                inner_self.calls.append(security.symbol)
                return bars, {'symbol': security.symbol, 'record_count': len(bars)}

        loader = FakeLoader()
        result = get_market_regime(stock, loader=loader)

        self.assertTrue(result['regime_available'])
        self.assertEqual(result['sector_benchmark'], 'XLK')
        self.assertEqual(loader.calls, ['AAPL', 'SPY', 'XLK'])
        self.assertEqual(compute.call_count, 3)
        self.assertFalse(result['engine']['contextual_regime_recursion'])

    @patch('market.regime_service.get_cached_daily_prices', return_value=[])
    @patch('market.regime_service.cache_has_requested_coverage', return_value=True)
    def test_request_loader_reuses_same_symbol_result(self, _coverage, cached_prices):
        loader = MarketRegimeDataLoader()
        first = loader.load(self.stock)
        second = loader.load(self.stock)
        self.assertIs(first, second)
        self.assertEqual(cached_prices.call_count, 2)

    @patch('market.regime_service.fetch_and_cache_daily_prices')
    @patch('market.regime_service.get_cached_daily_prices', return_value=[])
    @patch('market.regime_service.cache_has_requested_coverage', return_value=False)
    def test_request_loader_fetches_provider_only_once_per_symbol(
        self,
        _coverage,
        _cached_prices,
        fetch_prices,
    ):
        loader = MarketRegimeDataLoader()
        loader.load(self.stock)
        loader.load(self.stock)
        self.assertEqual(fetch_prices.call_count, 1)


class MarketRegimeApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='regime-user', password='password123')
        self.client.force_authenticate(self.user)
        self.security = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
        )

    @patch('market.views.get_market_regime')
    def test_market_regime_api_returns_structured_payload(self, regime_service):
        regime_service.return_value = {
            'symbol': 'AAPL',
            'regime_available': True,
            'regime_unavailable_reason': None,
            'regime': REGIME_BULLISH,
            'confidence': 'high',
            'trend': {'direction': TREND_DIRECTION_BULLISH},
            'range': {},
            'momentum': {},
            'volatility': {},
            'relative_strength': {},
            'market_context': {},
            'explanation': [],
        }
        response = self.client.get(reverse('market-regime'), {'symbol': 'aapl'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['regime'], REGIME_BULLISH)
        self.assertEqual(response.data['trend']['direction'], TREND_DIRECTION_BULLISH)
        self.assertEqual(regime_service.call_args.args[0], self.security)
        expected_keys = {
            'symbol', 'regime_available', 'regime', 'confidence', 'trend',
            'range', 'momentum', 'volatility', 'relative_strength',
            'market_context',
        }
        self.assertTrue(expected_keys.issubset(response.data.keys()))

    def test_valid_symbol_resolves_security_outside_validated_query_data(self):
        serializer = MarketRegimeQuerySerializer(data={'symbol': 'aapl'})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(dict(serializer.validated_data), {'symbol': 'AAPL'})
        self.assertEqual(serializer.resolved_security, self.security)

    @patch('market.views.get_market_regime')
    def test_insufficient_data_is_a_200_availability_response_not_server_error(self, regime_service):
        regime_service.return_value = {
            'symbol': 'AAPL',
            'regime_available': False,
            'regime_unavailable_reason': 'insufficient_history',
            'regime': None,
            'confidence': None,
            'trend': {},
            'range': {},
            'momentum': {},
            'volatility': {'volatility_percentile': None},
            'relative_strength': {},
            'market_context': {},
            'explanation': ['Insufficient historical data.'],
        }
        response = self.client.get(reverse('market-regime'), {'symbol': 'AAPL'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['regime_available'])
        self.assertIsNone(response.data['regime'])

    def test_unknown_security_returns_validation_error(self):
        response = self.client.get(reverse('market-regime'), {'symbol': 'MISSING'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Security is not available.', response.data['symbol'])

    def assert_remote_selection_enters_market_regime(
        self,
        *,
        symbol,
        name,
        expected_sector,
        expected_benchmark,
    ):
        item = {
            'id': None,
            'symbol': symbol,
            'name': name,
            'exchange': 'NYSE',
            'mic_code': 'XNYS',
            'instrument_type': 'Common Stock',
            'country': 'United States',
            'currency': 'USD',
            'is_local': False,
            'source': 'remote',
            'is_preferred': True,
        }
        search_payload = {
            'query': symbol,
            'items': [item],
            'metadata': {'count': 1, 'local_count': 0, 'remote_error': ''},
        }
        bars = make_bars(320)

        class FakeLoader:
            def __init__(inner_self):
                inner_self.calls = []

            def load(inner_self, security):
                inner_self.calls.append(security.symbol)
                return bars, {'symbol': security.symbol, 'record_count': len(bars)}

        loader = FakeLoader()
        with (
            patch('market.services.search_security_symbols', return_value=search_payload),
            patch(
                'market.views.get_market_regime',
                side_effect=lambda security: get_market_regime(security, loader=loader),
            ),
        ):
            resolved = self.client.post(
                reverse('security-resolve'),
                {**item, 'search_query': symbol},
                format='json',
            )
            response = self.client.get(reverse('market-regime'), {'symbol': symbol})

        self.assertEqual(resolved.status_code, 201)
        self.assertTrue(resolved.data['created'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['symbol'], symbol)
        self.assertEqual(response.data['market_context']['broad_market'], 'SPY')
        self.assertEqual(response.data['market_context']['sector'], expected_sector)
        self.assertEqual(response.data['market_context']['sector_source'], 'symbol_mapping')
        self.assertEqual(response.data['market_context']['sector_benchmark'], expected_benchmark)
        self.assertEqual(loader.calls, [symbol, 'SPY', expected_benchmark])

    def test_resolved_jpm_is_immediately_available_to_market_regime(self):
        self.assert_remote_selection_enters_market_regime(
            symbol='JPM',
            name='JPMorgan Chase & Co.',
            expected_sector='Financials',
            expected_benchmark='XLF',
        )

    def test_resolved_xom_uses_energy_sector_context(self):
        self.assert_remote_selection_enters_market_regime(
            symbol='XOM',
            name='Exxon Mobil Corporation',
            expected_sector='Energy',
            expected_benchmark='XLE',
        )
