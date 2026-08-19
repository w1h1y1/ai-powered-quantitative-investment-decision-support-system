from django.conf import settings
from django.db import models


class InvestmentAgentAnalysis(models.Model):
    """Latest successful schema-validated analysis per user + security.

    Only successful, schema-validated analyses are stored. Failed generations
    are never persisted, so a later DeepSeek failure can never overwrite or
    remove the last successful analysis for the same security.
    """

    class Status(models.TextChoices):
        SUCCESS = 'success', 'Success'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_analyses',
    )
    security = models.ForeignKey(
        'market.Security',
        on_delete=models.CASCADE,
        related_name='agent_analyses',
    )
    symbol = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    as_of_date = models.DateField(null=True, blank=True)
    context_version = models.CharField(max_length=64, blank=True, default='')
    analysis_version = models.CharField(max_length=64, blank=True, default='')
    provider = models.CharField(max_length=64, blank=True, default='')
    model = models.CharField(max_length=64, blank=True, default='')
    analysis = models.JSONField(default=dict)
    failure_metadata = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-generated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'security'],
                name='uniq_user_security_latest_agent_analysis',
            ),
        ]
        indexes = [
            models.Index(
                fields=['user', 'security', '-generated_at'],
                name='agent_analysis_user_sec_idx',
            ),
        ]

    def __str__(self):
        return f'{self.user} · {self.symbol} · {self.generated_at:%Y-%m-%d %H:%M}'
