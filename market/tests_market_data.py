from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Security, SecurityDailyPrice
from .services import (
    MARKET_DATA_FETCH_START_BUFFER_DAYS,
    MARKET_DATA_INDICATOR_WARMUP_BARS,
    MARKET_DATA_INDICATOR_WARMUP_DAYS,
    MARKET_DATA_QUOTE_SOURCE_CACHED,
    MARKET_DATA_QUOTE_SOURCE_LAST_CLOSE,
    InvalidMarketDataDateRange,
    MarketDataInvalidSymbol,
    MarketDataQuoteResult,
    MarketDataRateLimited,
    MarketDataResult,
    MarketDataUnavailable,
    UnsupportedMarketDataInterval,
    get_market_summary,
    get_market_data_interval,
    get_range_date_window,
    get_latest_complete_market_date,
    get_security_daily_market_data,
    get_security_latest_quote,
    get_security_latest_quotes,
    search_security_symbols,
)
from .twelve_data import (
    TwelveDataClient,
    TwelveDataError,
    TwelveDataIntervalUnavailableError,
    TwelveDataInvalidSymbolError,
    TwelveDataRateLimitError,
    parse_bar,
    parse_quote,
)


@dataclass(frozen=True)
class FakeDailyBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timestamp: str = ''


@dataclass(frozen=True)
class FakeQuote:
    price: Decimal
    change: Decimal
    percent_change: Decimal
    as_of: str


class FakeTwelveDataClient:
    def __init__(
        self,
        bars=None,
        error=None,
        quote=None,
        quote_error=None,
        bars_by_symbol=None,
        errors_by_symbol=None,
        daily_bars=None,
        daily_bars_by_symbol=None,
        symbol_search_results=None,
        symbol_search_error=None,
    ):
        self.bars = bars or []
        self.daily_bars = daily_bars
        self.error = error
        self.quote = quote
        self.quote_error = quote_error
        self.symbol_search_results = symbol_search_results or []
        self.symbol_search_error = symbol_search_error
        self.bars_by_symbol = bars_by_symbol or {}
        self.daily_bars_by_symbol = daily_bars_by_symbol or {}
        self.errors_by_symbol = errors_by_symbol or {}
        self.calls = []
        self.quote_calls = []
        self.symbol_search_calls = []

    def get_time_series(self, symbol, interval, start_date=None, end_date=None, outputsize=None):
        self.calls.append({
            'symbol': symbol,
            'interval': interval,
            'start_date': start_date,
            'end_date': end_date,
            'outputsize': outputsize,
        })
        self.last_response_metadata = {
            'endpoint': 'time_series',
            'http_status': 200,
            'provider_status': 'ok',
            'provider_code': None,
            'provider_message': '',
            'params': {
                'symbol': symbol,
                'interval': interval,
                'start_date': start_date,
                'end_date': end_date,
                'outputsize': outputsize,
            },
        }
        if symbol in self.errors_by_symbol:
            raise self.errors_by_symbol[symbol]
        if self.error:
            raise self.error
        if interval == '1day' and (self.daily_bars is not None or symbol in self.daily_bars_by_symbol):
            bars = self.daily_bars_by_symbol.get(symbol, self.daily_bars or [])
        else:
            bars = self.bars_by_symbol.get(symbol, self.bars)
        if start_date is not None:
            bars = [bar for bar in bars if bar.date >= start_date]
        if end_date is not None:
            bars = [bar for bar in bars if bar.date <= end_date]
        if outputsize is not None:
            bars = bars[-outputsize:]
        return bars

    def get_daily_time_series(self, symbol, start_date=None, end_date=None, outputsize=None):
        return self.get_time_series(
            symbol=symbol,
            interval='1day',
            start_date=start_date,
            end_date=end_date,
            outputsize=outputsize,
        )

    def get_quote(self, symbol):
        self.quote_calls.append({'symbol': symbol})
        if self.quote_error:
            raise self.quote_error
        return self.quote

    def symbol_search(self, symbol):
        self.symbol_search_calls.append({'symbol': symbol})
        if self.symbol_search_error:
            raise self.symbol_search_error
        return self.symbol_search_results


def make_security(symbol='AAPL', asset_type=Security.AssetType.STOCK):
    return Security.objects.create(
        symbol=symbol,
        name=f'{symbol} Test Security',
        asset_type=asset_type,
        exchange='NASDAQ',
        currency='USD',
    )


def make_daily_bars(start_date, end_date):
    day_count = (end_date - start_date).days + 1
    return [
        FakeDailyBar(
            start_date + timedelta(days=offset),
            Decimal('100'),
            Decimal('102'),
            Decimal('99'),
            Decimal('101'),
            1000 + offset,
        )
        for offset in range(day_count)
    ]


def make_summary_bars(symbol_index, start_date, count=4):
    base_price = Decimal('1000') + Decimal(symbol_index * 100)
    return [
        FakeDailyBar(
            start_date + timedelta(days=offset),
            base_price + Decimal(offset),
            base_price + Decimal(offset) + Decimal('2'),
            base_price + Decimal(offset) - Decimal('2'),
            base_price + Decimal(offset) + Decimal('1'),
            1000 + offset,
        )
        for offset in range(count)
    ]


def subtract_months_for_test(value, months):
    target_month_index = value.month - months - 1
    target_year = value.year + target_month_index // 12
    target_month = target_month_index % 12 + 1
    target_day = min(value.day, monthrange(target_year, target_month)[1])
    return date(target_year, target_month, target_day)


def subtract_years_for_test(value, years):
    target_year = value.year - years
    target_day = min(value.day, monthrange(target_year, value.month)[1])
    return date(target_year, value.month, target_day)


def expected_range_start(range_key, today):
    if range_key == '1D':
        return today - timedelta(days=1)
    if range_key == '1W':
        return today - timedelta(days=7)
    if range_key == '1M':
        return subtract_months_for_test(today, 1)
    if range_key == '3M':
        return subtract_months_for_test(today, 3)
    if range_key == '6M':
        return subtract_months_for_test(today, 6)
    if range_key == '1Y':
        return subtract_years_for_test(today, 1)
    if range_key == '5Y':
        return subtract_years_for_test(today, 5)
    raise AssertionError(f'Unsupported test range {range_key}')


def expected_provider_start(range_key, today):
    warmup_start = expected_warmup_start(range_key, today, '1day')
    return warmup_start - timedelta(days=MARKET_DATA_FETCH_START_BUFFER_DAYS)


def expected_warmup_start(range_key, today, interval):
    return expected_range_start(range_key, today) - timedelta(days=MARKET_DATA_INDICATOR_WARMUP_DAYS[interval])


class SecuritySymbolSearchTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_symbol_search_merges_local_and_remote_results(self):
        local_security = Security.objects.create(
            symbol='AVGO',
            name='Existing Broadcom',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        client = FakeTwelveDataClient(symbol_search_results=[
            {
                'symbol': 'AVGO',
                'instrument_name': 'Broadcom Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
            },
            {
                'symbol': 'AVGOP',
                'instrument_name': 'Broadcom Preferred',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
            },
        ])

        payload = search_security_symbols('AVGO', client=client)

        self.assertEqual(payload['metadata']['count'], 2)
        self.assertEqual(payload['items'][0]['symbol'], 'AVGO')
        self.assertEqual(payload['items'][0]['id'], local_security.id)
        self.assertTrue(payload['items'][0]['is_local'])
        self.assertEqual(payload['items'][0]['mic_code'], 'XNAS')
        self.assertEqual(client.symbol_search_calls, [{'symbol': 'AVGO'}])

    @override_settings(MARKET_DATA_SYMBOL_SEARCH_CACHE_TTL_SECONDS=300)
    def test_symbol_search_uses_ttl_cache(self):
        client = FakeTwelveDataClient(symbol_search_results=[
            {
                'symbol': 'AVGO',
                'instrument_name': 'Broadcom Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
            },
        ])

        with patch('market.services.TwelveDataClient', return_value=client):
            first_payload = search_security_symbols('AVGO')
            second_payload = search_security_symbols('AVGO')

        self.assertEqual(first_payload['metadata']['cache_status'], 'fresh')
        self.assertEqual(second_payload['metadata']['cache_status'], 'hit')
        self.assertEqual(client.symbol_search_calls, [{'symbol': 'AVGO'}])

    def test_symbol_search_preserves_rate_limit_when_no_local_result_exists(self):
        client = FakeTwelveDataClient(
            symbol_search_error=TwelveDataRateLimitError('limit reached'),
        )

        with self.assertRaises(MarketDataRateLimited):
            search_security_symbols('AVGO', client=client)

    def test_symbol_search_keeps_local_result_when_remote_provider_is_unavailable(self):
        local_security = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            country='United States',
            currency='USD',
        )
        client = FakeTwelveDataClient(
            symbol_search_error=TwelveDataError('provider unavailable'),
        )

        payload = search_security_symbols('AAPL', client=client)

        self.assertEqual([item['id'] for item in payload['items']], [local_security.id])
        self.assertTrue(payload['items'][0]['is_local'])
        self.assertIn('temporarily unavailable', payload['metadata']['remote_error'])

    def test_one_character_query_does_not_call_remote_search_or_create_security(self):
        client = FakeTwelveDataClient(symbol_search_results=[{
            'symbol': 'TSLA',
            'instrument_name': 'Tesla Inc.',
            'instrument_type': 'Common Stock',
        }])

        payload = search_security_symbols('T', client=client)

        self.assertEqual(payload['items'], ())
        self.assertEqual(client.symbol_search_calls, [])
        self.assertEqual(Security.objects.count(), 0)

    def test_symbol_search_filters_unsupported_remote_assets_and_labels_source(self):
        client = FakeTwelveDataClient(symbol_search_results=[
            {
                'symbol': 'TSLA',
                'instrument_name': 'Tesla Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
            },
            {
                'symbol': 'BTC/USD',
                'instrument_name': 'Bitcoin',
                'exchange': 'Coinbase',
                'instrument_type': 'Crypto',
                'currency': 'USD',
            },
        ])

        payload = search_security_symbols('TS', client=client)

        self.assertEqual([item['symbol'] for item in payload['items']], ['TSLA'])
        self.assertEqual(payload['items'][0]['source'], 'remote')
        self.assertFalse(payload['items'][0]['is_local'])
        self.assertEqual(Security.objects.count(), 0)


class TwelveDataParsingTests(TestCase):
    def test_parse_bar_uses_decimal_values_and_integer_volume(self):
        bar = parse_bar({
            'datetime': '2026-07-24',
            'open': '100.1000',
            'high': '105.2500',
            'low': '99.5000',
            'close': '104.7500',
            'volume': '123456',
        })

        self.assertEqual(bar.date, date(2026, 7, 24))
        self.assertEqual(bar.open, Decimal('100.1000'))
        self.assertEqual(bar.high, Decimal('105.2500'))
        self.assertEqual(bar.low, Decimal('99.5000'))
        self.assertEqual(bar.close, Decimal('104.7500'))
        self.assertEqual(bar.volume, 123456)

    def test_parse_quote_uses_decimal_values_and_sanitized_timestamp(self):
        quote = parse_quote({
            'symbol': 'AAPL',
            'price': '198.1200',
            'change': '-1.2500',
            'percent_change': '-0.6270',
            'datetime': '2026-07-31',
        })

        self.assertEqual(quote.price, Decimal('198.1200'))
        self.assertEqual(quote.change, Decimal('-1.2500'))
        self.assertEqual(quote.percent_change, Decimal('-0.6270'))
        self.assertEqual(quote.as_of, '2026-07-31')

    @override_settings(TWELVE_DATA_TIMEZONE='America/New_York')
    def test_intraday_time_series_request_uses_full_market_day_boundaries_and_timezone(self):
        captured = {}

        class CapturingTwelveDataClient(TwelveDataClient):
            def _request(self, endpoint, params):
                captured['endpoint'] = endpoint
                captured['params'] = params
                return {
                    'values': [
                        {
                            'datetime': '2026-07-30 15:59:00',
                            'open': '337.90',
                            'high': '338.50',
                            'low': '337.80',
                            'close': '338.07',
                            'volume': '1500',
                        },
                    ],
                }

        client = CapturingTwelveDataClient(api_key='test-key')
        bars = client.get_time_series(
            symbol='AAPL',
            interval='1min',
            start_date=date(2026, 7, 30),
            end_date=date(2026, 7, 30),
        )

        self.assertEqual(captured['endpoint'], 'time_series')
        self.assertEqual(captured['params']['symbol'], 'AAPL')
        self.assertEqual(captured['params']['interval'], '1min')
        self.assertEqual(captured['params']['start_date'], '2026-07-30 00:00:00')
        self.assertEqual(captured['params']['end_date'], '2026-07-30 23:59:59')
        self.assertEqual(captured['params']['timezone'], 'America/New_York')
        self.assertNotIn('outputsize', captured['params'])
        self.assertEqual(bars[-1].timestamp, '2026-07-30 15:59:00')

    @override_settings(TWELVE_DATA_TIMEZONE='America/New_York')
    def test_daily_time_series_request_converts_inclusive_end_to_provider_exclusive_boundary(self):
        captured = {}

        class CapturingTwelveDataClient(TwelveDataClient):
            def _request(self, endpoint, params):
                captured['params'] = params
                return {
                    'values': [
                        {
                            'datetime': '2026-07-30',
                            'open': '337.90',
                            'high': '338.50',
                            'low': '337.80',
                            'close': '338.07',
                            'volume': '1500',
                        },
                    ],
                }

        client = CapturingTwelveDataClient(api_key='test-key')
        client.get_time_series(
            symbol='AAPL',
            interval='1day',
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 30),
        )

        self.assertEqual(captured['params']['start_date'], '2026-07-01')
        self.assertEqual(captured['params']['end_date'], '2026-07-31')
        self.assertEqual(captured['params']['timezone'], 'America/New_York')


class MarketDataDateRangeTests(TestCase):
    def test_latest_complete_market_date_uses_new_york_close_not_django_utc_date(self):
        self.assertEqual(
            get_latest_complete_market_date(datetime(2026, 7, 31, 1, 30, tzinfo=ZoneInfo('UTC'))),
            date(2026, 7, 30),
        )
        self.assertEqual(
            get_latest_complete_market_date(datetime(2026, 7, 30, 19, 30, tzinfo=ZoneInfo('UTC'))),
            date(2026, 7, 29),
        )

    @patch('market.services.get_latest_complete_market_date', return_value=date(2026, 7, 30))
    def test_supported_ranges_convert_to_expected_date_windows(self, latest_complete_date_mock):
        expected_windows = {
            '1D': (date(2026, 7, 29), date(2026, 7, 30)),
            '1W': (date(2026, 7, 23), date(2026, 7, 30)),
            '1M': (date(2026, 6, 30), date(2026, 7, 30)),
            '3M': (date(2026, 4, 30), date(2026, 7, 30)),
            '6M': (date(2026, 1, 30), date(2026, 7, 30)),
            '1Y': (date(2025, 7, 30), date(2026, 7, 30)),
            '5Y': (date(2021, 7, 30), date(2026, 7, 30)),
        }

        for range_key, expected_window in expected_windows.items():
            with self.subTest(range_key=range_key):
                self.assertEqual(get_range_date_window(range_key), expected_window)

    @patch('market.services.get_latest_complete_market_date', return_value=date(2026, 7, 30))
    def test_supported_ranges_use_expected_provider_intervals(self, latest_complete_date_mock):
        expected_intervals = {
            '1D': '1min',
            '1W': '15min',
            '1M': '1h',
            '3M': '2h',
            '6M': '1day',
            '1Y': '1day',
            '5Y': '1week',
        }

        for range_key, expected_interval in expected_intervals.items():
            with self.subTest(range_key=range_key):
                start_date, end_date = get_range_date_window(range_key)
                self.assertEqual(get_market_data_interval(range_key, start_date, end_date), expected_interval)

    def test_custom_interval_is_selected_from_date_span(self):
        cases = [
            (date(2026, 7, 30), date(2026, 7, 30), '1min'),
            (date(2026, 7, 23), date(2026, 7, 30), '15min'),
            (date(2026, 7, 1), date(2026, 7, 30), '1h'),
            (date(2026, 4, 30), date(2026, 7, 30), '2h'),
            (date(2026, 1, 1), date(2026, 7, 30), '1day'),
            (date(2021, 7, 30), date(2026, 7, 30), '1week'),
        ]

        for start_date, end_date, expected_interval in cases:
            with self.subTest(start_date=start_date, end_date=end_date):
                self.assertEqual(get_market_data_interval('CUSTOM', start_date, end_date), expected_interval)

    def test_explicit_interval_overrides_range_default_with_supported_provider_value(self):
        start_date = date(2026, 4, 30)
        end_date = date(2026, 7, 30)

        expected_aliases = {
            '1m': '1min',
            '5m': '5min',
            '15m': '15min',
            '30m': '30min',
            '1h': '1h',
            '2h': '2h',
            '4h': '4h',
            '1D': '1day',
            '1W': '1week',
        }
        for raw_interval, expected_interval in expected_aliases.items():
            with self.subTest(raw_interval=raw_interval):
                self.assertEqual(
                    get_market_data_interval('3M', start_date, end_date, interval=raw_interval),
                    expected_interval,
                )

        with self.assertRaises(UnsupportedMarketDataInterval):
            get_market_data_interval('3M', start_date, end_date, interval='10min')

    @patch('market.services.get_latest_complete_market_date', return_value=date(2026, 7, 30))
    def test_custom_date_range_validation(self, latest_complete_date_mock):
        self.assertEqual(
            get_range_date_window('CUSTOM', start_date='2026-01-05', end_date='2026-01-10'),
            (date(2026, 1, 5), date(2026, 1, 10)),
        )

        invalid_cases = [
            {'start_date': '2026-01-11', 'end_date': '2026-01-10'},
            {'start_date': '2026-13-01', 'end_date': '2026-01-10'},
            {'start_date': '2026-01-10', 'end_date': '2026-08-01'},
            {'start_date': '', 'end_date': '2026-01-10'},
        ]
        for invalid_case in invalid_cases:
            with self.subTest(invalid_case=invalid_case):
                with self.assertRaises(InvalidMarketDataDateRange):
                    get_range_date_window('CUSTOM', **invalid_case)


class MarketDataServiceTests(TestCase):
    def test_fetches_daily_prices_from_provider_and_caches_to_database(self):
        security = make_security()
        today = get_latest_complete_market_date()
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(today - timedelta(days=2), Decimal('100'), Decimal('102'), Decimal('99'), Decimal('101'), 1000),
            FakeDailyBar(today - timedelta(days=1), Decimal('101'), Decimal('103'), Decimal('100'), Decimal('102'), 1100),
        ])

        result = get_security_daily_market_data(security, range_key='6M', client=client)

        self.assertEqual(client.calls[0]['symbol'], 'AAPL')
        self.assertEqual(client.calls[0]['interval'], '1day')
        self.assertIsNone(client.calls[0]['start_date'])
        self.assertIsNone(client.calls[0]['end_date'])
        self.assertEqual(client.calls[0]['outputsize'], (today - expected_provider_start('6M', today)).days + 10)
        self.assertEqual(result.range_key, '6M')
        self.assertEqual(result.interval, '1day')
        self.assertEqual(len(result.values), 2)
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 2)
        cached_price = SecurityDailyPrice.objects.get(security=security, date=today - timedelta(days=1))
        self.assertEqual(cached_price.close, Decimal('102.000000'))

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def test_uses_fresh_cached_prices_without_provider_call(self):
        security = make_security()
        today = get_latest_complete_market_date()
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_warmup_start('6M', today, '1day'),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_range_start('6M', today),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=today,
            open=Decimal('101'),
            high=Decimal('103'),
            low=Decimal('100'),
            close=Decimal('102'),
            volume=1100,
        )
        client = FakeTwelveDataClient(error=AssertionError('Provider should not be called.'))

        result = get_security_daily_market_data(security, range_key='6M', client=client)

        self.assertEqual(len(result.values), 2)
        self.assertEqual(client.calls, [])
        self.assertFalse(result.is_stale)
        self.assertEqual(result.data_source, 'database_cache')
        self.assertEqual(result.cache_status, 'hit')

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def test_daily_cache_missing_latest_complete_market_date_is_refreshed(self):
        security = make_security()
        today = get_latest_complete_market_date()
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_warmup_start('6M', today, '1day'),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=today - timedelta(days=1),
            open=Decimal('101'),
            high=Decimal('103'),
            low=Decimal('100'),
            close=Decimal('102'),
            volume=1100,
        )
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(today, Decimal('102'), Decimal('104'), Decimal('101'), Decimal('103'), 1200),
        ])

        result = get_security_daily_market_data(security, range_key='6M', client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertIsNone(client.calls[0]['end_date'])
        self.assertEqual(client.calls[0]['outputsize'], (today - expected_provider_start('6M', today)).days + 10)
        self.assertEqual(result.values[-1].date, today)
        self.assertEqual(result.data_source, 'twelve_data')
        self.assertEqual(result.cache_status, 'miss')

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=0)
    def test_returns_stale_cache_when_provider_fails(self):
        security = make_security()
        today = get_latest_complete_market_date()
        SecurityDailyPrice.objects.create(
            security=security,
            date=today - timedelta(days=1),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        client = FakeTwelveDataClient(error=TwelveDataError('Provider unavailable'))

        result = get_security_daily_market_data(security, range_key='6M', client=client)

        self.assertEqual(len(result.values), 1)
        self.assertTrue(result.is_stale)
        self.assertEqual(result.data_source, 'stale_database_cache')
        self.assertEqual(result.cache_status, 'stale_fallback')
        self.assertEqual(result.upstream_error, 'Provider unavailable')
        self.assertEqual(result.last_updated, str(today - timedelta(days=1)))

    def test_fetches_latest_quote_from_provider_for_security_symbol(self):
        security = make_security()
        client = FakeTwelveDataClient(quote=FakeQuote(
            price=Decimal('198.12'),
            change=Decimal('1.50'),
            percent_change=Decimal('0.76'),
            as_of='2026-07-31',
        ))

        result = get_security_latest_quote(security, client=client)

        self.assertEqual(client.quote_calls, [{'symbol': 'AAPL'}])
        self.assertEqual(result.security, security)
        self.assertEqual(result.price, Decimal('198.12'))
        self.assertEqual(result.change, Decimal('1.50'))
        self.assertEqual(result.percent_change, Decimal('0.76'))
        self.assertEqual(result.currency, 'USD')

    @override_settings(MARKET_DATA_QUOTE_CACHE_TTL_SECONDS=60)
    def test_latest_quote_uses_short_ttl_cache(self):
        cache.clear()
        security = make_security()
        client = FakeTwelveDataClient(quote=FakeQuote(
            price=Decimal('198.12'),
            change=Decimal('1.50'),
            percent_change=Decimal('0.76'),
            as_of='2026-07-31',
        ))

        with patch('market.services.TwelveDataClient', return_value=client):
            first_result = get_security_latest_quote(security)
            second_result = get_security_latest_quote(security)

        self.assertEqual(client.quote_calls, [{'symbol': 'AAPL'}])
        self.assertEqual(first_result.source, SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(first_result.cache_status, 'fresh')
        self.assertEqual(second_result.source, MARKET_DATA_QUOTE_SOURCE_CACHED)
        self.assertEqual(second_result.cache_status, 'hit')
        self.assertEqual(second_result.price, Decimal('198.12'))

    def test_latest_quote_can_use_cached_daily_close_as_stale_fallback(self):
        security = make_security()
        SecurityDailyPrice.objects.create(
            security=security,
            date=date(2026, 7, 30),
            open=Decimal('190'),
            high=Decimal('195'),
            low=Decimal('188'),
            close=Decimal('194'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=date(2026, 7, 31),
            open=Decimal('194'),
            high=Decimal('199'),
            low=Decimal('193'),
            close=Decimal('198'),
            volume=1100,
        )
        client = FakeTwelveDataClient(
            quote_error=TwelveDataRateLimitError('provider raw limit response'),
        )

        result = get_security_latest_quote(security, client=client, allow_stale=True)

        self.assertEqual(result.source, MARKET_DATA_QUOTE_SOURCE_LAST_CLOSE)
        self.assertEqual(result.cache_status, 'daily_fallback')
        self.assertEqual(result.data_status, 'stale')
        self.assertTrue(result.is_stale)
        self.assertEqual(result.price, Decimal('198'))
        self.assertEqual(result.change, Decimal('4'))
        self.assertEqual(result.percent_change, Decimal('2.061855670103092783505154639'))

    def test_latest_quote_maps_provider_rate_limit_to_project_error(self):
        security = make_security()
        client = FakeTwelveDataClient(
            quote_error=TwelveDataRateLimitError('provider raw limit response'),
        )

        with self.assertRaises(MarketDataRateLimited) as error_context:
            get_security_latest_quote(security, client=client)

        self.assertEqual(
            str(error_context.exception),
            'Market data provider rate limit reached. Please try again later.',
        )

    def test_latest_quote_maps_invalid_provider_symbol_to_project_error(self):
        security = make_security()
        client = FakeTwelveDataClient(
            quote_error=TwelveDataInvalidSymbolError('provider raw invalid symbol response'),
        )

        with self.assertRaises(MarketDataInvalidSymbol) as error_context:
            get_security_latest_quote(security, client=client)

        self.assertEqual(
            str(error_context.exception),
            'Market data is not available for this security.',
        )

    def test_latest_quotes_returns_unavailable_item_without_raising_for_rate_limit(self):
        security = make_security()
        client = FakeTwelveDataClient(
            quote_error=TwelveDataRateLimitError('provider raw limit response'),
        )

        result = get_security_latest_quotes([security], client=client)[0]

        self.assertEqual(result.security, security)
        self.assertEqual(result.data_status, 'unavailable')
        self.assertEqual(result.source, 'PRICE_UNAVAILABLE')
        self.assertEqual(result.price, Decimal('0'))
        self.assertIn('rate limit', result.error.lower())

    def test_market_summary_fetches_configured_symbols_and_computes_changes(self):
        start_date = date(2026, 7, 20)
        client = FakeTwelveDataClient(bars_by_symbol={
            'SPY': make_summary_bars(1, start_date),
            'ONEQ': make_summary_bars(2, start_date),
            'DIA': make_summary_bars(3, start_date),
            'BTC/USD': make_summary_bars(4, start_date),
        })

        summary = get_market_summary(client=client)

        self.assertEqual(summary['source'], SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(summary['status'], 'ok')
        self.assertEqual(summary['cache_status'], 'fresh')
        self.assertEqual(summary['metadata']['count'], 4)
        self.assertEqual(summary['metadata']['symbols'], ('SPY', 'ONEQ', 'DIA', 'BTC/USD'))
        self.assertEqual(summary['metadata']['requested_symbols'], ('SPX', 'IXIC', 'DJI', 'BTC/USD'))
        self.assertEqual(summary['metadata']['provider_symbols'], ('SPY', 'ONEQ', 'DIA', 'BTC/USD'))
        self.assertEqual([call['symbol'] for call in client.calls], ['SPY', 'ONEQ', 'DIA', 'BTC/USD'])
        self.assertTrue(all(call['interval'] == '1day' for call in client.calls))
        self.assertTrue(all(call['outputsize'] == 16 for call in client.calls))
        self.assertEqual(len(summary['items']), 4)
        self.assertEqual(summary['items'][0]['id'], 'sp500')
        self.assertEqual(summary['items'][0]['symbol'], 'SPY')
        self.assertEqual(summary['items'][0]['requested_symbol'], 'SPX')
        self.assertEqual(summary['items'][0]['provider_symbol'], 'SPY')
        self.assertTrue(summary['items'][0]['is_proxy'])
        self.assertEqual(summary['items'][0]['display_name'], 'S&P 500 ETF proxy')
        self.assertEqual(summary['items'][0]['latest_price'], 1104.0)
        self.assertEqual(summary['items'][0]['previous_close'], 1103.0)
        self.assertEqual(summary['items'][0]['absolute_change'], 1.0)
        self.assertEqual(summary['items'][0]['percentage_change'], 0.090662)
        self.assertEqual(summary['items'][0]['updated_at'], '2026-07-23')
        self.assertEqual(summary['items'][0]['data_status'], 'ok')
        self.assertEqual(len(summary['items'][0]['sparkline']), 4)
        self.assertEqual(
            [point['datetime'] for point in summary['items'][0]['sparkline']],
            ['2026-07-20', '2026-07-21', '2026-07-22', '2026-07-23'],
        )
        self.assertEqual(summary['items'][0]['sparkline'][-1]['close'], summary['items'][0]['latest_price'])
        self.assertEqual(summary['updated_at'], '2026-07-23')

    def test_market_summary_keeps_failed_item_unavailable_without_failing_payload(self):
        start_date = date(2026, 7, 20)
        client = FakeTwelveDataClient(
            bars_by_symbol={
                'SPY': make_summary_bars(1, start_date),
                'ONEQ': make_summary_bars(2, start_date),
                'DIA': make_summary_bars(3, start_date),
            },
            errors_by_symbol={
                'BTC/USD': TwelveDataRateLimitError(
                    'raw provider rate limit',
                    http_status=429,
                    provider_status='error',
                    provider_code=429,
                    provider_message='API credits exhausted',
                ),
            },
        )

        summary = get_market_summary(client=client)
        bitcoin_item = summary['items'][3]

        self.assertEqual(summary['status'], 'partial')
        self.assertEqual(bitcoin_item['symbol'], 'BTC/USD')
        self.assertEqual(bitcoin_item['data_status'], 'unavailable')
        self.assertIsNone(bitcoin_item['latest_price'])
        self.assertIsNone(bitcoin_item['previous_close'])
        self.assertEqual(bitcoin_item['sparkline'], ())
        self.assertEqual(
            bitcoin_item['error'],
            'Market data provider rate limit reached. Please try again later.',
        )
        self.assertEqual(bitcoin_item['provider_http_status'], 429)
        self.assertEqual(bitcoin_item['provider_status'], 'error')
        self.assertEqual(bitcoin_item['provider_code'], 429)
        self.assertEqual(bitcoin_item['provider_message'], 'API credits exhausted')

    def test_fetches_one_day_intraday_prices_without_daily_cache(self):
        security = make_security()
        today = get_latest_complete_market_date()
        warmup_bars = [
            FakeDailyBar(
                today - timedelta(days=2),
                Decimal('99'),
                Decimal('100'),
                Decimal('98'),
                Decimal('99.5'),
                900 + index,
                timestamp=f'{(today - timedelta(days=2)).isoformat()} 09:{index % 60:02d}:00',
            )
            for index in range(70)
        ]
        client = FakeTwelveDataClient(bars=[
            *warmup_bars,
            *[
                FakeDailyBar(
                    today - timedelta(days=1),
                    Decimal('99'),
                    Decimal('101'),
                    Decimal('98'),
                    Decimal('100'),
                    950 + index,
                    timestamp=f'{(today - timedelta(days=1)).isoformat()} 15:{index % 60:02d}:00',
                )
                for index in range(5)
            ],
            FakeDailyBar(
                today,
                Decimal('100'),
                Decimal('101'),
                Decimal('99'),
                Decimal('100.5'),
                1000,
                timestamp=f'{today.isoformat()} 09:45:00',
            ),
        ])

        result = get_security_daily_market_data(security, range_key='1D', client=client)

        self.assertEqual(client.calls[0]['interval'], '1min')
        self.assertEqual(client.calls[0]['start_date'], expected_warmup_start('1D', today, '1min'))
        self.assertEqual(client.calls[0]['end_date'], today)
        self.assertEqual(result.interval, '1min')
        self.assertEqual(len(result.warmup_values), MARKET_DATA_INDICATOR_WARMUP_BARS)
        self.assertEqual(result.warmup_values[-1].date, today - timedelta(days=1))
        self.assertTrue(all(value.date == today for value in result.values))
        self.assertEqual(result.values[0].timestamp, f'{today.isoformat()} 09:45:00')
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 0)

    def test_intraday_prices_align_session_last_close_to_official_daily_close(self):
        security = make_security()
        today = get_latest_complete_market_date()
        previous_day = today - timedelta(days=1)
        client = FakeTwelveDataClient(
            bars=[
                FakeDailyBar(
                    previous_day,
                    Decimal('333.52'),
                    Decimal('334.00'),
                    Decimal('333.04'),
                    Decimal('333.85001'),
                    882500,
                    timestamp=f'{previous_day.isoformat()} 15:59:00',
                ),
                FakeDailyBar(
                    today,
                    Decimal('309.65'),
                    Decimal('310.66'),
                    Decimal('308.44'),
                    Decimal('309.029999'),
                    2565164,
                    timestamp=f'{today.isoformat()} 15:59:00',
                ),
            ],
            daily_bars=[
                FakeDailyBar(
                    previous_day,
                    Decimal('333.10'),
                    Decimal('334.75'),
                    Decimal('329.59'),
                    Decimal('333.42999'),
                    74817800,
                ),
                FakeDailyBar(
                    today,
                    Decimal('304.81'),
                    Decimal('310.69'),
                    Decimal('300'),
                    Decimal('308.91000'),
                    127398021,
                ),
            ],
        )

        result = get_security_daily_market_data(security, range_key='1D', interval='1min', client=client)

        self.assertEqual([call['interval'] for call in client.calls], ['1min', '1day'])
        self.assertEqual(result.values[-1].timestamp, f'{today.isoformat()} 15:59:00')
        self.assertEqual(result.values[-1].close, Decimal('308.91000'))
        self.assertEqual(result.warmup_values[-1].timestamp, f'{previous_day.isoformat()} 15:59:00')
        self.assertEqual(result.warmup_values[-1].close, Decimal('333.42999'))
        self.assertEqual(len(result.session_close_adjustments), 2)
        self.assertEqual(result.session_close_adjustments[-1]['original_close'], '309.029999')
        self.assertEqual(result.session_close_adjustments[-1]['official_close'], '308.91000')
        self.assertEqual(result.provider_metadata['time_series']['last_timestamp'], f'{today.isoformat()} 15:59:00')

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def test_intraday_session_close_reuses_fresh_daily_cache_without_daily_provider_call(self):
        security = make_security()
        today = get_latest_complete_market_date()
        warmup_start = expected_warmup_start('1D', today, '1min')
        # Seed a fresh daily cache that covers the full alignment window.
        for offset in range((today - warmup_start).days + 1):
            SecurityDailyPrice.objects.create(
                security=security,
                date=warmup_start + timedelta(days=offset),
                open=Decimal('100'),
                high=Decimal('102'),
                low=Decimal('99'),
                close=Decimal('101'),
                volume=1000,
            )
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(
                today,
                Decimal('100'),
                Decimal('101'),
                Decimal('99'),
                Decimal('99.5'),
                1000,
                timestamp=f'{today.isoformat()} 15:59:00',
            ),
        ])

        result = get_security_daily_market_data(
            security,
            range_key='1D',
            interval='1min',
            client=client,
        )

        self.assertEqual([call['interval'] for call in client.calls], ['1min'])
        self.assertEqual(result.range_key, '1D')
        self.assertEqual(result.interval, '1min')
        self.assertEqual(result.data_source, 'twelve_data')
        self.assertFalse(result.is_stale)
        self.assertEqual(result.values[-1].close, Decimal('101'))
        self.assertEqual(result.session_close_adjustments[-1]['original_close'], '99.5')
        self.assertEqual(result.session_close_adjustments[-1]['official_close'], '101.000000')
        self.assertEqual(result.provider_metadata['session_close_source']['source'], 'database_cache')
        self.assertEqual(result.provider_metadata['session_close_source']['cache_status'], 'hit')

    def test_intraday_session_close_calls_daily_provider_when_cache_missing(self):
        security = make_security()
        today = get_latest_complete_market_date()
        client = FakeTwelveDataClient(
            bars=[
                FakeDailyBar(
                    today,
                    Decimal('100'),
                    Decimal('101'),
                    Decimal('99'),
                    Decimal('99.5'),
                    1000,
                    timestamp=f'{today.isoformat()} 15:59:00',
                ),
            ],
            daily_bars=[
                FakeDailyBar(
                    today,
                    Decimal('100'),
                    Decimal('102'),
                    Decimal('99'),
                    Decimal('101'),
                    1000,
                ),
            ],
        )

        result = get_security_daily_market_data(
            security,
            range_key='1D',
            interval='1min',
            client=client,
        )

        self.assertEqual([call['interval'] for call in client.calls], ['1min', '1day'])
        self.assertEqual(result.values[-1].close, Decimal('101'))
        self.assertEqual(result.session_close_adjustments[-1]['official_close'], '101')
        self.assertEqual(result.provider_metadata['session_close_source']['endpoint'], 'time_series')

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def test_intraday_session_close_calls_daily_provider_when_coverage_insufficient(self):
        security = make_security()
        today = get_latest_complete_market_date()
        # Daily cache exists but only covers the latest day, not the warmup start.
        SecurityDailyPrice.objects.create(
            security=security,
            date=today,
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        client = FakeTwelveDataClient(
            bars=[
                FakeDailyBar(
                    today,
                    Decimal('100'),
                    Decimal('101'),
                    Decimal('99'),
                    Decimal('99.5'),
                    1000,
                    timestamp=f'{today.isoformat()} 15:59:00',
                ),
            ],
            daily_bars=[
                FakeDailyBar(
                    today,
                    Decimal('100'),
                    Decimal('102'),
                    Decimal('99'),
                    Decimal('101'),
                    1000,
                ),
            ],
        )

        result = get_security_daily_market_data(
            security,
            range_key='1D',
            interval='1min',
            client=client,
        )

        self.assertEqual([call['interval'] for call in client.calls], ['1min', '1day'])
        self.assertEqual(result.values[-1].close, Decimal('101'))
        self.assertEqual(result.provider_metadata['session_close_source']['endpoint'], 'time_series')

    def test_fetches_one_week_hourly_prices_without_daily_cache(self):
        security = make_security()
        today = get_latest_complete_market_date()
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(
                today - timedelta(days=8),
                Decimal('99'),
                Decimal('100'),
                Decimal('98'),
                Decimal('99.5'),
                900,
                timestamp=f'{(today - timedelta(days=8)).isoformat()} 10:00:00',
            ),
            FakeDailyBar(
                today,
                Decimal('100'),
                Decimal('101'),
                Decimal('99'),
                Decimal('100.5'),
                1000,
                timestamp=f'{today.isoformat()} 10:00:00',
            ),
        ])

        result = get_security_daily_market_data(security, range_key='1W', client=client)

        self.assertEqual(client.calls[0]['interval'], '15min')
        self.assertEqual(client.calls[0]['start_date'], expected_warmup_start('1W', today, '15min'))
        self.assertEqual(client.calls[0]['end_date'], today)
        self.assertEqual(result.interval, '15min')
        self.assertEqual(len(result.warmup_values), 1)
        self.assertEqual(result.values[0].timestamp, f'{today.isoformat()} 10:00:00')
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 0)

    def test_explicit_intraday_interval_overrides_default_range_interval(self):
        security = make_security()
        today = get_latest_complete_market_date()
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(
                today,
                Decimal('100'),
                Decimal('101'),
                Decimal('99'),
                Decimal('100.5'),
                1000,
                timestamp=f'{today.isoformat()} 10:00:00',
            ),
        ])

        result = get_security_daily_market_data(
            security,
            range_key='1M',
            interval='1h',
            client=client,
        )

        self.assertEqual(client.calls[0]['interval'], '1h')
        self.assertEqual(result.interval, '1h')
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 0)

    def test_rejects_date_ranges_that_are_too_large_for_interval(self):
        security = make_security()
        client = FakeTwelveDataClient(bars=[])

        with self.assertRaises(InvalidMarketDataDateRange) as error_context:
            get_security_daily_market_data(
                security,
                range_key='1Y',
                interval='30m',
                client=client,
            )

        self.assertEqual(client.calls, [])
        self.assertIn('interval', error_context.exception.errors)

    def test_interval_unavailable_returns_clear_project_error(self):
        security = make_security()
        client = FakeTwelveDataClient(
            error=TwelveDataIntervalUnavailableError('provider raw interval plan error'),
        )

        with self.assertRaises(MarketDataUnavailable) as error_context:
            get_security_daily_market_data(security, range_key='1D', client=client)

        self.assertEqual(
            str(error_context.exception),
            'Market data for this interval is not available. Please choose another range.',
        )

    def test_requested_ranges_fetch_dates_covering_requested_windows(self):
        today = get_latest_complete_market_date()
        all_bars = make_daily_bars(today - timedelta(days=1900), today)
        minimum_ages = {
            '1D': 0,
            '1W': 7,
            '1M': 25,
            '3M': 90,
            '6M': 180,
            '1Y': 360,
            '5Y': 1820,
        }

        for range_key, minimum_age in minimum_ages.items():
            with self.subTest(range_key=range_key):
                security = make_security(symbol=f'SEC{range_key}')
                client = FakeTwelveDataClient(bars=all_bars)

                result = get_security_daily_market_data(security, range_key=range_key, client=client)

                self.assertEqual(client.calls[0]['interval'], result.interval)
                if result.interval == '1day':
                    expected_start_date = expected_provider_start(range_key, today)
                    self.assertIsNone(client.calls[0]['start_date'])
                    self.assertIsNone(client.calls[0]['end_date'])
                    self.assertEqual(client.calls[0]['outputsize'], (today - expected_start_date).days + 10)
                else:
                    expected_start_date = expected_warmup_start(range_key, today, result.interval)
                    self.assertEqual(client.calls[0]['start_date'], expected_start_date)
                    self.assertEqual(client.calls[0]['end_date'], today)
                expected_visible_start = today if range_key == '1D' else expected_range_start(range_key, today)
                self.assertEqual(result.values[0].date, expected_visible_start)
                self.assertEqual(result.values[-1].date, today)
                self.assertGreaterEqual((today - result.values[0].date).days, minimum_age)

    def test_expands_cached_data_when_switching_from_six_months_to_one_year(self):
        security = make_security(symbol='MSFT')
        today = get_latest_complete_market_date()
        all_bars = make_daily_bars(today - timedelta(days=400), today)

        six_month_client = FakeTwelveDataClient(bars=all_bars)
        six_month_result = get_security_daily_market_data(
            security,
            range_key='6M',
            client=six_month_client,
        )
        count_after_six_months = SecurityDailyPrice.objects.filter(security=security).count()

        one_year_client = FakeTwelveDataClient(bars=all_bars)
        one_year_result = get_security_daily_market_data(
            security,
            range_key='1Y',
            client=one_year_client,
        )

        self.assertEqual(len(one_year_client.calls), 1)
        self.assertIsNone(one_year_client.calls[0]['start_date'])
        self.assertEqual(
            one_year_client.calls[0]['outputsize'],
            (today - expected_provider_start('1Y', today)).days + 10,
        )
        self.assertLess(
            SecurityDailyPrice.objects.filter(security=security).earliest('date').date,
            expected_range_start('1Y', today),
        )
        self.assertGreater(SecurityDailyPrice.objects.filter(security=security).count(), count_after_six_months)
        self.assertEqual(one_year_result.values[0].date, expected_range_start('1Y', today))
        self.assertGreater(len(one_year_result.values), len(six_month_result.values))

    def test_fetches_five_year_weekly_prices_without_daily_cache(self):
        today = get_latest_complete_market_date()
        all_bars = make_daily_bars(today - timedelta(days=2400), today)
        security = make_security(symbol='H5Y')
        client = FakeTwelveDataClient(bars=all_bars)

        result = get_security_daily_market_data(
            security,
            range_key='5Y',
            client=client,
        )

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]['interval'], '1week')
        self.assertEqual(client.calls[0]['start_date'], expected_warmup_start('5Y', today, '1week'))
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 0)
        self.assertGreaterEqual(len(result.warmup_values), MARKET_DATA_INDICATOR_WARMUP_BARS)
        self.assertEqual(result.values[0].date, expected_range_start('5Y', today))
        self.assertGreater(len(result.values), 1800)

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=0)
    def test_repeated_fetches_upsert_without_duplicate_daily_prices(self):
        security = make_security(symbol='GOOG')
        today = get_latest_complete_market_date()
        all_bars = make_daily_bars(today - timedelta(days=400), today)
        client = FakeTwelveDataClient(bars=all_bars)

        get_security_daily_market_data(security, range_key='1Y', client=client)
        count_after_first_request = SecurityDailyPrice.objects.filter(security=security).count()
        get_security_daily_market_data(security, range_key='1Y', client=client)
        count_after_second_request = SecurityDailyPrice.objects.filter(security=security).count()
        unique_date_count = (
            SecurityDailyPrice.objects
            .filter(security=security)
            .values('security_id', 'date')
            .distinct()
            .count()
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(count_after_second_request, count_after_first_request)
        self.assertEqual(unique_date_count, count_after_second_request)


class SecuritySearchApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='security_search_user', password='pass')

    def test_security_search_requires_authentication(self):
        response = self.client.get(reverse('security-search'), {'q': 'AVGO'})

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_security_search_returns_service_payload(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            'query': 'AVGO',
            'items': [
                {
                    'id': None,
                    'symbol': 'AVGO',
                    'name': 'Broadcom Inc.',
                    'exchange': 'NASDAQ',
                    'mic_code': 'XNAS',
                    'instrument_type': 'Common Stock',
                    'country': 'United States',
                    'currency': 'USD',
                    'is_local': False,
                    'is_preferred': True,
                },
            ],
            'metadata': {
                'query': 'AVGO',
                'count': 1,
                'local_count': 0,
                'remote_error': '',
                'cache_status': 'fresh',
            },
        }

        with patch('market.views.search_security_symbols', return_value=payload) as search_mock:
            response = self.client.get(reverse('security-search'), {'q': 'AVGO'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['items'][0]['symbol'], 'AVGO')
        search_mock.assert_called_once_with('AVGO', force_refresh=False)


class SecuritySectorContextApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sector-context-user',
            password='password123',
        )
        self.client.force_authenticate(self.user)
        self.securities = {
            symbol: Security.objects.create(
                symbol=symbol,
                name=f'{symbol} Test Security',
                asset_type=Security.AssetType.STOCK,
                exchange='NASDAQ',
                currency='USD',
            )
            for symbol in ('AAPL', 'JPM', 'XOM', 'UNKNOWN')
        }

    def get_sector_context(self, symbol):
        security = self.securities[symbol]
        return self.client.get(reverse('security-sector-context', args=[security.id]))

    def test_aapl_sector_context_returns_spy_qqq_xlk(self):
        response = self.get_sector_context('AAPL')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['sector'], 'Information Technology')
        self.assertEqual(response.data['sector_benchmark'], 'XLK')
        self.assertEqual(response.data['broad_market'], 'SPY')
        self.assertIn('SPY', response.data['allowed_benchmarks'])
        self.assertIn('XLK', response.data['allowed_benchmarks'])
        self.assertIn('QQQ', response.data['allowed_benchmarks'])
        self.assertNotIn('XLF', response.data['allowed_benchmarks'])
        self.assertNotIn('XLE', response.data['allowed_benchmarks'])
        self.assertNotIn('XLY', response.data['allowed_benchmarks'])

    def test_jpm_sector_context_returns_spy_xlf(self):
        response = self.get_sector_context('JPM')

        self.assertEqual(response.data['sector'], 'Financials')
        self.assertEqual(response.data['sector_benchmark'], 'XLF')
        self.assertIn('SPY', response.data['allowed_benchmarks'])
        self.assertIn('XLF', response.data['allowed_benchmarks'])
        self.assertNotIn('QQQ', response.data['allowed_benchmarks'])

    def test_xom_sector_context_returns_spy_xle(self):
        response = self.get_sector_context('XOM')

        self.assertEqual(response.data['sector'], 'Energy')
        self.assertEqual(response.data['sector_benchmark'], 'XLE')
        self.assertIn('SPY', response.data['allowed_benchmarks'])
        self.assertIn('XLE', response.data['allowed_benchmarks'])
        self.assertNotIn('QQQ', response.data['allowed_benchmarks'])

    def test_unknown_sector_falls_back_to_spy(self):
        response = self.get_sector_context('UNKNOWN')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['sector'])
        self.assertIsNone(response.data['sector_benchmark'])
        self.assertEqual(response.data['allowed_benchmarks'], ['SPY'])

    def test_sector_context_requires_authentication(self):
        self.client.force_authenticate(user=None)
        security = self.securities['AAPL']
        response = self.client.get(reverse('security-sector-context', args=[security.id]))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class SecurityResolveApiTests(APITestCase):
    remote_item = {
        'id': None,
        'symbol': 'JPM',
        'name': 'JPMorgan Chase & Co.',
        'exchange': 'NYSE',
        'mic_code': 'XNYS',
        'instrument_type': 'Common Stock',
        'country': 'United States',
        'currency': 'USD',
        'is_local': False,
        'source': 'remote',
        'is_preferred': True,
    }

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username='security_resolve_user', password='pass')
        self.client.force_authenticate(user=self.user)

    def test_security_resolve_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def selection(self, **overrides):
        return {
            **self.remote_item,
            'search_query': 'JPM',
            **overrides,
        }

    def search_payload(self, item=None):
        result = item or self.remote_item
        return {
            'query': result['symbol'],
            'items': [result],
            'metadata': {
                'query': result['symbol'],
                'count': 1,
                'local_count': 0,
                'remote_error': '',
                'cache_status': 'fresh',
            },
        }

    def test_selecting_verified_remote_result_creates_active_security(self):
        with patch('market.services.search_security_symbols', return_value=self.search_payload()):
            response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['created'])
        self.assertEqual(response.data['security']['symbol'], 'JPM')
        security = Security.objects.get(symbol='JPM', mic_code='XNYS')
        self.assertTrue(security.is_active)
        self.assertEqual(security.name, 'JPMorgan Chase & Co.')

    def test_selecting_same_listing_twice_reuses_one_security(self):
        with patch('market.services.search_security_symbols', return_value=self.search_payload()):
            first = self.client.post(reverse('security-resolve'), self.selection(), format='json')
            second = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.data['created'])
        self.assertEqual(Security.objects.filter(symbol='JPM', mic_code='XNYS').count(), 1)

    def test_selecting_remote_result_reactivates_matching_inactive_security(self):
        security = Security.objects.create(
            symbol='JPM',
            name='JPMorgan Chase & Co.',
            asset_type=Security.AssetType.STOCK,
            exchange='NYSE',
            mic_code='XNYS',
            country='United States',
            currency='USD',
            is_active=False,
        )
        with patch('market.services.search_security_symbols', return_value=self.search_payload()):
            response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['created'])
        security.refresh_from_db()
        self.assertTrue(security.is_active)
        self.assertEqual(Security.objects.filter(symbol='JPM').count(), 1)

    def test_unverified_selection_returns_400_without_creating_security(self):
        with patch('market.services.search_security_symbols', return_value={
            'query': 'JPM', 'items': [], 'metadata': {},
        }):
            response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Security.objects.filter(symbol='JPM').exists())

    def test_provider_rate_limit_returns_429_without_creating_security(self):
        with patch(
            'market.services.search_security_symbols',
            side_effect=MarketDataRateLimited('Provider rate limit reached.'),
        ):
            response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(Security.objects.filter(symbol='JPM').exists())

    def test_provider_unavailable_returns_503_without_creating_security(self):
        with patch(
            'market.services.search_security_symbols',
            side_effect=MarketDataUnavailable('Remote search temporarily unavailable.'),
        ):
            response = self.client.post(reverse('security-resolve'), self.selection(), format='json')

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(Security.objects.filter(symbol='JPM').exists())


class RemoteResolvedMarketDataIntegrationTests(APITestCase):
    """Regression coverage: a remotely resolved security must immediately
    serve its own OHLCV (K-line) data and must never fall back to another
    security's symbol.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username='remote_market_user', password='pass')
        self.client.force_authenticate(user=self.user)

    def remote_item(self, **overrides):
        return {
            'id': None,
            'symbol': 'XOM',
            'name': 'Exxon Mobil Corporation',
            'exchange': 'NYSE',
            'mic_code': 'XNYS',
            'instrument_type': 'Common Stock',
            'country': 'United States',
            'currency': 'USD',
            'is_local': False,
            'source': 'remote',
            'is_preferred': True,
            **overrides,
        }

    def search_payload(self, item):
        return {
            'query': item['symbol'],
            'items': [item],
            'metadata': {
                'query': item['symbol'],
                'count': 1,
                'local_count': 0,
                'remote_error': '',
                'cache_status': 'fresh',
            },
        }

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def assert_remote_security_serves_its_own_ohlcv(self, **item_overrides):
        today = get_latest_complete_market_date()
        item = self.remote_item(**item_overrides)

        with patch('market.services.search_security_symbols', return_value=self.search_payload(item)):
            resolved = self.client.post(
                reverse('security-resolve'),
                {**item, 'search_query': item['symbol']},
                format='json',
            )

        self.assertEqual(resolved.status_code, status.HTTP_201_CREATED)
        security_id = resolved.data['security']['id']
        security = Security.objects.get(pk=security_id)
        self.assertEqual(security.symbol, item['symbol'])

        # Seed a fresh daily cache for the resolved security so the OHLCV
        # endpoint can be exercised end-to-end without calling the provider.
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_warmup_start('6M', today, '1day'),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_range_start('6M', today),
            open=Decimal('100'),
            high=Decimal('102'),
            low=Decimal('99'),
            close=Decimal('101'),
            volume=1000,
        )
        SecurityDailyPrice.objects.create(
            security=security,
            date=today,
            open=Decimal('101'),
            high=Decimal('103'),
            low=Decimal('100'),
            close=Decimal('102'),
            volume=1100,
        )

        response = self.client.get(
            reverse('market-data-daily'),
            {'security': security_id, 'range': '6M'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['security']['id'], security_id)
        self.assertEqual(response.data['security']['symbol'], item['symbol'])
        self.assertEqual(response.data['metadata']['symbol'], item['symbol'])
        self.assertEqual(response.data['metadata']['security_id'], security_id)
        self.assertEqual(response.data['data_source'], 'database_cache')
        self.assertEqual(response.data['cache_status'], 'hit')
        self.assertEqual(response.data['values'][-1]['date'], today.isoformat())
        self.assertEqual(response.data['values'][-1]['close'], '102.000000')
        # No other security may appear in the response for this request.
        self.assertNotEqual(item['symbol'], 'SPY')
        self.assertEqual(
            SecurityDailyPrice.objects.filter(security=security).count(),
            3,
        )

    def test_remote_resolved_xom_serves_xom_ohlcv(self):
        self.assert_remote_security_serves_its_own_ohlcv(
            symbol='XOM',
            name='Exxon Mobil Corporation',
            exchange='NYSE',
            mic_code='XNYS',
            instrument_type='Common Stock',
        )

    def test_remote_resolved_qqq_serves_qqq_ohlcv(self):
        self.assert_remote_security_serves_its_own_ohlcv(
            symbol='QQQ',
            name='Invesco QQQ ETF',
            exchange='NASDAQ',
            mic_code='XNAS',
            instrument_type='ETF',
        )


class MarketDataApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='market_data_user', password='pass')
        self.security = make_security()

    def authenticate(self):
        self.client.force_authenticate(user=self.user)

    def test_market_data_api_requires_authentication(self):
        response = self.client.get(reverse('market-data-daily'), {'security': self.security.id, 'range': '3M'})

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_market_data_quote_api_requires_authentication(self):
        response = self.client.get(reverse('market-data-quote'), {'security': self.security.id})

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_market_summary_api_requires_authentication(self):
        response = self.client.get(reverse('market-data-summary'))

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_market_summary_api_returns_project_owned_payload(self):
        self.authenticate()
        payload = {
            'source': SecurityDailyPrice.SOURCE_TWELVE_DATA,
            'updated_at': '2026-07-23',
            'status': 'ok',
            'cache_status': 'fresh',
            'generated_at': '2026-07-30T12:00:00+00:00',
            'metadata': {
                'count': 1,
                'generated_at': '2026-07-30T12:00:00+00:00',
                'source': SecurityDailyPrice.SOURCE_TWELVE_DATA,
                'symbols': ('SPY',),
                'requested_symbols': ('SPX',),
                'provider_symbols': ('SPY',),
                'cache_status': 'fresh',
            },
            'items': (
                {
                    'id': 'sp500',
                    'key': 'sp500',
                    'symbol': 'SPY',
                    'display_name': 'S&P 500 ETF proxy',
                    'requested_symbol': 'SPX',
                    'provider_symbol': 'SPY',
                    'provider_name': 'SPDR S&P 500 ETF Trust',
                    'instrument_type': 'ETF',
                    'is_proxy': True,
                    'proxy_for': 'S&P 500',
                    'latest_price': 1104.0,
                    'previous_close': 1103.0,
                    'absolute_change': 1.0,
                    'percentage_change': 0.090662,
                    'updated_at': '2026-07-23',
                    'sparkline': (
                        {'datetime': '2026-07-22', 'close': 1103.0},
                        {'datetime': '2026-07-23', 'close': 1104.0},
                    ),
                    'data_status': 'ok',
                    'error': '',
                    'error_code': '',
                    'error_message': '',
                    'provider_http_status': 200,
                    'provider_status': 'ok',
                    'provider_code': None,
                    'provider_message': '',
                    'endpoint': 'time_series',
                    'interval': '1day',
                    'outputsize': 16,
                    'used_cache': False,
                    'used_fallback': False,
                },
            ),
        }

        with patch('market.views.get_market_summary', return_value=payload) as service_mock:
            response = self.client.get(reverse('market-data-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(force_refresh=False)
        self.assertEqual(response.data['source'], SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(response.data['updated_at'], '2026-07-23')
        self.assertEqual(response.data['cache_status'], 'fresh')
        self.assertEqual(response.data['metadata']['count'], 1)
        self.assertEqual(response.data['items'][0]['symbol'], 'SPY')
        self.assertEqual(response.data['items'][0]['requested_symbol'], 'SPX')
        self.assertEqual(response.data['items'][0]['provider_symbol'], 'SPY')
        self.assertEqual(response.data['items'][0]['latest_price'], 1104.0)
        self.assertEqual(response.data['items'][0]['previous_close'], 1103.0)
        self.assertEqual(response.data['items'][0]['sparkline'][1]['close'], 1104.0)
        self.assertEqual(response.data['items'][0]['data_status'], 'ok')

    @override_settings(DEBUG=True)
    def test_market_summary_api_refresh_query_bypasses_cache_in_development(self):
        self.authenticate()
        payload = {
            'source': SecurityDailyPrice.SOURCE_TWELVE_DATA,
            'updated_at': '',
            'status': 'unavailable',
            'cache_status': 'fresh',
            'generated_at': '2026-07-30T12:00:00+00:00',
            'metadata': {'count': 0, 'cache_status': 'fresh'},
            'items': (),
        }

        with patch('market.views.get_market_summary', return_value=payload) as service_mock:
            response = self.client.get(reverse('market-data-summary'), {'refresh': '1'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(force_refresh=True)

    def test_market_data_quote_api_returns_project_owned_payload(self):
        self.authenticate()
        result = MarketDataQuoteResult(
            security=self.security,
            price=Decimal('198.12'),
            change=Decimal('-1.25'),
            percent_change=Decimal('-0.63'),
            currency='USD',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            as_of='2026-07-31',
        )

        with patch('market.views.get_security_latest_quote', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-quote'), {'security': self.security.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(self.security)
        self.assertEqual(response.data['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['source'], SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(response.data['price'], '198.120000')
        self.assertEqual(response.data['change'], '-1.250000')
        self.assertEqual(response.data['percent_change'], '-0.630000')
        self.assertEqual(response.data['currency'], 'USD')
        self.assertEqual(response.data['as_of'], '2026-07-31')
        self.assertEqual(response.data['data_status'], 'ok')

    def test_market_data_quote_api_rejects_missing_or_invalid_security(self):
        self.authenticate()

        missing_response = self.client.get(reverse('market-data-quote'))
        invalid_response = self.client.get(reverse('market-data-quote'), {'security': 999999})

        self.assertEqual(missing_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_market_data_quote_api_returns_sanitized_provider_errors(self):
        self.authenticate()

        with patch(
            'market.views.get_security_latest_quote',
            side_effect=MarketDataRateLimited('Market data provider rate limit reached. Please try again later.'),
        ):
            rate_limit_response = self.client.get(reverse('market-data-quote'), {'security': self.security.id})

        with patch(
            'market.views.get_security_latest_quote',
            side_effect=MarketDataInvalidSymbol('Market data is not available for this security.'),
        ):
            invalid_symbol_response = self.client.get(reverse('market-data-quote'), {'security': self.security.id})

        self.assertEqual(rate_limit_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            rate_limit_response.data['detail'],
            'Market data provider rate limit reached. Please try again later.',
        )
        self.assertEqual(invalid_symbol_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            invalid_symbol_response.data['detail'],
            'Market data is not available for this security.',
        )

    def test_market_data_quotes_api_returns_batch_payload(self):
        self.authenticate()
        result = MarketDataQuoteResult(
            security=self.security,
            price=Decimal('198.12'),
            change=Decimal('-1.25'),
            percent_change=Decimal('-0.63'),
            currency='USD',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            as_of='2026-07-31',
        )

        with patch('market.views.get_security_latest_quotes', return_value=(result,)) as service_mock:
            response = self.client.get(reverse('market-data-quotes'), {'security_ids': str(self.security.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once()
        self.assertEqual(response.data['metadata']['requested_count'], 1)
        self.assertEqual(response.data['metadata']['returned_count'], 1)
        self.assertEqual(response.data['items'][0]['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['items'][0]['price'], '198.120000')
        self.assertEqual(response.data['items'][0]['data_status'], 'ok')

    def test_market_data_api_returns_project_owned_ohlcv_payload(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='3M',
            interval='1day',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
            values=[
                SecurityDailyPrice(
                    security=self.security,
                    date=date(2026, 7, 24),
                    open=Decimal('100'),
                    high=Decimal('102'),
                    low=Decimal('99'),
                    close=Decimal('101'),
                    volume=1000,
                ),
            ],
            warmup_values=(
                SecurityDailyPrice(
                    security=self.security,
                    date=date(2026, 7, 23),
                    open=Decimal('99'),
                    high=Decimal('101'),
                    low=Decimal('98'),
                    close=Decimal('100'),
                    volume=900,
                ),
            ),
        )

        with patch('market.views.get_security_daily_market_data', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-daily'), {'security': self.security.id, 'range': '3M'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once()
        self.assertEqual(response.data['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['range'], '3M')
        self.assertEqual(response.data['interval'], '1day')
        self.assertEqual(response.data['source'], SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(response.data['metadata']['security_id'], self.security.id)
        self.assertEqual(response.data['metadata']['symbol'], 'AAPL')
        self.assertEqual(response.data['metadata']['requested_range'], '3M')
        self.assertEqual(response.data['metadata']['interval'], '1day')
        self.assertEqual(response.data['metadata']['count'], 1)
        self.assertEqual(response.data['metadata']['warmup_count'], 1)
        self.assertEqual(response.data['metadata']['first_datetime'], '2026-07-24')
        self.assertEqual(response.data['metadata']['last_datetime'], '2026-07-24')
        self.assertEqual(response.data['metadata']['data_source'], 'twelve_data')
        self.assertEqual(response.data['metadata']['cache_status'], 'not_used')
        self.assertEqual(response.data['metadata']['is_stale'], False)
        self.assertEqual(response.data['metadata']['upstream_error'], '')
        self.assertEqual(response.data['data_source'], 'twelve_data')
        self.assertEqual(response.data['cache_status'], 'not_used')
        self.assertEqual(response.data['values'][0]['date'], '2026-07-24')
        self.assertEqual(response.data['values'][0]['open'], '100.000000')
        self.assertEqual(response.data['values'][0]['volume'], 1000)
        self.assertEqual(response.data['warmup_values'][0]['date'], '2026-07-23')
        self.assertEqual(response.data['warmup_values'][0]['close'], '100.000000')

    def test_market_data_api_returns_empty_ohlcv_contract(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='1Y',
            interval='1day',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
            values=[],
        )

        with patch('market.views.get_security_daily_market_data', return_value=result):
            response = self.client.get(
                reverse('market-data-daily'),
                {'security': self.security.id, 'range': '1Y'},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['values'], [])
        self.assertEqual(response.data['warmup_values'], [])
        self.assertEqual(response.data['metadata']['count'], 0)
        self.assertEqual(response.data['metadata']['record_count'], 0)
        self.assertEqual(response.data['metadata']['first_datetime'], '')
        self.assertEqual(response.data['metadata']['last_datetime'], '')
        self.assertEqual(response.data['metadata']['symbol'], 'AAPL')

    def test_market_data_api_passes_custom_dates_to_service(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='CUSTOM',
            interval='1day',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
            values=[],
        )

        with patch('market.views.get_security_daily_market_data', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-daily'), {
                'security_id': self.security.id,
                'range': 'Custom',
                'start_date': '2026-01-05',
                'end_date': '2026-01-10',
                'interval': '30m',
            })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(
            self.security,
            range_key='Custom',
            start_date='2026-01-05',
            end_date='2026-01-10',
            interval='30m',
            force_refresh=False,
        )

    @override_settings(DEBUG=True)
    def test_market_data_api_refresh_query_bypasses_cache_in_development(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='1D',
            interval='1min',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
            values=[],
        )

        with patch('market.views.get_security_daily_market_data', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-daily'), {
                'security_id': self.security.id,
                'range': '1D',
                'interval': '1min',
                'refresh': '1',
            })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(
            self.security,
            range_key='1D',
            start_date=None,
            end_date=None,
            interval='1min',
            force_refresh=True,
        )

    def test_market_data_api_exposes_stale_fallback_metadata(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='6M',
            interval='1day',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=True,
            data_source='stale_database_cache',
            cache_status='stale_fallback',
            last_updated='2026-07-29',
            upstream_error='Provider unavailable',
            fetched_at='2026-07-31T12:00:00+00:00',
            values=[
                SecurityDailyPrice(
                    security=self.security,
                    date=date(2026, 7, 29),
                    open=Decimal('100'),
                    high=Decimal('102'),
                    low=Decimal('99'),
                    close=Decimal('101'),
                    volume=1000,
                ),
            ],
        )

        with patch('market.views.get_security_daily_market_data', return_value=result):
            response = self.client.get(reverse('market-data-daily'), {'security_id': self.security.id, 'range': '6M'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_stale'])
        self.assertEqual(response.data['data_source'], 'stale_database_cache')
        self.assertEqual(response.data['cache_status'], 'stale_fallback')
        self.assertEqual(response.data['last_updated'], '2026-07-29')
        self.assertEqual(response.data['upstream_error'], 'Provider unavailable')
        self.assertEqual(response.data['metadata']['last_timestamp'], '2026-07-29')
        self.assertEqual(response.data['metadata']['upstream_error'], 'Provider unavailable')

    def test_market_data_api_rejects_unsupported_interval(self):
        self.authenticate()

        response = self.client.get(reverse('market-data-daily'), {
            'security': self.security.id,
            'range': '3M',
            'interval': '10min',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('interval', response.data)

    def test_market_data_api_rejects_overly_large_interval_range(self):
        self.authenticate()

        response = self.client.get(reverse('market-data-daily'), {
            'security': self.security.id,
            'range': '1Y',
            'interval': '30m',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('interval', response.data)

    def test_market_data_api_rejects_invalid_custom_dates(self):
        self.authenticate()

        response = self.client.get(reverse('market-data-daily'), {
            'security': self.security.id,
            'range': 'Custom',
            'start_date': '2026-01-11',
            'end_date': '2026-01-10',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_date', response.data)

    def test_market_data_api_rejects_unsupported_range(self):
        self.authenticate()

        response = self.client.get(reverse('market-data-daily'), {'security': self.security.id, 'range': 'YTD'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('range', response.data)
