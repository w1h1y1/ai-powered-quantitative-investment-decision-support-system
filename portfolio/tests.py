from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from market.models import Security

from .models import Holding, Portfolio, TradeTransaction


class PortfolioModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='analyst', password='pass')
        self.security = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            name='Core Portfolio',
            description='Long-term investment account',
            available_funds=Decimal('10000.00'),
            base_currency='usd',
        )

    def test_portfolio_can_be_created_and_has_readable_string(self):
        self.assertEqual(self.portfolio.base_currency, 'USD')
        self.assertEqual(str(self.portfolio), 'Core Portfolio')

    def test_holding_can_be_created_and_has_readable_string(self):
        holding = Holding.objects.create(
            portfolio=self.portfolio,
            security=self.security,
            quantity=Decimal('10.500000'),
            average_cost=Decimal('185.2500'),
        )

        self.assertEqual(str(holding), 'Core Portfolio - AAPL')

    def test_portfolio_cannot_have_duplicate_holding_for_security(self):
        Holding.objects.create(
            portfolio=self.portfolio,
            security=self.security,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('185.2500'),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Holding.objects.create(
                portfolio=self.portfolio,
                security=self.security,
                quantity=Decimal('2.000000'),
                average_cost=Decimal('190.0000'),
            )

    def test_holding_non_negative_validation(self):
        holding = Holding(
            portfolio=self.portfolio,
            security=self.security,
            quantity=Decimal('-1.000000'),
            average_cost=Decimal('185.2500'),
        )

        with self.assertRaises(ValidationError):
            holding.full_clean()

    def test_trade_transaction_can_be_created_and_has_readable_string(self):
        transaction_record = TradeTransaction.objects.create(
            portfolio=self.portfolio,
            security=self.security,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('5.000000'),
            price=Decimal('180.1200'),
            fee=Decimal('1.50'),
            transaction_date=timezone.now(),
            notes='Initial purchase',
        )

        self.assertTrue(str(transaction_record).startswith('BUY AAPL on '))

    def test_trade_transaction_validation_requires_positive_buy_price(self):
        transaction_record = TradeTransaction(
            portfolio=self.portfolio,
            security=self.security,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('-180.1200'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            transaction_record.full_clean()
