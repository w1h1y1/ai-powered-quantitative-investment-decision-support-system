from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security
from watchlist.models import Watchlist, WatchlistItem

from .models import Holding, Portfolio, TradeTransaction


PROTECTED_LIST_ROUTES = [
    'security-list',
    'portfolio-list',
    'holding-list',
    'transaction-list',
    'watchlist-list',
    'watchlist-item-list',
]


class CoreApiPermissionTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='user_a', password='pass')
        self.user_b = User.objects.create_user(username='user_b', password='pass')
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
        self.portfolio_a = Portfolio.objects.create(
            user=self.user_a,
            name='User A Portfolio',
            available_funds=Decimal('10000.00'),
            base_currency='USD',
        )
        self.portfolio_b = Portfolio.objects.create(
            user=self.user_b,
            name='User B Portfolio',
            available_funds=Decimal('5000.00'),
            base_currency='USD',
        )
        self.holding_a = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('3.000000'),
            average_cost=Decimal('175.0000'),
        )
        self.holding_b = Holding.objects.create(
            portfolio=self.portfolio_b,
            security=self.security_b,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('300.0000'),
        )
        self.transaction_a = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('3.000000'),
            price=Decimal('175.0000'),
            fee=Decimal('1.00'),
            transaction_date=timezone.now(),
            notes='User A buy',
        )
        self.transaction_b = TradeTransaction.objects.create(
            portfolio=self.portfolio_b,
            security=self.security_b,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('300.0000'),
            fee=Decimal('1.00'),
            transaction_date=timezone.now(),
            notes='User B buy',
        )
        self.watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        self.watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        self.watchlist_item_a = WatchlistItem.objects.create(
            watchlist=self.watchlist_a,
            security=self.security_a,
        )
        self.watchlist_item_b = WatchlistItem.objects.create(
            watchlist=self.watchlist_b,
            security=self.security_b,
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user)

    def assert_protected_response(self, response):
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_anonymous_user_cannot_access_protected_list_endpoints(self):
        for route_name in PROTECTED_LIST_ROUTES:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assert_protected_response(response)

    def test_user_a_and_user_b_only_list_their_own_portfolios(self):
        self.authenticate_as(self.user_a)
        user_a_response = self.client.get(reverse('portfolio-list'))

        self.authenticate_as(self.user_b)
        user_b_response = self.client.get(reverse('portfolio-list'))

        self.assertEqual(user_a_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in user_a_response.data], [self.portfolio_a.id])
        self.assertEqual(user_b_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in user_b_response.data], [self.portfolio_b.id])
        self.assertNotIn('user', user_a_response.data[0])

    def test_user_a_cannot_access_modify_or_delete_user_b_portfolio(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('portfolio-detail', args=[self.portfolio_b.id]))
        patch_response = self.client.patch(
            reverse('portfolio-detail', args=[self.portfolio_b.id]),
            {'name': 'Compromised'},
            format='json',
        )
        delete_response = self.client.delete(reverse('portfolio-detail', args=[self.portfolio_b.id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.portfolio_b.refresh_from_db()
        self.assertEqual(self.portfolio_b.name, 'User B Portfolio')

    def test_creating_portfolio_for_existing_user_returns_existing_primary_portfolio(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('portfolio-list'),
            {
                'user': self.user_b.id,
                'name': 'User A New Portfolio',
                'description': 'Created through API',
                'available_funds': '2500.00',
                'base_currency': 'USD',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.portfolio_a.id)
        self.assertEqual(Portfolio.objects.filter(user=self.user_a).count(), 1)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.name, 'User A Portfolio')

    def test_creating_portfolio_for_user_without_portfolio_creates_one_primary_portfolio(self):
        User = get_user_model()
        user_c = User.objects.create_user(username='user_c', password='pass')
        self.authenticate_as(user_c)

        response = self.client.post(
            reverse('portfolio-list'),
            {
                'user': self.user_b.id,
                'name': 'User C Portfolio',
                'description': 'Created through API',
                'available_funds': '2500.00',
                'base_currency': 'USD',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        portfolio = Portfolio.objects.get(user=user_c)
        self.assertEqual(response.data['id'], portfolio.id)
        self.assertEqual(portfolio.name, 'User C Portfolio')
        self.assertEqual(Portfolio.objects.filter(user=user_c).count(), 1)

    def test_user_a_can_only_list_their_own_holdings(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('holding-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [self.holding_a.id])
        self.assertEqual(response.data[0]['security']['symbol'], 'AAPL')
        self.assertNotIn('security_id', response.data[0])

    def test_two_users_have_separate_primary_portfolios_and_holdings(self):
        self.assertNotEqual(self.portfolio_a.id, self.portfolio_b.id)
        self.assertEqual(self.holding_a.portfolio, self.portfolio_a)
        self.assertEqual(self.holding_b.portfolio, self.portfolio_b)

        self.authenticate_as(self.user_a)
        user_a_response = self.client.get(reverse('holding-list'))

        self.authenticate_as(self.user_b)
        user_b_response = self.client.get(reverse('holding-list'))

        self.assertEqual([item['id'] for item in user_a_response.data], [self.holding_a.id])
        self.assertEqual([item['id'] for item in user_b_response.data], [self.holding_b.id])

    def test_user_a_cannot_access_modify_or_delete_user_b_holding(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('holding-detail', args=[self.holding_b.id]))
        patch_response = self.client.patch(
            reverse('holding-detail', args=[self.holding_b.id]),
            {'quantity': '9.000000'},
            format='json',
        )
        delete_response = self.client.delete(reverse('holding-detail', args=[self.holding_b.id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Holding.objects.filter(id=self.holding_b.id).exists())

    def test_user_a_cannot_create_holding_for_user_b_portfolio(self):
        self.authenticate_as(self.user_a)
        security_c = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            currency='USD',
        )

        response = self.client.post(
            reverse('holding-list'),
            {
                'portfolio': self.portfolio_b.id,
                'security': security_c.id,
                'quantity': '1.000000',
                'average_cost': '180.0000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('portfolio', response.data)
        self.assertFalse(
            Holding.objects.filter(portfolio=self.portfolio_b, security=security_c).exists()
        )
        self.assertFalse(
            Holding.objects.filter(portfolio=self.portfolio_a, security=security_c).exists()
        )

    def test_user_a_can_create_holding_for_own_portfolio_with_valid_security(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('holding-list'),
            {
                'security': self.security_b.id,
                'quantity': '1.250000',
                'average_cost': '320.5000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        holding = Holding.objects.get(id=response.data['id'])
        self.assertEqual(holding.portfolio, self.portfolio_a)
        self.assertEqual(holding.security, self.security_b)

    def test_user_a_cannot_create_holding_with_invalid_security(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('holding-list'),
            {
                'security': 999999,
                'quantity': '1.000000',
                'average_cost': '180.0000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('security_id', response.data)
        self.assertEqual(Holding.objects.filter(portfolio=self.portfolio_a).count(), 1)

    def test_creating_holding_without_existing_portfolio_creates_primary_portfolio(self):
        User = get_user_model()
        user_c = User.objects.create_user(username='user_c', password='pass')
        self.authenticate_as(user_c)

        response = self.client.post(
            reverse('holding-list'),
            {
                'security': self.security_a.id,
                'quantity': '1.000000',
                'average_cost': '180.0000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        portfolio = Portfolio.objects.get(user=user_c)
        holding = Holding.objects.get(id=response.data['id'])
        self.assertEqual(holding.portfolio, portfolio)
        self.assertEqual(portfolio.name, 'My Portfolio')
        self.assertEqual(Portfolio.objects.filter(user=user_c).count(), 1)

    def test_user_a_cannot_patch_own_holding_to_user_b_portfolio(self):
        self.authenticate_as(self.user_a)

        response = self.client.patch(
            reverse('holding-detail', args=[self.holding_a.id]),
            {'portfolio': self.portfolio_b.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.holding_a.refresh_from_db()
        self.assertEqual(self.holding_a.portfolio, self.portfolio_a)

    def test_user_a_can_update_and_delete_own_holding(self):
        self.authenticate_as(self.user_a)

        patch_response = self.client.patch(
            reverse('holding-detail', args=[self.holding_a.id]),
            {
                'quantity': '4.500000',
                'average_cost': '181.2500',
            },
            format='json',
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.holding_a.refresh_from_db()
        self.assertEqual(self.holding_a.quantity, Decimal('4.500000'))
        self.assertEqual(self.holding_a.average_cost, Decimal('181.2500'))

        delete_response = self.client.delete(reverse('holding-detail', args=[self.holding_a.id]))

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Holding.objects.filter(id=self.holding_a.id).exists())

    def test_user_a_can_only_list_their_own_transactions(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [self.transaction_a.id])
        self.assertEqual(response.data[0]['security']['symbol'], 'AAPL')

    def test_user_a_cannot_access_modify_or_delete_user_b_transaction(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('transaction-detail', args=[self.transaction_b.id]))
        patch_response = self.client.patch(
            reverse('transaction-detail', args=[self.transaction_b.id]),
            {'notes': 'Compromised'},
            format='json',
        )
        delete_response = self.client.delete(reverse('transaction-detail', args=[self.transaction_b.id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.transaction_b.refresh_from_db()
        self.assertEqual(self.transaction_b.notes, 'User B buy')

    def test_user_a_cannot_create_transaction_for_user_b_portfolio(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            {
                'portfolio': self.portfolio_b.id,
                'security_id': self.security_a.id,
                'transaction_type': TradeTransaction.TransactionType.BUY,
                'quantity': '1.000000',
                'price': '180.0000',
                'fee': '0.00',
                'transaction_date': timezone.now().isoformat(),
                'notes': '',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            TradeTransaction.objects.filter(portfolio=self.portfolio_b, security=self.security_a).exists()
        )

    def test_user_a_cannot_patch_own_transaction_to_user_b_portfolio(self):
        self.authenticate_as(self.user_a)

        response = self.client.patch(
            reverse('transaction-detail', args=[self.transaction_a.id]),
            {'portfolio': self.portfolio_b.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.transaction_a.refresh_from_db()
        self.assertEqual(self.transaction_a.portfolio, self.portfolio_a)

    def test_user_a_can_only_list_their_own_watchlists(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [self.watchlist_a.id])

    def test_user_a_cannot_access_modify_or_delete_user_b_watchlist(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('watchlist-detail', args=[self.watchlist_b.id]))
        patch_response = self.client.patch(
            reverse('watchlist-detail', args=[self.watchlist_b.id]),
            {'name': 'Compromised'},
            format='json',
        )
        delete_response = self.client.delete(reverse('watchlist-detail', args=[self.watchlist_b.id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.watchlist_b.refresh_from_db()
        self.assertEqual(self.watchlist_b.name, 'User B Watchlist')

    def test_creating_watchlist_ignores_submitted_user_and_sets_request_user(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-list'),
            {'user': self.user_b.id, 'name': 'User A New Watchlist'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        watchlist = Watchlist.objects.get(id=response.data['id'])
        self.assertEqual(watchlist.user, self.user_a)

    def test_user_a_can_only_list_their_own_watchlist_items(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-item-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [self.watchlist_item_a.id])
        self.assertEqual(response.data[0]['security']['symbol'], 'AAPL')

    def test_user_a_cannot_access_modify_or_delete_user_b_watchlist_item(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(
            reverse('watchlist-item-detail', args=[self.watchlist_item_b.id])
        )
        patch_response = self.client.patch(
            reverse('watchlist-item-detail', args=[self.watchlist_item_b.id]),
            {'watchlist': self.watchlist_a.id},
            format='json',
        )
        delete_response = self.client.delete(
            reverse('watchlist-item-detail', args=[self.watchlist_item_b.id])
        )

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WatchlistItem.objects.filter(id=self.watchlist_item_b.id).exists())

    def test_user_a_cannot_add_security_to_user_b_watchlist(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-item-list'),
            {
                'watchlist': self.watchlist_b.id,
                'security_id': self.security_a.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            WatchlistItem.objects.filter(watchlist=self.watchlist_b, security=self.security_a).exists()
        )

    def test_user_a_cannot_patch_own_watchlist_item_to_user_b_watchlist(self):
        self.authenticate_as(self.user_a)

        response = self.client.patch(
            reverse('watchlist-item-detail', args=[self.watchlist_item_a.id]),
            {'watchlist': self.watchlist_b.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.watchlist_item_a.refresh_from_db()
        self.assertEqual(self.watchlist_item_a.watchlist, self.watchlist_a)

    def test_watchlist_detail_returns_nested_security_items_for_owner_only(self):
        self.authenticate_as(self.user_a)

        own_response = self.client.get(reverse('watchlist-detail', args=[self.watchlist_a.id]))
        other_response = self.client.get(reverse('watchlist-detail', args=[self.watchlist_b.id]))

        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertEqual(own_response.data['name'], 'User A Watchlist')
        self.assertEqual(len(own_response.data['items']), 1)
        self.assertEqual(own_response.data['items'][0]['security']['symbol'], 'AAPL')
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authenticated_user_can_read_security_list_and_detail(self):
        self.authenticate_as(self.user_a)

        list_response = self.client.get(reverse('security-list'))
        detail_response = self.client.get(reverse('security-detail', args=[self.security_a.id]))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual({item['symbol'] for item in list_response.data}, {'AAPL', 'MSFT'})
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['symbol'], 'AAPL')

    def test_regular_user_cannot_create_update_or_delete_security(self):
        self.authenticate_as(self.user_a)

        create_response = self.client.post(
            reverse('security-list'),
            {
                'symbol': 'NVDA',
                'name': 'NVIDIA Corporation',
                'asset_type': Security.AssetType.STOCK,
                'exchange': 'NASDAQ',
                'currency': 'USD',
                'is_active': True,
            },
            format='json',
        )
        put_response = self.client.put(
            reverse('security-detail', args=[self.security_a.id]),
            {
                'symbol': 'AAPL',
                'name': 'Changed Name',
                'asset_type': Security.AssetType.STOCK,
                'exchange': 'NASDAQ',
                'currency': 'USD',
                'is_active': True,
            },
            format='json',
        )
        patch_response = self.client.patch(
            reverse('security-detail', args=[self.security_a.id]),
            {'name': 'Changed Name'},
            format='json',
        )
        delete_response = self.client.delete(reverse('security-detail', args=[self.security_a.id]))

        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(put_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(patch_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(delete_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.security_a.refresh_from_db()
        self.assertEqual(self.security_a.name, 'Apple Inc.')

    def test_security_search_by_symbol_name_and_exchange(self):
        self.authenticate_as(self.user_a)

        symbol_response = self.client.get(reverse('security-list'), {'search': 'aap'})
        name_response = self.client.get(reverse('security-list'), {'search': 'Microsoft'})
        exchange_response = self.client.get(reverse('security-list'), {'search': 'NASDAQ'})

        self.assertEqual(symbol_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['symbol'] for item in symbol_response.data], ['AAPL'])
        self.assertEqual(name_response.data[0]['symbol'], 'MSFT')
        self.assertEqual(len(exchange_response.data), 2)
