from django.core.management.base import BaseCommand

from market.models import Security


SAMPLE_SECURITIES = [
    {
        'symbol': 'AAPL',
        'name': 'Apple',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'currency': 'USD',
    },
    {
        'symbol': 'MSFT',
        'name': 'Microsoft',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'currency': 'USD',
    },
    {
        'symbol': 'AMZN',
        'name': 'Amazon',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'currency': 'USD',
    },
    {
        'symbol': 'SPY',
        'name': 'SPDR S&P 500 ETF',
        'asset_type': Security.AssetType.ETF,
        'exchange': 'NYSEARCA',
        'currency': 'USD',
    },
    {
        'symbol': 'QQQ',
        'name': 'Invesco QQQ ETF',
        'asset_type': Security.AssetType.ETF,
        'exchange': 'NASDAQ',
        'currency': 'USD',
    },
]


class Command(BaseCommand):
    help = 'Seed development Security records used by the portfolio UI.'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for security_data in SAMPLE_SECURITIES:
            symbol = security_data['symbol']
            defaults = {
                'name': security_data['name'],
                'asset_type': security_data['asset_type'],
                'exchange': security_data['exchange'],
                'currency': security_data['currency'],
                'is_active': True,
            }
            _, created = Security.objects.update_or_create(
                symbol=symbol,
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded securities: {created_count} created, {updated_count} updated.',
            ),
        )
