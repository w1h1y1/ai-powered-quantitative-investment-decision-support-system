from django.conf import settings
from django.db import models

from market.models import Security


class Watchlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watchlists',
    )
    name = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'name']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='watchlist_user_created_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'name'],
                name='unique_watchlist_user_name',
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.user})'


class WatchlistItem(models.Model):
    watchlist = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        related_name='items',
    )
    security = models.ForeignKey(
        Security,
        on_delete=models.PROTECT,
        related_name='watchlist_items',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        indexes = [
            models.Index(fields=['watchlist', 'security'], name='watchlist_item_sec_idx'),
            models.Index(fields=['security'], name='watchlist_item_security_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['watchlist', 'security'],
                name='unique_watchlist_item_sec',
            ),
        ]

    def __str__(self):
        return f'{self.watchlist.name} - {self.security.symbol}'
