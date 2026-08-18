from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PortfolioCashFlow
from .services import get_or_create_primary_portfolio


class PortfolioFundingApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='funding_user_a', password='StrongPassword123')
        self.user_b = User.objects.create_user(username='funding_user_b', password='StrongPassword123')

    def authenticate_as(self, user):
        self.client.force_authenticate(user)

    def post_funding(self, flow_type, amount, transaction_date='2026-08-18', note=''):
        return self.client.post(
            reverse('portfolio-funding'),
            {
                'flow_type': flow_type,
                'amount': amount,
                'transaction_date': transaction_date,
                'note': note,
            },
            format='json',
        )

    def assert_liquidity(self, user, expected):
        portfolio, _ = get_or_create_primary_portfolio(user)
        self.assertEqual(portfolio.available_funds, Decimal(expected))

    def test_initial_deposit_establishes_starting_cash(self):
        self.authenticate_as(self.user_a)

        response = self.post_funding('INITIAL_DEPOSIT', '10000.00')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['portfolio_summary']['remaining_liquidity'], '10000.00')
        self.assertEqual(response.data['portfolio_summary']['holdings_market_value'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['total_asset_value'], '10000.00')
        self.assertEqual(response.data['portfolio_summary']['total_profit_loss'], '0.00')
        self.assert_liquidity(self.user_a, '10000.00')
        self.assertEqual(
            PortfolioCashFlow.objects.filter(
                portfolio__user=self.user_a,
                flow_type=PortfolioCashFlow.FlowType.INITIAL,
                amount=Decimal('10000.00'),
            ).count(),
            1,
        )

    def test_deposit_increases_liquidity_without_changing_profit(self):
        self.authenticate_as(self.user_a)
        self.post_funding('INITIAL_DEPOSIT', '10000.00')

        response = self.post_funding('DEPOSIT', '3000.00', transaction_date='2026-08-19')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['portfolio_summary']['remaining_liquidity'], '13000.00')
        self.assertEqual(response.data['portfolio_summary']['total_profit_loss'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['realized_profit_loss'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['unrealized_profit_loss'], '0.00')

    def test_withdrawal_decreases_liquidity_without_changing_profit(self):
        self.authenticate_as(self.user_a)
        self.post_funding('INITIAL_DEPOSIT', '10000.00')

        response = self.post_funding('WITHDRAWAL', '1000.00', transaction_date='2026-08-20')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['portfolio_summary']['remaining_liquidity'], '9000.00')
        self.assertEqual(response.data['portfolio_summary']['total_profit_loss'], '0.00')

    def test_excessive_withdrawal_is_rejected_and_not_recorded(self):
        self.authenticate_as(self.user_a)
        self.post_funding('INITIAL_DEPOSIT', '1000.00')

        response = self.post_funding('WITHDRAWAL', '1000.01')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cannot exceed available cash', str(response.data['detail']))
        self.assert_liquidity(self.user_a, '1000.00')
        self.assertFalse(
            PortfolioCashFlow.objects.filter(
                portfolio__user=self.user_a,
                flow_type=PortfolioCashFlow.FlowType.WITHDRAWAL,
            ).exists(),
        )

    def test_initial_deposit_cannot_be_recorded_twice(self):
        self.authenticate_as(self.user_a)
        self.post_funding('INITIAL_DEPOSIT', '10000.00')

        response = self.post_funding('INITIAL_DEPOSIT', '5000.00')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_liquidity(self.user_a, '10000.00')
        self.assertEqual(
            PortfolioCashFlow.objects.filter(
                portfolio__user=self.user_a,
                flow_type=PortfolioCashFlow.FlowType.INITIAL,
            ).count(),
            1,
        )

    def test_funding_records_are_isolated_between_users(self):
        self.authenticate_as(self.user_a)
        self.post_funding('INITIAL_DEPOSIT', '10000.00')
        self.authenticate_as(self.user_b)
        self.post_funding('INITIAL_DEPOSIT', '5000.00')

        self.authenticate_as(self.user_a)
        user_a_response = self.client.get(reverse('portfolio-funding'))
        self.authenticate_as(self.user_b)
        user_b_response = self.client.get(reverse('portfolio-funding'))

        self.assertEqual(user_a_response.status_code, status.HTTP_200_OK)
        self.assertEqual(user_b_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item['flow_type'] for item in user_a_response.data['funding_transactions']],
            ['INITIAL'],
        )
        self.assertEqual(
            [item['flow_type'] for item in user_b_response.data['funding_transactions']],
            ['INITIAL'],
        )
        self.assertEqual(
            {item['id'] for item in user_a_response.data['funding_transactions']}
            .isdisjoint({item['id'] for item in user_b_response.data['funding_transactions']}),
            True,
        )

    def test_funding_requires_authentication(self):
        response = self.client.get(reverse('portfolio-funding'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
