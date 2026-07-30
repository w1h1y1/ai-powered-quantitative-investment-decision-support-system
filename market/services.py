from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from .models import Security, SecurityDailyPrice
from .twelve_data import TwelveDataClient, TwelveDataError


MARKET_DATA_RANGES = {
    '1M': {
        'months': 1,
    },
    '3M': {
        'months': 3,
    },
    '6M': {
        'months': 6,
    },
    'YTD': {
        'ytd': True,
    },
    '1Y': {
        'years': 1,
    },
    '3Y': {
        'years': 3,
    },
    '5Y': {
        'years': 5,
    },
    'CUSTOM': {
        'custom': True,
    },
}
DEFAULT_MARKET_DATA_RANGE = '3M'
MARKET_DATA_FETCH_START_BUFFER_DAYS = 7
MARKET_DATA_LATEST_DATE_TOLERANCE_DAYS = 7
SUPPORTED_MARKET_DATA_ASSET_TYPES = {
    Security.AssetType.STOCK,
    Security.AssetType.ETF,
}


class MarketDataError(Exception):
    pass


class UnsupportedMarketDataRange(MarketDataError):
    pass


class InvalidMarketDataDateRange(MarketDataError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Invalid market data date range.')


class UnsupportedMarketDataSecurity(MarketDataError):
    pass


class MarketDataUnavailable(MarketDataError):
    pass


@dataclass(frozen=True)
class MarketDataResult:
    security: Security
    range_key: str
    values: list
    source: str
    is_stale: bool = False


def normalize_range(range_key):
    normalized = (range_key or DEFAULT_MARKET_DATA_RANGE).upper()
    if normalized not in MARKET_DATA_RANGES:
        raise UnsupportedMarketDataRange('Supported ranges are 1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, and Custom.')
    return normalized


def subtract_months(value, months):
    target_month_index = value.month - months - 1
    target_year = value.year + target_month_index // 12
    target_month = target_month_index % 12 + 1
    target_day = min(value.day, monthrange(target_year, target_month)[1])
    return date(target_year, target_month, target_day)


def subtract_years(value, years):
    target_year = value.year - years
    target_day = min(value.day, monthrange(target_year, value.month)[1])
    return date(target_year, value.month, target_day)


def parse_market_data_date(value, field_name):
    if not value:
        raise InvalidMarketDataDateRange({field_name: f'{field_name} is required for Custom range.'})
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidMarketDataDateRange({field_name: f'{field_name} must use YYYY-MM-DD format.'}) from exc


def get_range_date_window(range_key, start_date=None, end_date=None):
    today = timezone.localdate()
    config = MARKET_DATA_RANGES[range_key]

    if config.get('custom'):
        requested_start_date = parse_market_data_date(start_date, 'start_date')
        requested_end_date = parse_market_data_date(end_date, 'end_date')
    else:
        requested_end_date = today
        if config.get('ytd'):
            requested_start_date = date(today.year, 1, 1)
        elif 'months' in config:
            requested_start_date = subtract_months(today, config['months'])
        else:
            requested_start_date = subtract_years(today, config['years'])

    errors = {}
    if requested_start_date > requested_end_date:
        errors['start_date'] = 'Start date cannot be later than end date.'
    if requested_start_date > today:
        errors['start_date'] = 'Start date cannot be in the future.'
    if requested_end_date > today:
        errors['end_date'] = 'End date cannot be in the future.'
    if errors:
        raise InvalidMarketDataDateRange(errors)

    return requested_start_date, requested_end_date


def get_provider_start_date(start_date):
    return start_date - timedelta(days=MARKET_DATA_FETCH_START_BUFFER_DAYS)


def get_cached_daily_prices(security, start_date, end_date):
    return list(
        SecurityDailyPrice.objects
        .filter(security=security, date__gte=start_date, date__lte=end_date)
        .order_by('date')
    )


def cache_is_fresh(security):
    latest_bar = (
        SecurityDailyPrice.objects
        .filter(security=security)
        .order_by('-fetched_at')
        .first()
    )
    if not latest_bar:
        return False

    cache_ttl = timedelta(seconds=settings.MARKET_DATA_CACHE_TTL_SECONDS)
    return latest_bar.fetched_at >= timezone.now() - cache_ttl


def cache_has_requested_coverage(security, start_date, end_date):
    if not cache_is_fresh(security):
        return False

    coverage = (
        SecurityDailyPrice.objects
        .filter(security=security, date__lte=end_date)
        .aggregate(
            earliest_date=Min('date'),
            latest_date=Max('date'),
        )
    )
    earliest_date = coverage['earliest_date']
    latest_date = coverage['latest_date']
    if earliest_date is None or latest_date is None:
        return False

    latest_allowed_date = end_date - timedelta(days=MARKET_DATA_LATEST_DATE_TOLERANCE_DAYS)
    return earliest_date <= start_date and latest_date >= latest_allowed_date


def upsert_daily_bars(security, bars):
    with transaction.atomic():
        for bar in bars:
            SecurityDailyPrice.objects.update_or_create(
                security=security,
                date=bar.date,
                defaults={
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': max(bar.volume, 0),
                    'source': SecurityDailyPrice.SOURCE_TWELVE_DATA,
                },
            )


def fetch_and_cache_daily_prices(security, start_date, end_date, client=None):
    market_data_client = client or TwelveDataClient()
    bars = market_data_client.get_daily_time_series(
        symbol=security.symbol,
        start_date=get_provider_start_date(start_date),
        end_date=end_date,
    )
    upsert_daily_bars(security, bars)


def get_security_daily_market_data(security, range_key=None, start_date=None, end_date=None, client=None):
    normalized_range = normalize_range(range_key)
    if security.asset_type not in SUPPORTED_MARKET_DATA_ASSET_TYPES:
        raise UnsupportedMarketDataSecurity('Only stocks and ETFs are supported for daily market data.')

    requested_start_date, requested_end_date = get_range_date_window(
        normalized_range,
        start_date=start_date,
        end_date=end_date,
    )
    cached_values = get_cached_daily_prices(security, requested_start_date, requested_end_date)
    if cached_values and cache_has_requested_coverage(security, requested_start_date, requested_end_date):
        return MarketDataResult(
            security=security,
            range_key=normalized_range,
            values=cached_values,
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            is_stale=False,
        )

    try:
        fetch_and_cache_daily_prices(security, requested_start_date, requested_end_date, client=client)
    except TwelveDataError as exc:
        if cached_values:
            return MarketDataResult(
                security=security,
                range_key=normalized_range,
                values=cached_values,
                source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
                is_stale=True,
            )
        raise MarketDataUnavailable('Daily market data is temporarily unavailable.') from exc

    refreshed_values = get_cached_daily_prices(security, requested_start_date, requested_end_date)
    if not refreshed_values:
        raise MarketDataUnavailable('Daily market data is temporarily unavailable.')

    return MarketDataResult(
        security=security,
        range_key=normalized_range,
        values=refreshed_values,
        source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
        is_stale=False,
    )
