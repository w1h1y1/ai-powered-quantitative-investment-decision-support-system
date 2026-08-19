from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security, SecurityDailyPrice
from market.services import MarketDataQuoteResult, MarketDataRateLimited, MarketDataResult

from portfolio.models import Holding, Portfolio, TradeTransaction

from .models import Watchlist, WatchlistItem


class WatchlistApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user_a = User.objects.create_user(username='watch_api_user_a', password='pass')
        self.user_b = User.objects.create_user(username='watch_api_user_b', password='pass')
        self.security_a = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.security_b = Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_list_creates_default_watchlist_for_authenticated_user(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Watchlist.objects.filter(user=self.user_a).count(), 1)
        watchlist = Watchlist.objects.get(user=self.user_a)
        self.assertEqual(watchlist.name, 'My Watchlist')
        self.assertEqual(response.data[0]['id'], watchlist.id)
        self.assertEqual(response.data[0]['items'], [])

    def test_watchlist_list_only_returns_current_users_records(self):
        watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [watchlist_a.id])

    def test_watchlist_item_list_can_be_filtered_to_current_users_watchlist(self):
        watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        item_a = WatchlistItem.objects.create(watchlist=watchlist_a, security=self.security_a)
        WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        self.authenticate_as(self.user_a)

        own_response = self.client.get(reverse('watchlist-item-list'), {'watchlist': watchlist_a.id})
        other_response = self.client.get(reverse('watchlist-item-list'), {'watchlist': watchlist_b.id})

        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in own_response.data], [item_a.id])
        self.assertEqual(other_response.status_code, status.HTTP_200_OK)
        self.assertEqual(other_response.data, [])

    def test_watchlist_item_list_without_filter_only_returns_current_users_items(self):
        watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        item_a = WatchlistItem.objects.create(watchlist=watchlist_a, security=self.security_a)
        WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-item-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [item_a.id])

    def test_user_can_create_watchlist_item_in_own_watchlist_without_user_field(self):
        watchlist = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-item-list'),
            {
                'watchlist': watchlist.id,
                'security_id': self.security_a.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['watchlist'], watchlist.id)
        self.assertEqual(response.data['security']['id'], self.security_a.id)
        self.assertEqual(WatchlistItem.objects.get().watchlist.user, self.user_a)

    def test_user_cannot_create_item_in_another_users_watchlist(self):
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-item-list'),
            {
                'watchlist': watchlist_b.id,
                'security_id': self.security_a.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('watchlist', response.data)
        self.assertFalse(WatchlistItem.objects.exists())

    def test_duplicate_security_in_same_watchlist_returns_validation_error(self):
        watchlist = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist, security=self.security_a)
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-item-list'),
            {
                'watchlist': watchlist.id,
                'security_id': self.security_a.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('security_id', response.data)
        self.assertEqual(
            response.data['security_id'][0],
            'This security is already in this watchlist.',
        )
        self.assertEqual(WatchlistItem.objects.filter(watchlist=watchlist).count(), 1)

    def test_add_symbol_creates_security_and_adds_current_users_watchlist_item(self):
        self.authenticate_as(self.user_a)
        search_payload = {
            'query': 'Broadcom',
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
                },
            ],
        }

        with patch('watchlist.services.search_security_symbols', return_value=search_payload) as search_mock:
            response = self.client.post(
                reverse('watchlist-add-symbol'),
                {
                    'symbol': 'AVGO',
                    'name': 'Broadcom Inc.',
                    'exchange': 'NASDAQ',
                    'mic_code': 'XNAS',
                    'instrument_type': 'Common Stock',
                    'country': 'United States',
                    'currency': 'USD',
                    'search_query': 'Broadcom',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        security = Security.objects.get(symbol='AVGO', mic_code='XNAS')
        self.assertEqual(security.name, 'Broadcom Inc.')
        self.assertEqual(security.country, 'United States')
        self.assertEqual(response.data['security']['id'], security.id)
        self.assertEqual(response.data['status'], 'added')
        self.assertTrue(response.data['created_security'])
        self.assertTrue(WatchlistItem.objects.filter(watchlist__user=self.user_a, security=security).exists())
        search_mock.assert_called_once_with('Broadcom')

    def test_add_symbol_reuses_existing_security_and_preserves_user_isolation(self):
        existing_security = Security.objects.create(
            symbol='AVGO',
            name='Broadcom Existing',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist_b, security=existing_security)
        self.authenticate_as(self.user_a)
        search_payload = {
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
                },
            ],
        }

        with patch('watchlist.services.search_security_symbols', return_value=search_payload):
            response = self.client.post(
                reverse('watchlist-add-symbol'),
                {
                    'symbol': 'AVGO',
                    'name': 'Broadcom Inc.',
                    'exchange': 'NASDAQ',
                    'mic_code': 'XNAS',
                    'instrument_type': 'Common Stock',
                    'country': 'United States',
                    'currency': 'USD',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        existing_security.refresh_from_db()
        self.assertEqual(Security.objects.filter(symbol='AVGO').count(), 1)
        self.assertEqual(existing_security.mic_code, 'XNAS')
        self.assertEqual(response.data['security']['id'], existing_security.id)
        self.assertFalse(response.data['created_security'])
        self.assertTrue(WatchlistItem.objects.filter(watchlist__user=self.user_a, security=existing_security).exists())
        self.assertTrue(WatchlistItem.objects.filter(watchlist__user=self.user_b, security=existing_security).exists())

    def test_add_symbol_returns_already_tracked_without_duplicate_item(self):
        watchlist = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist, security=self.security_a)
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-add-symbol'),
            {
                'id': self.security_a.id,
                'symbol': 'AAPL',
                'name': 'Apple Inc.',
                'exchange': 'NASDAQ',
                'mic_code': 'XNAS',
                'instrument_type': 'Common Stock',
                'country': 'United States',
                'currency': 'USD',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'already_tracked')
        self.assertFalse(response.data['created_item'])
        self.assertEqual(WatchlistItem.objects.filter(watchlist=watchlist, security=self.security_a).count(), 1)

    def test_add_symbol_does_not_modify_portfolio_state(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='User A Portfolio',
            available_funds=Decimal('5000.00'),
            initial_balance=Decimal('5000.00'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            quantity=Decimal('10.000000'),
            average_cost=Decimal('150.0000'),
        )
        self.authenticate_as(self.user_a)
        search_payload = {
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
                },
            ],
        }

        with patch('watchlist.services.search_security_symbols', return_value=search_payload):
            response = self.client.post(
                reverse('watchlist-add-symbol'),
                {
                    'symbol': 'AVGO',
                    'name': 'Broadcom Inc.',
                    'exchange': 'NASDAQ',
                    'mic_code': 'XNAS',
                    'instrument_type': 'Common Stock',
                    'country': 'United States',
                    'currency': 'USD',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        portfolio.refresh_from_db()
        self.assertEqual(portfolio.available_funds, Decimal('5000.00'))
        self.assertEqual(portfolio.holdings.count(), 1)
        self.assertEqual(portfolio.holdings.get().security.symbol, 'AAPL')
        self.assertEqual(portfolio.trade_transactions.count(), 0)
        self.assertEqual(portfolio.cash_flows.count(), 0)

    def test_add_symbol_preserves_market_data_rate_limit_error(self):
        self.authenticate_as(self.user_a)

        with patch(
            'watchlist.services.search_security_symbols',
            side_effect=MarketDataRateLimited('Market data provider rate limit reached.'),
        ):
            response = self.client.post(
                reverse('watchlist-add-symbol'),
                {
                    'symbol': 'AVGO',
                    'name': 'Broadcom Inc.',
                    'exchange': 'NASDAQ',
                    'mic_code': 'XNAS',
                    'instrument_type': 'Common Stock',
                    'country': 'United States',
                    'currency': 'USD',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data['detail'], 'Market data provider rate limit reached.')
        self.assertFalse(Security.objects.filter(symbol='AVGO').exists())

    def test_user_cannot_delete_another_users_watchlist_item(self):
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        item_b = WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        self.authenticate_as(self.user_a)

        response = self.client.delete(reverse('watchlist-item-detail', args=[item_b.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WatchlistItem.objects.filter(id=item_b.id).exists())

    def test_watchlist_summary_requires_authentication(self):
        response = self.client.get(reverse('watchlist-summary'))

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_watchlist_summary_returns_current_user_quote_and_history(self):
        watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        item_a = WatchlistItem.objects.create(watchlist=watchlist_a, security=self.security_a)
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        quote_result = MarketDataQuoteResult(
            security=self.security_a,
            price=Decimal('198.12'),
            change=Decimal('1.50'),
            percent_change=Decimal('0.76'),
            currency='USD',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            as_of='2026-07-31',
        )
        market_data_result = MarketDataResult(
            security=self.security_a,
            range_key='3M',
            interval='1day',
            values=[
                SimpleNamespace(date=date(2026, 7, 29), close=Decimal('194.00')),
                SimpleNamespace(date=date(2026, 7, 30), close=Decimal('196.00')),
                SimpleNamespace(date=date(2026, 7, 31), close=Decimal('198.12')),
            ],
            warmup_values=[
                SimpleNamespace(date=date(2026, 7, 28), close=Decimal('193.00')),
            ],
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            data_source='database_cache',
            cache_status='hit',
        )
        self.authenticate_as(self.user_a)

        with (
            patch('watchlist.services.get_security_latest_quotes', return_value=(quote_result,)) as quotes_mock,
            patch('watchlist.services.get_security_daily_market_data', return_value=market_data_result) as history_mock,
        ):
            response = self.client.get(reverse('watchlist-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['watchlist']['id'], watchlist_a.id)
        self.assertEqual(response.data['metadata']['item_count'], 1)
        self.assertEqual(response.data['watchlist_items'][0]['id'], item_a.id)
        self.assertEqual(response.data['items'][0]['security']['symbol'], 'AAPL')
        self.assertEqual(response.data['items'][0]['quote']['price'], '198.120000')
        self.assertEqual(response.data['items'][0]['quote']['percent_change'], '0.760000')
        self.assertEqual(
            [point['close'] for point in response.data['items'][0]['history']['mini_trend']],
            ['194.000000', '196.000000', '198.120000'],
        )
        self.assertEqual(response.data['items'][0]['history']['indicator_closes'][0]['close'], '193.000000')
        self.assertEqual(response.data['items'][0]['history']['cache_status'], 'hit')
        self.assertEqual(quotes_mock.call_count, 1)
        self.assertEqual([security.id for security in quotes_mock.call_args.args[0]], [self.security_a.id])
        history_mock.assert_called_once_with(
            self.security_a,
            range_key='3M',
            interval='1day',
            force_refresh=False,
        )

    def test_watchlist_summary_uses_ttl_cache_for_repeated_requests(self):
        watchlist = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist, security=self.security_a)
        quote_result = MarketDataQuoteResult(
            security=self.security_a,
            price=Decimal('198.12'),
            change=Decimal('1.50'),
            percent_change=Decimal('0.76'),
            currency='USD',
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            as_of='2026-07-31',
        )
        market_data_result = MarketDataResult(
            security=self.security_a,
            range_key='3M',
            interval='1day',
            values=[SimpleNamespace(date=date(2026, 7, 31), close=Decimal('198.12'))],
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            cache_status='hit',
        )
        self.authenticate_as(self.user_a)

        with (
            patch('watchlist.services.get_security_latest_quotes', return_value=(quote_result,)) as quotes_mock,
            patch('watchlist.services.get_security_daily_market_data', return_value=market_data_result) as history_mock,
        ):
            first_response = self.client.get(reverse('watchlist-summary'))
            second_response = self.client.get(reverse('watchlist-summary'))

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data['cache_status'], 'fresh')
        self.assertEqual(second_response.data['cache_status'], 'hit')
        quotes_mock.assert_called_once()
        history_mock.assert_called_once()
