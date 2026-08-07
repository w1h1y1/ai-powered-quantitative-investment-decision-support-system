from django.db import models


class Security(models.Model):
    class AssetType(models.TextChoices):
        STOCK = 'STOCK', 'Stock'
        ETF = 'ETF', 'ETF'

    symbol = models.CharField(max_length=16, db_index=True)
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=8, choices=AssetType.choices)
    exchange = models.CharField(max_length=64)
    mic_code = models.CharField(max_length=16, blank=True, default='')
    country = models.CharField(max_length=64, blank=True, default='')
    currency = models.CharField(max_length=3, default='USD')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']
        indexes = [
            models.Index(fields=['symbol'], name='security_symbol_idx'),
            models.Index(fields=['asset_type', 'is_active'], name='security_type_active_idx'),
            models.Index(fields=['symbol', 'mic_code'], name='security_symbol_mic_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['symbol', 'mic_code'],
                name='unique_security_symbol_mic_code',
            ),
        ]
        verbose_name_plural = 'securities'

    def save(self, *args, **kwargs):
        self.symbol = self.symbol.strip().upper()
        self.mic_code = self.mic_code.strip().upper()
        self.country = self.country.strip()
        self.currency = self.currency.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.symbol} - {self.name}'


class SecurityDailyPrice(models.Model):
    SOURCE_TWELVE_DATA = 'TWELVE_DATA'

    security = models.ForeignKey(
        Security,
        on_delete=models.CASCADE,
        related_name='daily_prices',
    )
    date = models.DateField()
    open = models.DecimalField(max_digits=20, decimal_places=6)
    high = models.DecimalField(max_digits=20, decimal_places=6)
    low = models.DecimalField(max_digits=20, decimal_places=6)
    close = models.DecimalField(max_digits=20, decimal_places=6)
    volume = models.BigIntegerField(default=0)
    source = models.CharField(max_length=32, default=SOURCE_TWELVE_DATA)
    fetched_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['security', 'date']
        indexes = [
            models.Index(fields=['security', 'date'], name='daily_price_security_date_idx'),
            models.Index(fields=['security', '-date'], name='daily_price_sec_date_desc_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'date'],
                name='unique_daily_price_security_date',
            ),
        ]

    def __str__(self):
        return f'{self.security.symbol} {self.date}'
