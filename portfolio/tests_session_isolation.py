from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from .models import Holding, Portfolio


class SessionSwitchingIsolationTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='switch_user_a', password='StrongPassword123')
        self.user_b = User.objects.create_user(username='switch_user_b', password='StrongPassword123')
        self.msft = Security.objects.create(
            symbol='MSFT',
            name='Microsoft',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.spy = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            currency='USD',
        )
        self.quote_patch = patch('portfolio.services.get_security_latest_quotes', return_value=())
        self.quote_patch.start()
        self.addCleanup(self.quote_patch.stop)

    def login_as(self, username):
        response = self.client.post(
            reverse('auth-login'),
            {'username': username, 'password': 'StrongPassword123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}",
        )
        me_response = self.client.get(reverse('auth-me'))
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data['username'], username)
        self.assertIs(me_response.data['is_authenticated'], True)
        return response

    def logout(self):
        response = self.client.post(reverse('auth-logout'))
        self.client.credentials()
        return response

    def create_holding(self, security, quantity='1.000000', average_price='100.0000'):
        response = self.client.post(
            reverse('holding-list'),
            {
                'security': security.id,
                'quantity': quantity,
                'average_price': average_price,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def assert_holdings_symbols(self, expected_symbols):
        response = self.client.get(reverse('holding-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item['security']['symbol'] for item in response.data],
            expected_symbols,
        )
        return response

    def assert_summary_symbols(self, expected_symbols, expected_portfolio_id):
        response = self.client.get(reverse('portfolio-summary'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['portfolio_id'], expected_portfolio_id)
        self.assertEqual(
            [item['symbol'] for item in response.data['allocations']],
            expected_symbols,
        )
        return response

    def test_same_browser_session_switch_keeps_holdings_and_summary_isolated(self):
        anonymous_holdings = self.client.get(reverse('holding-list'))
        anonymous_summary = self.client.get(reverse('portfolio-summary'))
        self.assertIn(
            anonymous_holdings.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            anonymous_summary.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

        self.login_as('switch_user_a')
        blocked_portfolio_payload = self.client.post(
            reverse('holding-list'),
            {
                'portfolio': 999999,
                'security': self.msft.id,
                'quantity': '1.000000',
                'average_price': '400.0000',
            },
            format='json',
        )
        self.assertEqual(blocked_portfolio_payload.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('portfolio', blocked_portfolio_payload.data)

        user_a_holding_response = self.create_holding(
            self.msft,
            quantity='1.000000',
            average_price='400.0000',
        )
        user_a_portfolio = Portfolio.objects.get(user=self.user_a)
        user_a_holding_id = user_a_holding_response.data['id']

        logout_response = self.logout()
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
        me_after_logout = self.client.get(reverse('auth-me'))
        self.assertIn(
            me_after_logout.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

        self.login_as('switch_user_b')
        user_b_holding_response = self.create_holding(
            self.spy,
            quantity='2.000000',
            average_price='500.0000',
        )
        user_b_portfolio = Portfolio.objects.get(user=self.user_b)
        user_b_holding_id = user_b_holding_response.data['id']

        self.assertNotEqual(user_a_portfolio.id, user_b_portfolio.id)
        self.assert_holdings_symbols(['SPY'])
        self.assert_summary_symbols(['SPY'], user_b_portfolio.id)
        self.assertEqual(
            Holding.objects.get(id=user_b_holding_id).portfolio_id,
            user_b_portfolio.id,
        )

        detail_response = self.client.get(reverse('holding-detail', args=[user_a_holding_id]))
        patch_response = self.client.patch(
            reverse('holding-detail', args=[user_a_holding_id]),
            {'quantity': '9.000000'},
            format='json',
        )
        delete_response = self.client.delete(reverse('holding-detail', args=[user_a_holding_id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Holding.objects.filter(id=user_a_holding_id).exists())

        self.logout()
        self.login_as('switch_user_a')
        self.assert_holdings_symbols(['MSFT'])
        self.assert_summary_symbols(['MSFT'], user_a_portfolio.id)

    def test_login_as_second_user_without_logout_replaces_session_user(self):
        self.login_as('switch_user_a')
        self.create_holding(self.msft, quantity='1.000000', average_price='400.0000')

        self.login_as('switch_user_b')
        self.create_holding(self.spy, quantity='1.000000', average_price='500.0000')
        user_b_portfolio = Portfolio.objects.get(user=self.user_b)

        self.assert_holdings_symbols(['SPY'])
        self.assert_summary_symbols(['SPY'], user_b_portfolio.id)

    def test_historical_multiple_portfolios_do_not_cross_user_boundaries(self):
        primary_a = Portfolio.objects.create(
            user=self.user_a,
            name='A Primary',
            available_funds=Decimal('100.00'),
        )
        secondary_a = Portfolio.objects.create(
            user=self.user_a,
            name='A Secondary',
            available_funds=Decimal('200.00'),
        )
        primary_b = Portfolio.objects.create(
            user=self.user_b,
            name='B Primary',
            available_funds=Decimal('300.00'),
        )
        Holding.objects.create(
            portfolio=primary_a,
            security=self.msft,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('400.0000'),
        )
        Holding.objects.create(
            portfolio=secondary_a,
            security=self.spy,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('500.0000'),
        )
        Holding.objects.create(
            portfolio=primary_b,
            security=self.spy,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('500.0000'),
        )

        self.login_as('switch_user_a')
        holdings_response = self.client.get(reverse('holding-list'))
        summary_response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(holdings_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            sorted(item['security']['symbol'] for item in holdings_response.data),
            ['MSFT', 'SPY'],
        )
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data['portfolio_id'], primary_a.id)
        self.assertEqual([item['symbol'] for item in summary_response.data['allocations']], ['MSFT'])
        self.assertNotEqual(summary_response.data['portfolio_id'], primary_b.id)
