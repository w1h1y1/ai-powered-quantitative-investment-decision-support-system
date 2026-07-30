from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from market.models import Security


class Portfolio(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='portfolios',
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    available_funds = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    base_currency = models.CharField(max_length=3, default='USD')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'name']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='portfolio_user_created_idx'),
            models.Index(fields=['created_at'], name='portfolio_created_idx'),
        ]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.base_currency = self.base_currency.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Holding(models.Model):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='holdings',
    )
    security = models.ForeignKey(
        Security,
        on_delete=models.PROTECT,
        related_name='holdings',
    )
    quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000000'))],
    )
    average_cost = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0000'))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['portfolio', 'security__symbol']
        indexes = [
            models.Index(fields=['portfolio', 'security'], name='holding_portfolio_sec_idx'),
            models.Index(fields=['security'], name='holding_security_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['portfolio', 'security'],
                name='unique_holding_portfolio_sec',
            ),
        ]

    def __str__(self):
        return f'{self.portfolio.name} - {self.security.symbol}'


class TradeTransaction(models.Model):
    class TransactionType(models.TextChoices):
        BUY = 'BUY', 'Buy'
        SELL = 'SELL', 'Sell'
        DIVIDEND = 'DIVIDEND', 'Dividend'

    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='trade_transactions',
    )
    security = models.ForeignKey(
        Security,
        on_delete=models.PROTECT,
        related_name='trade_transactions',
    )
    transaction_type = models.CharField(max_length=16, choices=TransactionType.choices)
    quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.000000'))],
    )
    price = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0000'))],
    )
    cash_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0000'))],
    )
    fee = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    transaction_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['portfolio', '-transaction_date'], name='trade_txn_port_date_idx'),
            models.Index(fields=['security', '-transaction_date'], name='trade_txn_sec_date_idx'),
            models.Index(fields=['transaction_date'], name='trade_txn_date_idx'),
        ]

    def clean(self):
        errors = {}

        if self.transaction_type in {
            self.TransactionType.BUY,
            self.TransactionType.SELL,
        }:
            if self.quantity is None or self.quantity <= 0:
                errors['quantity'] = 'Quantity must be greater than 0 for buy and sell transactions.'
            if self.price is None or self.price <= 0:
                errors['price'] = 'Price must be greater than 0 for buy and sell transactions.'

        if self.transaction_type == self.TransactionType.DIVIDEND:
            if self.cash_amount is None or self.cash_amount <= 0:
                errors['cash_amount'] = 'Cash amount must be greater than 0 for dividend transactions.'

        if self.fee is not None and self.fee < 0:
            errors['fee'] = 'Fee cannot be negative.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.transaction_type} {self.security.symbol} on {self.transaction_date:%Y-%m-%d}'
