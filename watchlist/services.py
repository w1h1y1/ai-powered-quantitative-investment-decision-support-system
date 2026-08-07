from threading import Lock

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from market.models import Security
from market.serializers import SecuritySummarySerializer
from market.services import (
    MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
    InvalidMarketDataDateRange,
    MarketDataInvalidSymbol,
    MarketDataRateLimited,
    MarketDataUnavailable,
    UnsupportedMarketDataInterval,
    UnsupportedMarketDataRange,
    UnsupportedMarketDataSecurity,
    get_asset_type_from_instrument_type,
    get_security_daily_market_data,
    get_security_latest_quotes,
    normalize_security_currency,
    normalize_security_exchange,
    normalize_security_mic_code,
    normalize_security_search_text,
    normalize_security_symbol,
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


class WatchlistSymbolValidationError(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(str(detail))


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


def get_search_item_value(item, key):
    value = item.get(key)
    return '' if value is None else str(value)


def search_item_matches_submission(item, data):
    submitted_symbol = normalize_security_symbol(data.get('symbol'))
    if normalize_security_symbol(item.get('symbol')) != submitted_symbol:
        return False

    submitted_id = data.get('id')
    if submitted_id and item.get('id') == submitted_id:
        return True

    submitted_mic_code = normalize_security_mic_code(data.get('mic_code'))
    item_mic_code = normalize_security_mic_code(item.get('mic_code'))
    if submitted_mic_code and item_mic_code:
        return submitted_mic_code == item_mic_code

    submitted_exchange = normalize_security_exchange(data.get('exchange'))
    item_exchange = normalize_security_exchange(item.get('exchange'))
    if submitted_exchange and item_exchange:
        return submitted_exchange.lower() == item_exchange.lower()

    return bool(item.get('is_local'))


def get_local_security_from_submission(data):
    security_id = data.get('id')
    if not security_id:
        return None

    try:
        security = Security.objects.get(pk=security_id, is_active=True)
    except Security.DoesNotExist:
        raise WatchlistSymbolValidationError({'security': 'Selected security is no longer available.'})

    submitted_symbol = normalize_security_symbol(data.get('symbol'))
    if submitted_symbol and security.symbol != submitted_symbol:
        raise WatchlistSymbolValidationError({'security': 'Selected security does not match the submitted symbol.'})

    submitted_mic_code = normalize_security_mic_code(data.get('mic_code'))
    if submitted_mic_code and security.mic_code and security.mic_code != submitted_mic_code:
        raise WatchlistSymbolValidationError({'security': 'Selected security does not match the submitted exchange.'})

    return security


def get_security_search_queries(data):
    queries = []
    for value in (data.get('search_query'), data.get('symbol'), data.get('name')):
        query = normalize_security_search_text(value)
        if len(query) >= 2 and query.lower() not in {item.lower() for item in queries}:
            queries.append(query)
    return queries


def get_verified_search_item(data):
    local_security = get_local_security_from_submission(data)
    if local_security is not None:
        return {
            'id': local_security.id,
            'symbol': local_security.symbol,
            'name': local_security.name,
            'exchange': local_security.exchange,
            'mic_code': local_security.mic_code,
            'instrument_type': 'ETF' if local_security.asset_type == Security.AssetType.ETF else 'Common Stock',
            'country': local_security.country,
            'currency': local_security.currency,
            'is_local': True,
        }

    queries = get_security_search_queries(data)
    if not queries:
        raise WatchlistSymbolValidationError({'symbol': 'Enter a valid symbol or company name.'})

    for query in queries:
        payload = search_security_symbols(query)
        for item in payload.get('items', ()):
            if search_item_matches_submission(item, data):
                return item

    raise WatchlistSymbolValidationError({'security': 'Selected security could not be verified.'})


def get_verified_security_defaults(search_item):
    symbol = normalize_security_symbol(search_item.get('symbol'))
    if not symbol:
        raise WatchlistSymbolValidationError({'symbol': 'Selected security is missing a symbol.'})

    instrument_type = get_search_item_value(search_item, 'instrument_type')
    asset_type = get_asset_type_from_instrument_type(instrument_type)
    if asset_type is None:
        raise WatchlistSymbolValidationError({
            'instrument_type': 'Only supported stock and ETF securities can be added.'
        })

    return {
        'symbol': symbol,
        'name': normalize_security_search_text(search_item.get('name')) or symbol,
        'asset_type': asset_type,
        'exchange': normalize_security_exchange(search_item.get('exchange')),
        'mic_code': normalize_security_mic_code(search_item.get('mic_code')),
        'country': normalize_security_search_text(search_item.get('country')),
        'currency': normalize_security_currency(search_item.get('currency')),
    }


def update_security_metadata_if_needed(security, defaults):
    updates = {}
    for field in ('mic_code', 'country', 'currency'):
        if not getattr(security, field) and defaults.get(field):
            updates[field] = defaults[field]

    if not security.exchange and defaults.get('exchange'):
        updates['exchange'] = defaults['exchange']

    if not security.name and defaults.get('name'):
        updates['name'] = defaults['name']

    if security.asset_type != defaults['asset_type']:
        updates['asset_type'] = defaults['asset_type']

    if not updates:
        return security

    for field, value in updates.items():
        setattr(security, field, value)
    security.save(update_fields=[*updates.keys(), 'updated_at'])
    return security


def get_or_create_verified_security(search_item):
    local_id = search_item.get('id')
    defaults = get_verified_security_defaults(search_item)
    symbol = defaults['symbol']
    mic_code = defaults['mic_code']
    exchange = defaults['exchange']

    queryset = Security.objects.select_for_update().filter(symbol=symbol)

    if local_id:
        try:
            security = queryset.get(pk=local_id, is_active=True)
        except Security.DoesNotExist:
            raise WatchlistSymbolValidationError({'security': 'Selected security is no longer available.'})
        return update_security_metadata_if_needed(security, defaults), False

    security = None
    if mic_code:
        security = queryset.filter(mic_code=mic_code).first()

    if security is None and exchange:
        security = queryset.filter(exchange__iexact=exchange, mic_code='').first()

    if security is None:
        symbol_matches = tuple(queryset)
        if len(symbol_matches) == 1 and not symbol_matches[0].mic_code:
            security = symbol_matches[0]

    if security is not None:
        return update_security_metadata_if_needed(security, defaults), False

    return Security.objects.create(**defaults, is_active=True), True


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
