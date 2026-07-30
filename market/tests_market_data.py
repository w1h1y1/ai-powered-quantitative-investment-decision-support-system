from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Security, SecurityDailyPrice
from .services import (
    MARKET_DATA_FETCH_START_BUFFER_DAYS,
    InvalidMarketDataDateRange,
    MarketDataResult,
    get_range_date_window,
    get_security_daily_market_data,
)
from .twelve_data import TwelveDataError, parse_bar


@dataclass(frozen=True)
class FakeDailyBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class FakeTwelveDataClient:
    def __init__(self, bars=None, error=None):
        self.bars = bars or []
        self.error = error
        self.calls = []

    def get_daily_time_series(self, symbol, start_date=None, end_date=None, outputsize=None):
        self.calls.append({
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'outputsize': outputsize,
        })
        if self.error:
            raise self.error
        bars = self.bars
        if start_date is not None:
            bars = [bar for bar in bars if bar.date >= start_date]
        if end_date is not None:
            bars = [bar for bar in bars if bar.date <= end_date]
        if outputsize is not None:
            bars = bars[-outputsize:]
        return bars


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
    if range_key == '1M':
        return subtract_months_for_test(today, 1)
    if range_key == '3M':
        return subtract_months_for_test(today, 3)
    if range_key == '6M':
        return subtract_months_for_test(today, 6)
    if range_key == 'YTD':
        return date(today.year, 1, 1)
    if range_key == '1Y':
        return subtract_years_for_test(today, 1)
    if range_key == '3Y':
        return subtract_years_for_test(today, 3)
    if range_key == '5Y':
        return subtract_years_for_test(today, 5)
    raise AssertionError(f'Unsupported test range {range_key}')


def expected_provider_start(range_key, today):
    return expected_range_start(range_key, today) - timedelta(days=MARKET_DATA_FETCH_START_BUFFER_DAYS)


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


class MarketDataDateRangeTests(TestCase):
    @patch('market.services.timezone.localdate', return_value=date(2026, 7, 30))
    def test_supported_ranges_convert_to_expected_date_windows(self, localdate_mock):
        expected_windows = {
            '1M': (date(2026, 6, 30), date(2026, 7, 30)),
            '3M': (date(2026, 4, 30), date(2026, 7, 30)),
            '6M': (date(2026, 1, 30), date(2026, 7, 30)),
            'YTD': (date(2026, 1, 1), date(2026, 7, 30)),
            '1Y': (date(2025, 7, 30), date(2026, 7, 30)),
            '3Y': (date(2023, 7, 30), date(2026, 7, 30)),
            '5Y': (date(2021, 7, 30), date(2026, 7, 30)),
        }

        for range_key, expected_window in expected_windows.items():
            with self.subTest(range_key=range_key):
                self.assertEqual(get_range_date_window(range_key), expected_window)

    @patch('market.services.timezone.localdate', return_value=date(2026, 7, 30))
    def test_ytd_starts_on_first_day_of_current_year(self, localdate_mock):
        start_date, end_date = get_range_date_window('YTD')

        self.assertEqual(start_date, date(2026, 1, 1))
        self.assertEqual(end_date, date(2026, 7, 30))

    @patch('market.services.timezone.localdate', return_value=date(2026, 7, 30))
    def test_custom_date_range_validation(self, localdate_mock):
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
        today = timezone.localdate()
        client = FakeTwelveDataClient(bars=[
            FakeDailyBar(today - timedelta(days=2), Decimal('100'), Decimal('102'), Decimal('99'), Decimal('101'), 1000),
            FakeDailyBar(today - timedelta(days=1), Decimal('101'), Decimal('103'), Decimal('100'), Decimal('102'), 1100),
        ])

        result = get_security_daily_market_data(security, range_key='3M', client=client)

        self.assertEqual(client.calls[0]['symbol'], 'AAPL')
        self.assertEqual(client.calls[0]['start_date'], expected_provider_start('3M', today))
        self.assertEqual(client.calls[0]['end_date'], today)
        self.assertIsNone(client.calls[0]['outputsize'])
        self.assertEqual(result.range_key, '3M')
        self.assertEqual(len(result.values), 2)
        self.assertEqual(SecurityDailyPrice.objects.filter(security=security).count(), 2)
        cached_price = SecurityDailyPrice.objects.get(security=security, date=today - timedelta(days=1))
        self.assertEqual(cached_price.close, Decimal('102.000000'))

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=3600)
    def test_uses_fresh_cached_prices_without_provider_call(self):
        security = make_security()
        today = timezone.localdate()
        SecurityDailyPrice.objects.create(
            security=security,
            date=expected_range_start('3M', today),
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
        client = FakeTwelveDataClient(error=AssertionError('Provider should not be called.'))

        result = get_security_daily_market_data(security, range_key='3M', client=client)

        self.assertEqual(len(result.values), 2)
        self.assertEqual(client.calls, [])
        self.assertFalse(result.is_stale)

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=0)
    def test_returns_stale_cache_when_provider_fails(self):
        security = make_security()
        today = timezone.localdate()
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

        result = get_security_daily_market_data(security, range_key='3M', client=client)

        self.assertEqual(len(result.values), 1)
        self.assertTrue(result.is_stale)

    def test_requested_ranges_fetch_dates_covering_requested_windows(self):
        today = timezone.localdate()
        all_bars = make_daily_bars(today - timedelta(days=1900), today)
        minimum_ages = {
            '1M': 25,
            '3M': 90,
            '6M': 180,
            'YTD': max((today - date(today.year, 1, 1)).days - 1, 0),
            '1Y': 360,
            '3Y': 1090,
            '5Y': 1820,
        }

        for range_key, minimum_age in minimum_ages.items():
            with self.subTest(range_key=range_key):
                security = make_security(symbol=f'SEC{range_key}')
                client = FakeTwelveDataClient(bars=all_bars)

                result = get_security_daily_market_data(security, range_key=range_key, client=client)

                self.assertEqual(client.calls[0]['start_date'], expected_provider_start(range_key, today))
                self.assertEqual(client.calls[0]['end_date'], today)
                self.assertEqual(result.values[0].date, expected_range_start(range_key, today))
                self.assertEqual(result.values[-1].date, today)
                self.assertGreaterEqual((today - result.values[0].date).days, minimum_age)

    def test_expands_cached_data_when_switching_from_three_months_to_one_year(self):
        security = make_security(symbol='MSFT')
        today = timezone.localdate()
        all_bars = make_daily_bars(today - timedelta(days=400), today)

        three_month_client = FakeTwelveDataClient(bars=all_bars)
        three_month_result = get_security_daily_market_data(
            security,
            range_key='3M',
            client=three_month_client,
        )
        count_after_three_months = SecurityDailyPrice.objects.filter(security=security).count()

        one_year_client = FakeTwelveDataClient(bars=all_bars)
        one_year_result = get_security_daily_market_data(
            security,
            range_key='1Y',
            client=one_year_client,
        )

        self.assertEqual(len(one_year_client.calls), 1)
        self.assertEqual(one_year_client.calls[0]['start_date'], expected_provider_start('1Y', today))
        self.assertLess(
            SecurityDailyPrice.objects.filter(security=security).earliest('date').date,
            expected_range_start('1Y', today),
        )
        self.assertGreater(SecurityDailyPrice.objects.filter(security=security).count(), count_after_three_months)
        self.assertEqual(one_year_result.values[0].date, expected_range_start('1Y', today))
        self.assertGreater(len(one_year_result.values), len(three_month_result.values) * 3)

    def test_expands_cached_data_for_three_and_five_year_ranges(self):
        today = timezone.localdate()
        all_bars = make_daily_bars(today - timedelta(days=1900), today)

        for range_key in ['3Y', '5Y']:
            with self.subTest(range_key=range_key):
                security = make_security(symbol=f'H{range_key}')
                get_security_daily_market_data(
                    security,
                    range_key='3M',
                    client=FakeTwelveDataClient(bars=all_bars),
                )
                count_after_three_months = SecurityDailyPrice.objects.filter(security=security).count()
                client = FakeTwelveDataClient(bars=all_bars)

                result = get_security_daily_market_data(
                    security,
                    range_key=range_key,
                    client=client,
                )

                self.assertEqual(len(client.calls), 1)
                self.assertEqual(client.calls[0]['start_date'], expected_provider_start(range_key, today))
                self.assertGreater(SecurityDailyPrice.objects.filter(security=security).count(), count_after_three_months)
                self.assertEqual(result.values[0].date, expected_range_start(range_key, today))
                self.assertGreater(len(result.values), count_after_three_months)

    @override_settings(MARKET_DATA_CACHE_TTL_SECONDS=0)
    def test_repeated_fetches_upsert_without_duplicate_daily_prices(self):
        security = make_security(symbol='GOOG')
        today = timezone.localdate()
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

    def test_market_data_api_returns_project_owned_ohlcv_payload(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='3M',
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
        )

        with patch('market.views.get_security_daily_market_data', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-daily'), {'security': self.security.id, 'range': '3M'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once()
        self.assertEqual(response.data['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['range'], '3M')
        self.assertEqual(response.data['source'], SecurityDailyPrice.SOURCE_TWELVE_DATA)
        self.assertEqual(response.data['values'][0]['date'], '2026-07-24')
        self.assertEqual(response.data['values'][0]['open'], '100.000000')
        self.assertEqual(response.data['values'][0]['volume'], 1000)

    def test_market_data_api_passes_custom_dates_to_service(self):
        self.authenticate()
        result = MarketDataResult(
            security=self.security,
            range_key='CUSTOM',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
            values=[],
        )

        with patch('market.views.get_security_daily_market_data', return_value=result) as service_mock:
            response = self.client.get(reverse('market-data-daily'), {
                'security': self.security.id,
                'range': 'Custom',
                'start_date': '2026-01-05',
                'end_date': '2026-01-10',
            })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(
            self.security,
            range_key='Custom',
            start_date='2026-01-05',
            end_date='2026-01-10',
        )

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

        response = self.client.get(reverse('market-data-daily'), {'security': self.security.id, 'range': '1D'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('range', response.data)
