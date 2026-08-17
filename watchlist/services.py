from threading import Lock

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from market.serializers import SecuritySummarySerializer
from market.services import (
    MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
    InvalidMarketDataDateRange,
    MarketDataInvalidSymbol,
    MarketDataRateLimited,
    MarketDataUnavailable,
    SecuritySelectionValidationError,
    UnsupportedMarketDataInterval,
    UnsupportedMarketDataRange,
    UnsupportedMarketDataSecurity,
    get_or_create_verified_security,
    get_security_daily_market_data,
    get_security_latest_quotes,
    get_verified_security_search_item,
    search_security_symbols,
)

from .models import Watchlist, WatchlistItem


DEFAULT_WATCHLIST_NAME = 'My Watchlist'
WATCHLIST_SUMMARY_CACHE_KEY_PREFIX = 'watchlist:summary:v1'
WATCHLIST_SUMMARY_RANGE = '3M'
WATCHLIST_SUMMARY_INTERVAL = '1day'
WATCHLIST_SUMMARY_MINI_TREND_POINTS = 16
WATCHLIST_SUMMARY_INDICATOR_POINTS = 96

_summary_locks = {}
_summary_locks_guard = Lock()


WatchlistSymbolValidationError = SecuritySelectionValidationError


def get_verified_search_item(data):
    return get_verified_security_search_item(data, search_func=search_security_symbols)


def get_primary_watchlist(user):
    if not user or not user.is_authenticated:
        return None

    return (
        Watchlist.objects
        .filter(user=user)
        .order_by('created_at', 'id')
        .first()
    )


def get_or_create_primary_watchlist(user, defaults=None):
    defaults = defaults or {}

    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        watchlist = get_primary_watchlist(user)
        if watchlist:
            return watchlist, False

        create_defaults = {
            'name': defaults.get('name') or DEFAULT_WATCHLIST_NAME,
        }
        return Watchlist.objects.create(user=user, **create_defaults), True


def serialize_watchlist_item_result(item):
    return {
        'id': item.id,
        'security': SecuritySummarySerializer(item.security).data,
        'added_at': item.added_at.isoformat() if item.added_at else '',
    }


def add_symbol_to_watchlist(user, data):
    search_item = get_verified_search_item(data)

    with transaction.atomic():
        watchlist, _ = get_or_create_primary_watchlist(user)
        security, created_security = get_or_create_verified_security(search_item)
        item, created_item = WatchlistItem.objects.get_or_create(
            watchlist=watchlist,
            security=security,
        )

    return {
        'status': 'added' if created_item else 'already_tracked',
        'created_security': created_security,
        'created_item': created_item,
        'watchlist': {
            'id': watchlist.id,
            'name': watchlist.name,
        },
        'watchlist_item': serialize_watchlist_item_result(item),
        'security': SecuritySummarySerializer(security).data,
    }


def get_watchlist_summary_cache_ttl_seconds():
    return getattr(settings, 'WATCHLIST_SUMMARY_CACHE_TTL_SECONDS', 60)


def get_summary_lock(cache_key):
    with _summary_locks_guard:
        if cache_key not in _summary_locks:
            _summary_locks[cache_key] = Lock()
        return _summary_locks[cache_key]


def format_decimal(value):
    if value is None:
        return None
    return f'{value:.6f}'


def get_bar_date(value):
    timestamp = getattr(value, 'timestamp', '')
    if timestamp:
        return str(timestamp)

    date_value = getattr(value, 'date', '')
    if hasattr(date_value, 'isoformat'):
        return date_value.isoformat()
    return str(date_value)


def serialize_close_point(value):
    return {
        'date': get_bar_date(value),
        'close': format_decimal(getattr(value, 'close', None)),
    }


def downsample_points(points, maximum_points):
    points = tuple(points)
    if len(points) <= maximum_points:
        return points
    if maximum_points <= 1:
        return points[-maximum_points:]

    last_index = len(points) - 1
    return tuple(
        points[round((position / (maximum_points - 1)) * last_index)]
        for position in range(maximum_points)
    )


def serialize_quote_result(result):
    is_unavailable = result.data_status == MARKET_DATA_QUOTE_STATUS_UNAVAILABLE
    return {
        'source': result.source,
        'price': None if is_unavailable else format_decimal(result.price),
        'change': None if is_unavailable else format_decimal(result.change),
        'percent_change': None if is_unavailable else format_decimal(result.percent_change),
        'currency': result.currency,
        'as_of': result.as_of,
        'data_status': result.data_status,
        'cache_status': result.cache_status,
        'is_stale': result.is_stale,
        'error': result.error,
    }


def unavailable_history_payload(error):
    return {
        'range': WATCHLIST_SUMMARY_RANGE,
        'interval': WATCHLIST_SUMMARY_INTERVAL,
        'source': '',
        'data_source': '',
        'cache_status': 'unavailable',
        'data_status': 'unavailable',
        'is_stale': True,
        'error': str(error),
        'mini_trend': (),
        'indicator_closes': (),
        'latest_as_of': '',
    }


def get_watchlist_item_history(security):
    try:
        result = get_security_daily_market_data(
            security,
            range_key=WATCHLIST_SUMMARY_RANGE,
            interval=WATCHLIST_SUMMARY_INTERVAL,
            force_refresh=False,
        )
    except (
        InvalidMarketDataDateRange,
        MarketDataInvalidSymbol,
        MarketDataRateLimited,
        MarketDataUnavailable,
        UnsupportedMarketDataInterval,
        UnsupportedMarketDataRange,
        UnsupportedMarketDataSecurity,
    ) as exc:
        return unavailable_history_payload(exc)

    visible_points = tuple(serialize_close_point(value) for value in result.values)
    indicator_points = tuple(
        serialize_close_point(value)
        for value in (
            *tuple(result.warmup_values),
            *tuple(result.values),
        )
    )[-WATCHLIST_SUMMARY_INDICATOR_POINTS:]

    return {
        'range': result.range_key,
        'interval': result.interval,
        'source': result.source,
        'data_source': result.data_source,
        'cache_status': result.cache_status,
        'data_status': 'stale' if result.is_stale else 'ok',
        'is_stale': result.is_stale,
        'error': result.upstream_error,
        'mini_trend': downsample_points(visible_points, WATCHLIST_SUMMARY_MINI_TREND_POINTS),
        'indicator_closes': indicator_points,
        'latest_as_of': visible_points[-1]['date'] if visible_points else '',
    }


def get_watchlist_summary_cache_key(user, watchlist, item_ids):
    joined_item_ids = '-'.join(str(item_id) for item_id in item_ids) or 'empty'
    return f'{WATCHLIST_SUMMARY_CACHE_KEY_PREFIX}:{user.pk}:{watchlist.pk}:{joined_item_ids}'


def set_summary_cache_status(summary, cache_status):
    metadata = {
        **summary.get('metadata', {}),
        'cache_status': cache_status,
    }
    return {
        **summary,
        'cache_status': cache_status,
        'metadata': metadata,
    }


def build_watchlist_summary(watchlist, items):
    securities = tuple(item.security for item in items)
    quote_results = get_security_latest_quotes(securities) if securities else ()
    quotes_by_security_id = {
        result.security.id: result
        for result in quote_results
    }
    summary_items = []
    errors = []

    for item in items:
        quote = quotes_by_security_id.get(item.security_id)
        history = get_watchlist_item_history(item.security)
        quote_payload = serialize_quote_result(quote) if quote else {
            'source': '',
            'price': None,
            'change': None,
            'percent_change': None,
            'currency': item.security.currency,
            'as_of': '',
            'data_status': 'unavailable',
            'cache_status': 'unavailable',
            'is_stale': True,
            'error': 'Latest quote is unavailable.',
        }

        if quote_payload.get('error'):
            errors.append(f'{item.security.symbol}: {quote_payload["error"]}')
        if history.get('error'):
            errors.append(f'{item.security.symbol}: {history["error"]}')

        summary_items.append({
            'item_id': item.id,
            'added_at': item.added_at.isoformat() if item.added_at else '',
            'security': SecuritySummarySerializer(item.security).data,
            'quote': quote_payload,
            'history': history,
        })

    data_status = 'ok' if not errors else 'partial'
    return {
        'watchlist': {
            'id': watchlist.id,
            'name': watchlist.name,
            'created_at': watchlist.created_at.isoformat() if watchlist.created_at else '',
            'updated_at': watchlist.updated_at.isoformat() if watchlist.updated_at else '',
        },
        'watchlist_items': [
            {
                'id': item.id,
                'security': SecuritySummarySerializer(item.security).data,
                'added_at': item.added_at.isoformat() if item.added_at else '',
            }
            for item in items
        ],
        'items': tuple(summary_items),
        'data_status': data_status,
        'cache_status': 'fresh',
        'metadata': {
            'watchlist_id': watchlist.id,
            'item_count': len(items),
            'range': WATCHLIST_SUMMARY_RANGE,
            'interval': WATCHLIST_SUMMARY_INTERVAL,
            'mini_trend_points': WATCHLIST_SUMMARY_MINI_TREND_POINTS,
            'indicator_points': WATCHLIST_SUMMARY_INDICATOR_POINTS,
            'cache_status': 'fresh',
            'errors': tuple(errors),
        },
    }


def get_watchlist_summary(user, force_refresh=False):
    watchlist, _ = get_or_create_primary_watchlist(user)
    items = tuple(
        WatchlistItem.objects
        .select_related('security')
        .filter(watchlist=watchlist)
        .order_by('-added_at')
    )
    item_ids = tuple(item.id for item in items)
    cache_key = get_watchlist_summary_cache_key(user, watchlist, item_ids)
    cache_ttl = get_watchlist_summary_cache_ttl_seconds()

    if cache_ttl > 0 and not force_refresh:
        cached_summary = cache.get(cache_key)
        if cached_summary is not None:
            return set_summary_cache_status(cached_summary, 'hit')

    lock = get_summary_lock(cache_key)
    with lock:
        if cache_ttl > 0 and not force_refresh:
            cached_summary = cache.get(cache_key)
            if cached_summary is not None:
                return set_summary_cache_status(cached_summary, 'hit')

        summary = build_watchlist_summary(watchlist, items)
        if cache_ttl > 0:
            cache.set(cache_key, summary, cache_ttl)
        return summary
