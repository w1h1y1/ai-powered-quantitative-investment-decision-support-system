from django.core.management.base import BaseCommand

from market.models import Security


SAMPLE_SECURITIES = [
    {
        'symbol': 'AAPL',
        'name': 'Apple',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'mic_code': 'XNAS',
        'country': 'United States',
        'currency': 'USD',
    },
    {
        'symbol': 'MSFT',
        'name': 'Microsoft',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'mic_code': 'XNAS',
        'country': 'United States',
        'currency': 'USD',
    },
    {
        'symbol': 'AMZN',
        'name': 'Amazon',
        'asset_type': Security.AssetType.STOCK,
        'exchange': 'NASDAQ',
        'mic_code': 'XNAS',
        'country': 'United States',
        'currency': 'USD',
    },
    {
        'symbol': 'SPY',
        'name': 'SPDR S&P 500 ETF',
        'asset_type': Security.AssetType.ETF,
        'exchange': 'NYSEARCA',
        'mic_code': 'ARCX',
        'country': 'United States',
        'currency': 'USD',
    },
    {
        'symbol': 'QQQ',
        'name': 'Invesco QQQ ETF',
        'asset_type': Security.AssetType.ETF,
        'exchange': 'NASDAQ',
        'mic_code': 'XNAS',
        'country': 'United States',
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
                'mic_code': security_data['mic_code'],
                'country': security_data['country'],
                'currency': security_data['currency'],
                'is_active': True,
            }
            security = (
                Security.objects
                .filter(symbol=symbol, mic_code=security_data['mic_code'])
                .first()
                or Security.objects.filter(symbol=symbol, mic_code='').first()
            )
            created = security is None
            if created:
                Security.objects.create(symbol=symbol, **defaults)
            else:
                for field, value in defaults.items():
                    setattr(security, field, value)
                security.save(update_fields=[*defaults.keys(), 'updated_at'])

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded securities: {created_count} created, {updated_count} updated.',
            ),
        )
