from django.utils import timezone

from .models import InvestmentAgentAnalysis


def save_successful_analysis(
    *,
    user,
    security,
    symbol,
    as_of_date,
    context_version,
    analysis_version,
    provider,
    model,
    analysis,
):
    """Upsert the latest successful analysis for (user, security)."""
    analysis_record, _ = InvestmentAgentAnalysis.objects.update_or_create(
        user=user,
        security=security,
        defaults={
            'symbol': symbol or security.symbol,
            'status': InvestmentAgentAnalysis.Status.SUCCESS,
            'as_of_date': as_of_date,
            'context_version': context_version or '',
            'analysis_version': analysis_version or '',
            'provider': provider or '',
            'model': model or '',
            'analysis': analysis or {},
            'failure_metadata': {},
            'generated_at': timezone.now(),
        },
    )
    return analysis_record


def get_latest_successful_analysis(user, security):
    return (
        InvestmentAgentAnalysis.objects
        .filter(
            user=user,
            security=security,
            status=InvestmentAgentAnalysis.Status.SUCCESS,
        )
        .order_by('-generated_at')
        .first()
    )
