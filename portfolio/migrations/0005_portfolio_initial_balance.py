from decimal import Decimal, ROUND_HALF_UP

from django.core.validators import MinValueValidator
from django.db import migrations, models


MONEY_QUANTIZER = Decimal('0.01')
ZERO = Decimal('0')


def quantize_money(value):
    return (value or ZERO).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def infer_initial_balance_from_transactions(portfolio, TradeTransaction, db_alias):
    initial_balance = portfolio.available_funds or ZERO
    transactions = TradeTransaction.objects.using(db_alias).filter(portfolio_id=portfolio.id)
    for trade_transaction in transactions:
        quantity = trade_transaction.quantity or ZERO
        price = trade_transaction.price or ZERO
        fee = trade_transaction.fee or ZERO
        gross_amount = quantity * price

        if trade_transaction.transaction_type == 'BUY':
            initial_balance += gross_amount + fee
        elif trade_transaction.transaction_type == 'SELL':
            initial_balance -= gross_amount - fee

    return quantize_money(initial_balance)


def backfill_initial_balance(apps, schema_editor):
    Portfolio = apps.get_model('portfolio', 'Portfolio')
    PortfolioCashFlow = apps.get_model('portfolio', 'PortfolioCashFlow')
    TradeTransaction = apps.get_model('portfolio', 'TradeTransaction')
    db_alias = schema_editor.connection.alias

    for portfolio in Portfolio.objects.using(db_alias).all():
        initial_cash_flow = (
            PortfolioCashFlow.objects
            .using(db_alias)
            .filter(portfolio_id=portfolio.id, flow_type='INITIAL')
            .order_by('effective_date', 'id')
            .first()
        )
        if initial_cash_flow:
            portfolio.initial_balance = quantize_money(initial_cash_flow.amount)
        else:
            portfolio.initial_balance = infer_initial_balance_from_transactions(
                portfolio,
                TradeTransaction,
                db_alias,
            )
        portfolio.save(update_fields=['initial_balance'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0004_portfoliocashflow'),
    ]

    operations = [
        migrations.AddField(
            model_name='portfolio',
            name='initial_balance',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=18,
                validators=[MinValueValidator(Decimal('0.00'))],
            ),
        ),
        migrations.RunPython(backfill_initial_balance, noop_reverse),
    ]
