from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from .models import Holding, Portfolio


class PortfolioHoldingIsolationApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='user_a', password='StrongPassword123')
        self.user_b = User.objects.create_user(username='user_b', password='StrongPassword123')
        self.security_a = Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.security_b = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            currency='USD',
        )
        self.security_c = Security.objects.create(
            symbol='QQQ',
            name='Invesco QQQ Trust',
            asset_type=Security.AssetType.ETF,
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
            quantity=Decimal('2.000000'),
            average_cost=Decimal('400.0000'),
        )
        self.holding_b = Holding.objects.create(
            portfolio=self.portfolio_b,
            security=self.security_b,
            quantity=Decimal('3.000000'),
            average_cost=Decimal('500.0000'),
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def assert_rejected(self, response):
        self.assertIn(
            response.status_code,
            [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
            ],
        )

    def test_unauthenticated_requests_to_portfolios_and_holdings_are_rejected(self):
        portfolio_response = self.client.get(reverse('portfolio-list'))
        holding_response = self.client.get(reverse('holding-list'))

        self.assertIn(
            portfolio_response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            holding_response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_user_a_only_receives_user_a_portfolio_and_holdings(self):
        self.authenticate_as(self.user_a)

        portfolio_response = self.client.get(reverse('portfolio-list'))
        holding_response = self.client.get(reverse('holding-list'))

        self.assertEqual(portfolio_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in portfolio_response.data], [self.portfolio_a.id])
        self.assertNotIn('user', portfolio_response.data[0])
        self.assertEqual(holding_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in holding_response.data], [self.holding_a.id])
        self.assertEqual([item['security']['symbol'] for item in holding_response.data], ['MSFT'])

    def test_user_b_only_receives_user_b_portfolio_and_holdings(self):
        self.authenticate_as(self.user_b)

        portfolio_response = self.client.get(reverse('portfolio-list'))
        holding_response = self.client.get(reverse('holding-list'))

        self.assertEqual(portfolio_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in portfolio_response.data], [self.portfolio_b.id])
        self.assertNotIn('user', portfolio_response.data[0])
        self.assertEqual(holding_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in holding_response.data], [self.holding_b.id])
        self.assertEqual([item['security']['symbol'] for item in holding_response.data], ['SPY'])

    def test_user_a_cannot_retrieve_update_or_delete_user_b_holding(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('holding-detail', args=[self.holding_b.id]))
        patch_response = self.client.patch(
            reverse('holding-detail', args=[self.holding_b.id]),
            {'quantity': '9.000000'},
            format='json',
        )
        delete_response = self.client.delete(reverse('holding-detail', args=[self.holding_b.id]))

        self.assert_rejected(detail_response)
        self.assert_rejected(patch_response)
        self.assert_rejected(delete_response)
        self.holding_b.refresh_from_db()
        self.assertEqual(self.holding_b.quantity, Decimal('3.000000'))

    def test_user_b_cannot_retrieve_update_or_delete_user_a_holding(self):
        self.authenticate_as(self.user_b)

        detail_response = self.client.get(reverse('holding-detail', args=[self.holding_a.id]))
        patch_response = self.client.patch(
            reverse('holding-detail', args=[self.holding_a.id]),
            {'quantity': '9.000000'},
            format='json',
        )
        delete_response = self.client.delete(reverse('holding-detail', args=[self.holding_a.id]))

        self.assert_rejected(detail_response)
        self.assert_rejected(patch_response)
        self.assert_rejected(delete_response)
        self.holding_a.refresh_from_db()
        self.assertEqual(self.holding_a.quantity, Decimal('2.000000'))

    def test_user_cannot_create_holding_using_another_users_portfolio_id(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('holding-list'),
            {
                'portfolio': self.portfolio_b.id,
                'security': self.security_c.id,
                'quantity': '1.000000',
                'average_price': '390.0000',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('portfolio', response.data)
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_b, security=self.security_c).exists())
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_a, security=self.security_c).exists())

    def test_authenticated_users_can_read_shared_security_records(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('security-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item['symbol'] for item in response.data},
            {'MSFT', 'QQQ', 'SPY'},
        )
