from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from .models import Holding, Portfolio


class PortfolioSummaryApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='summary_user_a', password='pass')
        self.user_b = User.objects.create_user(username='summary_user_b', password='pass')
        self.security_msft = Security.objects.create(
            symbol='MSFT',
            name='Microsoft',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.security_amzn = Security.objects.create(
            symbol='AMZN',
            name='Amazon',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user)

    def test_anonymous_user_cannot_access_portfolio_summary(self):
        response = self.client.get(reverse('portfolio-summary'))

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_empty_portfolio_summary_returns_zero_values(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Empty Portfolio',
            available_funds=Decimal('0.00'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['portfolio_id'], portfolio.id)
        self.assertEqual(response.data['holdings_count'], 0)
        self.assertEqual(response.data['total_cost'], '0.00')
        self.assertEqual(response.data['holdings_market_value'], '0.00')
        self.assertEqual(response.data['available_liquidity'], '0.00')
        self.assertEqual(response.data['remaining_liquidity'], '0.00')
        self.assertEqual(response.data['total_asset_value'], '0.00')
        self.assertEqual(response.data['unrealized_profit_loss'], '0.00')
        self.assertEqual(response.data['unrealized_return_percent'], '0.00')
        self.assertEqual(response.data['allocations'], [])

    def test_summary_calculates_totals_profit_return_liquidity_and_allocations(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Primary Portfolio',
            available_funds=Decimal('250.00'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_msft,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('397.5000'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_amzn,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('180.0000'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['portfolio_id'], portfolio.id)
        self.assertEqual(response.data['holdings_count'], 2)
        self.assertEqual(response.data['total_cost'], '975.00')
        self.assertEqual(response.data['holdings_market_value'], '1098.38')
        self.assertEqual(response.data['available_liquidity'], '250.00')
        self.assertEqual(response.data['remaining_liquidity'], '250.00')
        self.assertEqual(response.data['total_asset_value'], '1348.38')
        self.assertEqual(response.data['unrealized_profit_loss'], '123.38')
        self.assertEqual(response.data['unrealized_return_percent'], '12.65')

        msft_allocation = response.data['allocations'][1]
        self.assertEqual(msft_allocation['symbol'], 'MSFT')
        self.assertEqual(msft_allocation['quantity'], '2')
        self.assertEqual(msft_allocation['average_price'], '397.50')
        self.assertEqual(msft_allocation['current_price'], '449.52')
        self.assertEqual(msft_allocation['cost'], '795.00')
        self.assertEqual(msft_allocation['market_value'], '899.04')
        self.assertEqual(msft_allocation['unrealized_profit_loss'], '104.04')
        self.assertEqual(msft_allocation['unrealized_return_percent'], '13.09')
        self.assertEqual(msft_allocation['allocation_percent'], '81.85')

    def test_two_users_receive_isolated_portfolio_summaries(self):
        portfolio_a = Portfolio.objects.create(
            user=self.user_a,
            name='User A Portfolio',
            available_funds=Decimal('100.00'),
        )
        portfolio_b = Portfolio.objects.create(
            user=self.user_b,
            name='User B Portfolio',
            available_funds=Decimal('500.00'),
        )
        Holding.objects.create(
            portfolio=portfolio_a,
            security=self.security_msft,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('400.0000'),
        )
        Holding.objects.create(
            portfolio=portfolio_b,
            security=self.security_amzn,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('190.0000'),
        )

        self.authenticate_as(self.user_a)
        user_a_response = self.client.get(reverse('portfolio-summary'))

        self.authenticate_as(self.user_b)
        user_b_response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(user_a_response.status_code, status.HTTP_200_OK)
        self.assertEqual(user_b_response.status_code, status.HTTP_200_OK)
        self.assertEqual(user_a_response.data['portfolio_id'], portfolio_a.id)
        self.assertEqual(user_b_response.data['portfolio_id'], portfolio_b.id)
        self.assertEqual([item['symbol'] for item in user_a_response.data['allocations']], ['MSFT'])
        self.assertEqual([item['symbol'] for item in user_b_response.data['allocations']], ['AMZN'])

    def test_zero_market_value_does_not_divide_by_zero(self):
        unknown_security = Security.objects.create(
            symbol='ZZZZ',
            name='Unknown Demo Security',
            asset_type=Security.AssetType.STOCK,
            exchange='TEST',
            currency='USD',
        )
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Zero Market Portfolio',
            available_funds=Decimal('0.00'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=unknown_security,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('10.0000'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['holdings_market_value'], '0.00')
        self.assertEqual(response.data['unrealized_profit_loss'], '-20.00')
        self.assertEqual(response.data['unrealized_return_percent'], '-100.00')
        self.assertEqual(response.data['allocations'][0]['current_price'], '0.00')
        self.assertEqual(response.data['allocations'][0]['allocation_percent'], '0.00')
        self.assertEqual(response.data['allocations'][0]['current_price_source'], 'DEMO_UNAVAILABLE')

    def test_zero_cost_returns_zero_unrealized_return_percent(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Zero Cost Portfolio',
            available_funds=Decimal('0.00'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_msft,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('0.0000'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_cost'], '0.00')
        self.assertEqual(response.data['holdings_market_value'], '899.04')
        self.assertEqual(response.data['unrealized_profit_loss'], '899.04')
        self.assertEqual(response.data['unrealized_return_percent'], '0.00')
        self.assertEqual(response.data['allocations'][0]['unrealized_return_percent'], '0.00')
        self.assertEqual(response.data['allocations'][0]['allocation_percent'], '100.00')

    def test_decimal_calculation_does_not_expose_float_artifacts(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Decimal Portfolio',
            available_funds=Decimal('0.00'),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_msft,
            quantity=Decimal('0.100000'),
            average_cost=Decimal('0.1000'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_cost'], '0.01')
        self.assertEqual(response.data['holdings_market_value'], '44.95')
        self.assertNotIn('44.952000000', response.data['holdings_market_value'])

    def test_historical_duplicate_portfolios_use_primary_portfolio_only(self):
        primary_portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Primary Historical Portfolio',
            available_funds=Decimal('100.00'),
        )
        secondary_portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Secondary Historical Portfolio',
            available_funds=Decimal('999.00'),
        )
        other_user_portfolio = Portfolio.objects.create(
            user=self.user_b,
            name='Other User Portfolio',
            available_funds=Decimal('777.00'),
        )
        Holding.objects.create(
            portfolio=primary_portfolio,
            security=self.security_msft,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('400.0000'),
        )
        Holding.objects.create(
            portfolio=secondary_portfolio,
            security=self.security_amzn,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('180.0000'),
        )
        Holding.objects.create(
            portfolio=other_user_portfolio,
            security=self.security_amzn,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('180.0000'),
        )
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('portfolio-summary'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['portfolio_id'], primary_portfolio.id)
        self.assertEqual(response.data['available_liquidity'], '100.00')
        self.assertEqual(response.data['remaining_liquidity'], '100.00')
        self.assertEqual([item['symbol'] for item in response.data['allocations']], ['MSFT'])
