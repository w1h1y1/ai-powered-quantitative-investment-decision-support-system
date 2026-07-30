from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Security


class SecurityModelTests(TestCase):
    def test_security_can_be_created_and_has_readable_string(self):
        security = Security.objects.create(
            symbol='aapl',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='usd',
        )

        self.assertEqual(security.symbol, 'AAPL')
        self.assertEqual(security.currency, 'USD')
        self.assertEqual(str(security), 'AAPL - Apple Inc.')

    def test_security_symbol_must_be_unique(self):
        Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Security.objects.create(
                symbol='MSFT',
                name='Microsoft Duplicate',
                asset_type=Security.AssetType.STOCK,
                exchange='NASDAQ',
                currency='USD',
            )

    def test_seed_securities_command_is_idempotent(self):
        Security.objects.create(
            symbol='MSFT',
            name='Old Microsoft Name',
            asset_type=Security.AssetType.STOCK,
            exchange='OLD',
            currency='USD',
        )

        call_command('seed_securities', stdout=StringIO())
        call_command('seed_securities', stdout=StringIO())

        expected_symbols = ['AAPL', 'AMZN', 'MSFT', 'QQQ', 'SPY']
        self.assertEqual(
            list(Security.objects.order_by('symbol').values_list('symbol', flat=True)),
            expected_symbols,
        )
        self.assertEqual(Security.objects.count(), len(expected_symbols))
        self.assertEqual(Security.objects.get(symbol='MSFT').name, 'Microsoft')
