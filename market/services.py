from dataclasses import dataclass, field, replace
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import logging
from threading import Lock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max, Min, Q
from django.utils import timezone

from .models import Security, SecurityDailyPrice
from .twelve_data import (
    TwelveDataClient,
    TwelveDataError,
    TwelveDataIntervalUnavailableError,
    TwelveDataInvalidSymbolError,
    TwelveDataRateLimitError,
)


logger = logging.getLogger(__name__)

MARKET_DATA_RANGES = {
    '1D': {
        'days': 1,
        'interval': '1min',
        'use_daily_cache': False,
    },
    '1W': {
        'days': 7,
        'interval': '15min',
        'use_daily_cache': False,
    },
    '1M': {
        'months': 1,
        'interval': '1h',
        'use_daily_cache': False,
    },
    '3M': {
        'months': 3,
        'interval': '2h',
        'use_daily_cache': False,
    },
    '6M': {
        'months': 6,
        'interval': '1day',
        'use_daily_cache': True,
    },
    '1Y': {
        'years': 1,
        'interval': '1day',
        'use_daily_cache': True,
    },
    '5Y': {
        'years': 5,
        'interval': '1week',
        'use_daily_cache': False,
    },
    'CUSTOM': {
        'custom': True,
        'use_daily_cache': False,
    },
}
DEFAULT_MARKET_DATA_RANGE = '1D'
MARKET_DATA_INTERVALS = {
    '1m': '1min',
    '1min': '1min',
    '1minute': '1min',
    '1minutes': '1min',
    '5m': '5min',
    '5min': '5min',
    '5minute': '5min',
    '5minutes': '5min',
    '15m': '15min',
    '15min': '15min',
    '15minute': '15min',
    '15minutes': '15min',
    '30m': '30min',
    '30min': '30min',
    '30minute': '30min',
    '30minutes': '30min',
    '1h': '1h',
    '1hour': '1h',
    '1hourly': '1h',
    '60m': '1h',
    '60min': '1h',
    '2h': '2h',
    '2hour': '2h',
    '2hours': '2h',
    '120m': '2h',
    '120min': '2h',
    '4h': '4h',
    '4hour': '4h',
    '4hours': '4h',
    '240m': '4h',
    '240min': '4h',
    '1d': '1day',
    '1day': '1day',
    'day': '1day',
    'daily': '1day',
    '1w': '1week',
    '1week': '1week',
    'week': '1week',
    'weekly': '1week',
}
MARKET_DATA_INTERVAL_DAILY_POINT_ESTIMATES = {
    '1min': 1440,
    '5min': 288,
    '15min': 96,
    '30min': 48,
    '1h': 24,
    '2h': 12,
    '4h': 6,
    '1day': 1,
    '1week': 1 / 7,
}
MARKET_DATA_INDICATOR_WARMUP_BARS = 60
MARKET_DATA_INDICATOR_WARMUP_DAYS = {
    '1min': 7,
    '5min': 14,
    '15min': 14,
    '30min': 14,
    '1h': 30,
    '2h': 45,
    '4h': 60,
    '1day': 90,
    '1week': 560,
}
MARKET_DATA_MAX_REQUEST_POINTS = 5000
MARKET_DATA_MAX_DAILY_OUTPUTSIZE = 5000
MARKET_DATA_FETCH_START_BUFFER_DAYS = 7
MARKET_DATA_RTH_OPEN_MINUTE = 9 * 60 + 30
MARKET_DATA_RTH_CLOSE_MINUTE = 15 * 60 + 59
MARKET_SUMMARY_CACHE_KEY = 'market:summary:v3'
MARKET_DATA_QUOTE_CACHE_KEY_PREFIX = 'market:quote:v1'
MARKET_DATA_SYMBOL_SEARCH_CACHE_KEY_PREFIX = 'market:symbol-search:v1'
MARKET_DATA_QUOTE_SOURCE_CACHED = 'TWELVE_DATA_CACHED_QUOTE'
MARKET_DATA_QUOTE_SOURCE_LAST_CLOSE = 'LAST_AVAILABLE_DAILY_CLOSE'
MARKET_DATA_QUOTE_SOURCE_UNAVAILABLE = 'PRICE_UNAVAILABLE'
MARKET_DATA_QUOTE_STATUS_OK = 'ok'
MARKET_DATA_QUOTE_STATUS_STALE = 'stale'
MARKET_DATA_QUOTE_STATUS_UNAVAILABLE = 'unavailable'
MARKET_DATA_MAX_BATCH_QUOTES = 20
MARKET_DATA_SYMBOL_SEARCH_LIMIT = 12
MARKET_SUMMARY_HISTORY_BARS = 16
MARKET_SUMMARY_ITEMS = (
    {
        'key': 'sp500',
        'symbol': 'SPY',
        'requested_symbol': 'SPX',
        'provider_symbol': 'SPY',
        'display_name': 'S&P 500 ETF proxy',
        'provider_name': 'SPDR S&P 500 ETF Trust',
        'instrument_type': 'ETF',
        'is_proxy': True,
        'proxy_for': 'S&P 500',
    },
    {
        'key': 'nasdaq',
        'symbol': 'ONEQ',
        'requested_symbol': 'IXIC',
        'provider_symbol': 'ONEQ',
        'display_name': 'NASDAQ Composite ETF proxy',
        'provider_name': 'Fidelity Nasdaq Composite Index ETF',
        'instrument_type': 'ETF',
        'is_proxy': True,
        'proxy_for': 'NASDAQ Composite',
    },
    {
        'key': 'dow_jones',
        'symbol': 'DIA',
        'requested_symbol': 'DJI',
        'provider_symbol': 'DIA',
        'display_name': 'Dow Jones Industrial Average ETF proxy',
        'provider_name': 'SPDR Dow Jones Industrial Average ETF Trust',
        'instrument_type': 'ETF',
        'is_proxy': True,
        'proxy_for': 'Dow Jones Industrial Average',
    },
    {
        'key': 'bitcoin',
        'symbol': 'BTC/USD',
        'requested_symbol': 'BTC/USD',
        'provider_symbol': 'BTC/USD',
        'display_name': 'Bitcoin',
        'provider_name': 'Bitcoin US Dollar',
        'instrument_type': 'Digital Currency',
        'is_proxy': False,
        'proxy_for': '',
    },
)
SUPPORTED_MARKET_DATA_ASSET_TYPES = {
    Security.AssetType.STOCK,
    Security.AssetType.ETF,
}
PREFERRED_SECURITY_COUNTRIES = {'UNITED STATES', 'USA', 'US'}
PREFERRED_SECURITY_EXCHANGES = {
    'NASDAQ',
    'NASDAQ GLOBAL SELECT',
    'NASDAQ GLOBAL MARKET',
    'NASDAQ CAPITAL MARKET',
    'NYSE',
    'NEW YORK STOCK EXCHANGE',
    'NYSE ARCA',
    'NYSEARCA',
    'NYSE AMERICAN',
}
PREFERRED_SECURITY_MIC_CODES = {'XNAS', 'XNYS', 'ARCX', 'XASE'}

_symbol_search_locks = {}
_symbol_search_locks_guard = Lock()


class MarketDataError(Exception):
    pass


class UnsupportedMarketDataRange(MarketDataError):
    pass


class UnsupportedMarketDataInterval(MarketDataError):
    pass


class InvalidMarketDataDateRange(MarketDataError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Invalid market data date range.')


class UnsupportedMarketDataSecurity(MarketDataError):
    pass


class MarketDataUnavailable(MarketDataError):
    pass


class MarketDataRateLimited(MarketDataError):
    pass


class MarketDataInvalidSymbol(MarketDataError):
    pass


@dataclass(frozen=True)
class MarketDataResult:
    security: Security
    range_key: str
    interval: str
    values: list
    source: str
    is_stale: bool = False
    warmup_values: tuple = ()
    data_source: str = 'twelve_data'
    cache_status: str = 'not_used'
    last_updated: str = ''
    upstream_error: str = ''
    fetched_at: str = ''
    provider_metadata: dict = field(default_factory=dict)
    session_close_adjustments: tuple = ()


@dataclass(frozen=True)
class MarketDataQuoteResult:
    security: Security
    price: Decimal
    change: Decimal
    percent_change: Decimal
    currency: str
    source: str
    as_of: str
    data_status: str = MARKET_DATA_QUOTE_STATUS_OK
    cache_status: str = 'not_used'
    is_stale: bool = False
    error: str = ''


@dataclass(frozen=True)
class SecuritySearchResult:
    id: int | None
    symbol: str
    name: str
    exchange: str
    mic_code: str
    instrument_type: str
    country: str
    currency: str
    is_local: bool = False


@dataclass(frozen=True)
class MarketSummaryItemResult:
    key: str
    symbol: str
    display_name: str
    requested_symbol: str
    provider_symbol: str
    provider_name: str
    instrument_type: str
    is_proxy: bool
    proxy_for: str
    latest_price: Decimal | None
    previous_close: Decimal | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    updated_at: str
    sparkline: tuple
    data_status: str
    error: str = ''
    error_code: str = ''
    error_message: str = ''
    provider_http_status: int | None = None
    provider_status: str = ''
    provider_code: str | int | None = None
    provider_message: str = ''
    endpoint: str = 'time_series'
    interval: str = '1day'
    outputsize: int = MARKET_SUMMARY_HISTORY_BARS
    used_cache: bool = False
    used_fallback: bool = False


@dataclass(frozen=True)
class MarketSummaryResult:
    source: str
    updated_at: str
    status: str
    cache_status: str
    generated_at: str
    items: tuple


def normalize_security_search_text(value):
    return str(value or '').strip()


def normalize_security_symbol(value):
    return normalize_security_search_text(value).upper()


def normalize_security_exchange(value):
    return normalize_security_search_text(value)


def normalize_security_mic_code(value):
    return normalize_security_search_text(value).upper()


def normalize_security_currency(value):
    return (normalize_security_search_text(value) or 'USD').upper()


def get_security_symbol_search_cache_ttl_seconds():
    return getattr(settings, 'MARKET_DATA_SYMBOL_SEARCH_CACHE_TTL_SECONDS', 300)


def get_symbol_search_cache_key(query):
    return f'{MARKET_DATA_SYMBOL_SEARCH_CACHE_KEY_PREFIX}:{query.lower()}'


def get_symbol_search_lock(cache_key):
    with _symbol_search_locks_guard:
        if cache_key not in _symbol_search_locks:
            _symbol_search_locks[cache_key] = Lock()
        return _symbol_search_locks[cache_key]


def get_instrument_type_label(asset_type):
    if asset_type == Security.AssetType.ETF:
        return 'ETF'
    return 'Common Stock'


def get_asset_type_from_instrument_type(instrument_type):
    normalized = normalize_security_search_text(instrument_type).lower()
    if not normalized:
        return None
    if 'etf' in normalized or 'exchange traded fund' in normalized or 'exchange-traded fund' in normalized:
        return Security.AssetType.ETF
    if 'stock' in normalized or 'equity' in normalized or 'common share' in normalized:
        return Security.AssetType.STOCK
    return None


def normalize_remote_security_search_result(raw_result):
    symbol = normalize_security_symbol(raw_result.get('symbol'))
    if not symbol:
        return None

    instrument_type = normalize_security_search_text(
        raw_result.get('instrument_type')
        or raw_result.get('type')
        or raw_result.get('asset_type')
    )

    return SecuritySearchResult(
        id=None,
        symbol=symbol,
        name=normalize_security_search_text(
            raw_result.get('instrument_name')
            or raw_result.get('name')
            or raw_result.get('description')
            or symbol
        ),
        exchange=normalize_security_exchange(raw_result.get('exchange')),
        mic_code=normalize_security_mic_code(raw_result.get('mic_code')),
        instrument_type=instrument_type or 'Unknown',
        country=normalize_security_search_text(raw_result.get('country')),
        currency=normalize_security_currency(raw_result.get('currency')),
        is_local=False,
    )


def build_local_security_search_result(security):
    return SecuritySearchResult(
        id=security.id,
        symbol=security.symbol,
        name=security.name,
        exchange=security.exchange,
        mic_code=security.mic_code,
        instrument_type=get_instrument_type_label(security.asset_type),
        country=security.country,
        currency=security.currency,
        is_local=True,
    )


def security_search_result_key(result):
    return (
        result.symbol,
        result.mic_code or result.exchange.upper(),
    )


def find_matching_local_security(result, local_results):
    exact_key = security_search_result_key(result)
    for local_result in local_results:
        if security_search_result_key(local_result) == exact_key:
            return local_result

    if result.mic_code:
        for local_result in local_results:
            if local_result.symbol == result.symbol and local_result.mic_code == result.mic_code:
                return local_result

    if result.exchange:
        for local_result in local_results:
            if local_result.symbol == result.symbol and local_result.exchange.lower() == result.exchange.lower():
                return local_result

    symbol_matches = [local_result for local_result in local_results if local_result.symbol == result.symbol]
    return symbol_matches[0] if len(symbol_matches) == 1 else None


def merge_local_security_result(remote_result, local_result):
    if local_result is None:
        return remote_result
    return SecuritySearchResult(
        id=local_result.id,
        symbol=remote_result.symbol,
        name=remote_result.name or local_result.name,
        exchange=remote_result.exchange or local_result.exchange,
        mic_code=remote_result.mic_code or local_result.mic_code,
        instrument_type=remote_result.instrument_type or local_result.instrument_type,
        country=remote_result.country or local_result.country,
        currency=remote_result.currency or local_result.currency,
        is_local=True,
    )


def is_preferred_security_result(result):
    asset_type = get_asset_type_from_instrument_type(result.instrument_type)
    country = result.country.upper()
    exchange = result.exchange.upper()
    mic_code = result.mic_code.upper()
    return (
        asset_type in SUPPORTED_MARKET_DATA_ASSET_TYPES
        and (
            country in PREFERRED_SECURITY_COUNTRIES
            or exchange in PREFERRED_SECURITY_EXCHANGES
            or mic_code in PREFERRED_SECURITY_MIC_CODES
        )
    )


def get_security_search_rank(result, query):
    normalized_query = query.upper()
    symbol = result.symbol.upper()
    name = result.name.upper()
    exchange = result.exchange.upper()
    country = result.country.upper()
    mic_code = result.mic_code.upper()
    asset_type = get_asset_type_from_instrument_type(result.instrument_type)

    if symbol == normalized_query:
        match_score = 0
    elif symbol.startswith(normalized_query):
        match_score = 10
    elif name.startswith(normalized_query):
        match_score = 20
    elif normalized_query in symbol:
        match_score = 30
    elif normalized_query in name:
        match_score = 40
    else:
        match_score = 60

    return (
        match_score,
        0 if result.is_local else 1,
        0 if asset_type in SUPPORTED_MARKET_DATA_ASSET_TYPES else 1,
        0 if country in PREFERRED_SECURITY_COUNTRIES else 1,
        0 if exchange in PREFERRED_SECURITY_EXCHANGES or mic_code in PREFERRED_SECURITY_MIC_CODES else 1,
        result.symbol,
        result.exchange,
    )


def serialize_security_search_result(result):
    return {
        'id': result.id,
        'symbol': result.symbol,
        'name': result.name,
        'exchange': result.exchange,
        'mic_code': result.mic_code,
        'instrument_type': result.instrument_type,
        'country': result.country,
        'currency': result.currency,
        'is_local': result.is_local,
        'is_preferred': is_preferred_security_result(result),
    }


def get_local_security_search_results(query, limit=MARKET_DATA_SYMBOL_SEARCH_LIMIT):
    return tuple(
        build_local_security_search_result(security)
        for security in (
            Security.objects
            .filter(
                Q(symbol__icontains=query)
                | Q(name__icontains=query)
                | Q(exchange__icontains=query)
                | Q(mic_code__icontains=query),
                is_active=True,
            )
            .order_by('symbol', 'exchange', 'id')[:limit]
        )
    )


def build_security_search_payload(query, client=None):
    local_results = get_local_security_search_results(query)
    remote_results = ()
    remote_error = ''

    try:
        market_data_client = client or TwelveDataClient()
        remote_results = tuple(
            result
            for result in (
                normalize_remote_security_search_result(item)
                for item in market_data_client.symbol_search(query)
            )
            if result is not None
        )
    except TwelveDataRateLimitError as exc:
        if not local_results:
            raise MarketDataRateLimited('Market data provider rate limit reached. Please try again later.') from exc
        remote_error = 'Market data provider rate limit reached. Local results are shown.'
    except TwelveDataError as exc:
        if not local_results:
            raise MarketDataUnavailable('Security search is temporarily unavailable. Please try again later.') from exc
        remote_error = 'Remote security search is temporarily unavailable. Local results are shown.'

    merged_results = {}
    used_local_ids = set()
    for remote_result in remote_results:
        local_result = find_matching_local_security(remote_result, local_results)
        merged_result = merge_local_security_result(remote_result, local_result)
        if local_result:
            used_local_ids.add(local_result.id)
        key = security_search_result_key(merged_result)
        current = merged_results.get(key)
        if current is None or get_security_search_rank(merged_result, query) < get_security_search_rank(current, query):
            merged_results[key] = merged_result

    for local_result in local_results:
        if local_result.id in used_local_ids:
            continue
        merged_results.setdefault(security_search_result_key(local_result), local_result)

    ordered_results = sorted(merged_results.values(), key=lambda result: get_security_search_rank(result, query))
    items = tuple(serialize_security_search_result(result) for result in ordered_results[:MARKET_DATA_SYMBOL_SEARCH_LIMIT])

    return {
        'query': query,
        'items': items,
        'metadata': {
            'query': query,
            'count': len(items),
            'local_count': sum(1 for item in items if item['is_local']),
            'remote_error': remote_error,
            'cache_status': 'fresh',
        },
    }


def search_security_symbols(query, client=None, force_refresh=False):
    normalized_query = normalize_security_search_text(query)
    if not normalized_query:
        return {
            'query': '',
            'items': (),
            'metadata': {
                'query': '',
                'count': 0,
                'local_count': 0,
                'remote_error': '',
                'cache_status': 'not_used',
            },
        }

    cache_ttl = get_security_symbol_search_cache_ttl_seconds()
    cache_key = get_symbol_search_cache_key(normalized_query)
    if client is None and cache_ttl > 0 and not force_refresh:
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return {
                **cached_payload,
                'metadata': {
                    **cached_payload.get('metadata', {}),
                    'cache_status': 'hit',
                },
            }

    lock = get_symbol_search_lock(cache_key)
    with lock:
        if client is None and cache_ttl > 0 and not force_refresh:
            cached_payload = cache.get(cache_key)
            if cached_payload is not None:
                return {
                    **cached_payload,
                    'metadata': {
                        **cached_payload.get('metadata', {}),
                        'cache_status': 'hit',
                    },
                }

        payload = build_security_search_payload(normalized_query, client=client)
        if client is None and cache_ttl > 0:
            cache.set(cache_key, payload, cache_ttl)
        return payload


def normalize_range(range_key):
    normalized = (range_key or DEFAULT_MARKET_DATA_RANGE).upper()
    if normalized not in MARKET_DATA_RANGES:
        raise UnsupportedMarketDataRange('Supported ranges are 1D, 1W, 1M, 3M, 6M, 1Y, 5Y, and Custom.')
    return normalized


def normalize_interval(interval):
    if not interval:
        return ''

    normalized = str(interval).strip().lower().replace(' ', '')
    if normalized not in MARKET_DATA_INTERVALS:
        raise UnsupportedMarketDataInterval(
            'Supported intervals are 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1D, and 1W.'
        )
    return MARKET_DATA_INTERVALS[normalized]


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


def get_market_data_timezone():
    return ZoneInfo(getattr(settings, 'TWELVE_DATA_TIMEZONE', 'America/New_York'))


def get_previous_market_weekday(value):
    previous_date = value - timedelta(days=1)
    while previous_date.weekday() >= 5:
        previous_date -= timedelta(days=1)
    return previous_date


def get_latest_complete_market_date(now=None):
    reference_time = now or timezone.now()
    if timezone.is_naive(reference_time):
        reference_time = reference_time.replace(tzinfo=ZoneInfo('UTC'))

    market_time = reference_time.astimezone(get_market_data_timezone())
    market_date = market_time.date()
    if market_date.weekday() >= 5:
        return get_previous_market_weekday(market_date)

    close_buffer = timedelta(minutes=getattr(settings, 'MARKET_DATA_COMPLETE_DAY_BUFFER_MINUTES', 15))
    complete_after = datetime.combine(
        market_date,
        time(16, 0),
        tzinfo=get_market_data_timezone(),
    ) + close_buffer
    if market_time >= complete_after:
        return market_date

    return get_previous_market_weekday(market_date)


def get_range_date_window(range_key, start_date=None, end_date=None):
    latest_complete_date = get_latest_complete_market_date()
    config = MARKET_DATA_RANGES[range_key]

    if config.get('custom'):
        requested_start_date = parse_market_data_date(start_date, 'start_date')
        requested_end_date = parse_market_data_date(end_date, 'end_date')
    else:
        requested_end_date = latest_complete_date
        if 'days' in config:
            requested_start_date = latest_complete_date - timedelta(days=config['days'])
        elif 'months' in config:
            requested_start_date = subtract_months(latest_complete_date, config['months'])
        else:
            requested_start_date = subtract_years(latest_complete_date, config['years'])

    errors = {}
    if requested_start_date > requested_end_date:
        errors['start_date'] = 'Start date cannot be later than end date.'
    if requested_start_date > latest_complete_date:
        errors['start_date'] = 'Start date cannot be later than the latest complete market day.'
    if requested_end_date > latest_complete_date:
        errors['end_date'] = 'End date cannot be later than the latest complete market day.'
    if errors:
        raise InvalidMarketDataDateRange(errors)

    return requested_start_date, requested_end_date


def get_interval_for_date_window(start_date, end_date):
    span_days = (end_date - start_date).days
    if span_days <= 1:
        return '1min'
    if span_days <= 7:
        return '15min'
    if span_days <= 31:
        return '1h'
    if span_days <= 92:
        return '2h'
    if span_days <= 365:
        return '1day'
    return '1week'


def get_market_data_interval(range_key, start_date, end_date, interval=None):
    requested_interval = normalize_interval(interval)
    if requested_interval:
        return requested_interval

    config = MARKET_DATA_RANGES[range_key]
    if config.get('custom'):
        return get_interval_for_date_window(start_date, end_date)
    return config['interval']


def range_uses_daily_cache(range_key, interval):
    return interval == '1day'


def validate_market_data_request_size(start_date, end_date, interval):
    span_days = (end_date - start_date).days + 1
    estimated_points = span_days * MARKET_DATA_INTERVAL_DAILY_POINT_ESTIMATES[interval]
    if estimated_points > MARKET_DATA_MAX_REQUEST_POINTS:
        raise InvalidMarketDataDateRange({
            'interval': 'This date range is too large for the selected interval. Choose a shorter date range or a larger interval.',
        })


def get_indicator_warmup_start_date(start_date, interval):
    return start_date - timedelta(days=MARKET_DATA_INDICATOR_WARMUP_DAYS[interval])


def split_visible_and_warmup_values(values, visible_start_date):
    visible_values = []
    warmup_values = []
    for value in values:
        value_date = getattr(value, 'date', None)
        if value_date is not None and value_date < visible_start_date:
            warmup_values.append(value)
        else:
            visible_values.append(value)

    return visible_values, tuple(warmup_values[-MARKET_DATA_INDICATOR_WARMUP_BARS:])


def keep_latest_intraday_session_values(visible_values, warmup_values):
    if not visible_values:
        return visible_values, warmup_values

    dated_values = [value for value in visible_values if getattr(value, 'date', None) is not None]
    if not dated_values:
        return visible_values, warmup_values

    latest_visible_date = max(value.date for value in dated_values)
    display_values = [value for value in visible_values if getattr(value, 'date', None) == latest_visible_date]
    prior_visible_values = [
        value for value in visible_values
        if getattr(value, 'date', None) is not None and value.date < latest_visible_date
    ]
    calculation_warmup_values = tuple([
        *warmup_values,
        *prior_visible_values,
    ][-MARKET_DATA_INDICATOR_WARMUP_BARS:])
    return display_values, calculation_warmup_values


def get_provider_start_date(start_date):
    return start_date - timedelta(days=MARKET_DATA_FETCH_START_BUFFER_DAYS)


def get_daily_outputsize_for_window(start_date, end_date):
    return min(max((end_date - start_date).days + 10, 2), MARKET_DATA_MAX_DAILY_OUTPUTSIZE)


def fetch_daily_bars_for_window(security, start_date, end_date, client):
    if end_date >= get_latest_complete_market_date():
        bars = client.get_time_series(
            symbol=security.symbol,
            interval='1day',
            outputsize=get_daily_outputsize_for_window(start_date, end_date),
        )
        return [bar for bar in bars if start_date <= bar.date <= end_date]

    return client.get_time_series(
        symbol=security.symbol,
        interval='1day',
        start_date=start_date,
        end_date=end_date,
    )


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

    return earliest_date <= start_date and latest_date >= end_date


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
    bars = fetch_daily_bars_for_window(security, get_provider_start_date(start_date), end_date, market_data_client)
    upsert_daily_bars(security, bars)


def fetch_time_series_prices(security, start_date, end_date, interval, client=None):
    market_data_client = client or TwelveDataClient()
    return market_data_client.get_time_series(
        symbol=security.symbol,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
    )


def get_bar_timestamp(bar):
    timestamp = getattr(bar, 'timestamp', '')
    if timestamp:
        return timestamp

    value = getattr(bar, 'date', '')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def is_intraday_interval(interval):
    return interval in {'1min', '5min', '15min', '30min', '1h', '2h', '4h'}


def get_bar_market_minute(bar):
    timestamp = get_bar_timestamp(bar)
    try:
        timestamp_time = time.fromisoformat(timestamp[11:19])
    except (TypeError, ValueError):
        return None
    return timestamp_time.hour * 60 + timestamp_time.minute


def is_regular_trading_hours_bar(bar):
    market_minute = get_bar_market_minute(bar)
    if market_minute is None:
        return False
    return MARKET_DATA_RTH_OPEN_MINUTE <= market_minute <= MARKET_DATA_RTH_CLOSE_MINUTE


def get_provider_response_summary(client):
    metadata = get_client_response_metadata(client)
    return {
        'endpoint': metadata.get('endpoint', ''),
        'params': metadata.get('params', {}),
        'http_status': metadata.get('http_status'),
        'status': metadata.get('provider_status', ''),
        'code': metadata.get('provider_code'),
        'message': metadata.get('provider_message', ''),
    }


def apply_official_session_closes(security, values, start_date, end_date, client):
    if not values:
        return values, (), {}

    daily_bars = fetch_daily_bars_for_window(security, start_date, end_date, client)
    daily_metadata = get_provider_response_summary(client)
    official_closes = {bar.date: bar.close for bar in daily_bars}
    last_rth_index_by_date = {}
    for index, value in enumerate(values):
        if value.date in official_closes and is_regular_trading_hours_bar(value):
            last_rth_index_by_date[value.date] = index

    adjusted_values = list(values)
    adjustments = []
    for session_date, value_index in sorted(last_rth_index_by_date.items()):
        official_close = official_closes[session_date]
        current_bar = adjusted_values[value_index]
        if current_bar.close == official_close:
            continue
        adjusted_values[value_index] = replace(current_bar, close=official_close)
        adjustments.append({
            'date': session_date.isoformat(),
            'timestamp': get_bar_timestamp(current_bar),
            'original_close': str(current_bar.close),
            'official_close': str(official_close),
            'source': 'twelve_data_1day_close',
        })

    logger.info(
        'Market data official session close alignment symbol=%s daily_count=%s daily_first=%s daily_last=%s adjustments=%s',
        security.symbol,
        len(daily_bars),
        get_bar_timestamp(daily_bars[0]) if daily_bars else '',
        get_bar_timestamp(daily_bars[-1]) if daily_bars else '',
        adjustments,
    )
    return adjusted_values, tuple(adjustments), daily_metadata


def order_market_data_values(values):
    return sorted(values, key=lambda value: (getattr(value, 'date', None) or date.min, get_bar_timestamp(value)))


def get_values_last_updated(values):
    if not values:
        return ''
    return get_bar_timestamp(values[-1])


def build_time_series_provider_metadata(client, values):
    response_summary = get_provider_response_summary(client)
    return {
        **response_summary,
        'record_count': len(values),
        'first_timestamp': get_bar_timestamp(values[0]) if values else '',
        'last_timestamp': get_bar_timestamp(values[-1]) if values else '',
    }


def build_market_data_result(
    *,
    security,
    range_key,
    interval,
    values,
    warmup_values=(),
    is_stale=False,
    data_source='twelve_data',
    cache_status='not_used',
    upstream_error='',
    fetched_at='',
    provider_metadata=None,
    session_close_adjustments=(),
):
    ordered_values = order_market_data_values(values)
    ordered_warmup_values = tuple(order_market_data_values(warmup_values))
    result = MarketDataResult(
        security=security,
        range_key=range_key,
        interval=interval,
        values=ordered_values,
        source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
        is_stale=is_stale,
        warmup_values=ordered_warmup_values,
        data_source=data_source,
        cache_status=cache_status,
        last_updated=get_values_last_updated(ordered_values),
        upstream_error=upstream_error,
        fetched_at=fetched_at or timezone.now().isoformat(),
        provider_metadata=provider_metadata or {},
        session_close_adjustments=tuple(session_close_adjustments),
    )
    logger.info(
        'Market data result symbol=%s range=%s interval=%s count=%s first=%s last=%s data_source=%s cache_status=%s is_stale=%s upstream_error=%s provider_last=%s session_close_adjustments=%s',
        security.symbol,
        range_key,
        interval,
        len(result.values),
        get_bar_timestamp(result.values[0]) if result.values else '',
        get_bar_timestamp(result.values[-1]) if result.values else '',
        result.data_source,
        result.cache_status,
        result.is_stale,
        result.upstream_error,
        result.provider_metadata.get('time_series', {}).get('last_timestamp', ''),
        result.session_close_adjustments,
    )
    return result


def get_market_summary_error(exc):
    if isinstance(exc, TwelveDataRateLimitError):
        return 'Market data provider rate limit reached. Please try again later.'
    if isinstance(exc, TwelveDataInvalidSymbolError):
        return 'Market data is not available for this market item.'
    if isinstance(exc, TwelveDataIntervalUnavailableError):
        return 'Market data for this interval is not available.'
    return 'Market data is temporarily unavailable.'


def get_provider_error_metadata(exc):
    return {
        'provider_http_status': getattr(exc, 'http_status', None),
        'provider_status': getattr(exc, 'provider_status', '') or '',
        'provider_code': getattr(exc, 'provider_code', None),
        'provider_message': getattr(exc, 'provider_message', '') or str(exc),
    }


def get_client_response_metadata(client):
    return getattr(client, 'last_response_metadata', {}) or {}


def build_unavailable_market_summary_item(config, error, exc=None):
    provider_metadata = get_provider_error_metadata(exc) if exc else {}
    return MarketSummaryItemResult(
        key=config['key'],
        symbol=config['symbol'],
        display_name=config['display_name'],
        requested_symbol=config['requested_symbol'],
        provider_symbol=config['provider_symbol'],
        provider_name=config['provider_name'],
        instrument_type=config['instrument_type'],
        is_proxy=config['is_proxy'],
        proxy_for=config['proxy_for'],
        latest_price=None,
        previous_close=None,
        absolute_change=None,
        percentage_change=None,
        updated_at='',
        sparkline=(),
        data_status='unavailable',
        error=error,
        error_code=str(provider_metadata.get('provider_code') or ''),
        error_message=provider_metadata.get('provider_message') or error,
        provider_http_status=provider_metadata.get('provider_http_status'),
        provider_status=provider_metadata.get('provider_status', ''),
        provider_code=provider_metadata.get('provider_code'),
        provider_message=provider_metadata.get('provider_message', ''),
    )


def build_market_summary_item(config, bars, response_metadata=None):
    ordered_bars = sorted(bars, key=lambda bar: (bar.date, get_bar_timestamp(bar)))
    if len(ordered_bars) < 2:
        raise MarketDataUnavailable('Market data is temporarily unavailable.')

    response_metadata = response_metadata or {}
    latest_bar = ordered_bars[-1]
    previous_bar = ordered_bars[-2]
    absolute_change = latest_bar.close - previous_bar.close
    percentage_change = (
        (absolute_change / previous_bar.close) * Decimal('100')
        if previous_bar.close != 0
        else Decimal('0')
    )

    return MarketSummaryItemResult(
        key=config['key'],
        symbol=config['symbol'],
        display_name=config['display_name'],
        requested_symbol=config['requested_symbol'],
        provider_symbol=config['provider_symbol'],
        provider_name=config['provider_name'],
        instrument_type=config['instrument_type'],
        is_proxy=config['is_proxy'],
        proxy_for=config['proxy_for'],
        latest_price=latest_bar.close,
        previous_close=previous_bar.close,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        updated_at=get_bar_timestamp(latest_bar),
        sparkline=tuple({
            'datetime': get_bar_timestamp(bar),
            'close': bar.close,
        } for bar in ordered_bars),
        data_status='ok',
        provider_http_status=response_metadata.get('http_status'),
        provider_status=response_metadata.get('provider_status', ''),
        provider_code=response_metadata.get('provider_code'),
        provider_message=response_metadata.get('provider_message', ''),
    )


def serialize_market_summary_decimal(value):
    return None if value is None else float(value.quantize(Decimal('0.000001')))


def serialize_market_summary_item(item):
    return {
        'id': item.key,
        'key': item.key,
        'symbol': item.symbol,
        'display_name': item.display_name,
        'requested_symbol': item.requested_symbol,
        'provider_symbol': item.provider_symbol,
        'provider_name': item.provider_name,
        'instrument_type': item.instrument_type,
        'is_proxy': item.is_proxy,
        'proxy_for': item.proxy_for,
        'latest_price': serialize_market_summary_decimal(item.latest_price),
        'previous_close': serialize_market_summary_decimal(item.previous_close),
        'absolute_change': serialize_market_summary_decimal(item.absolute_change),
        'percentage_change': serialize_market_summary_decimal(item.percentage_change),
        'updated_at': item.updated_at,
        'sparkline': tuple({
            'datetime': point['datetime'],
            'close': serialize_market_summary_decimal(point['close']),
        } for point in item.sparkline),
        'data_status': item.data_status,
        'error': item.error,
        'error_code': item.error_code,
        'error_message': item.error_message,
        'provider_http_status': item.provider_http_status,
        'provider_status': item.provider_status,
        'provider_code': item.provider_code,
        'provider_message': item.provider_message,
        'endpoint': item.endpoint,
        'interval': item.interval,
        'outputsize': item.outputsize,
        'used_cache': item.used_cache,
        'used_fallback': item.used_fallback,
    }


def serialize_market_summary(result):
    symbols = tuple(item.symbol for item in result.items)
    provider_symbols = tuple(item.provider_symbol for item in result.items)
    requested_symbols = tuple(item.requested_symbol for item in result.items)
    return {
        'source': result.source,
        'updated_at': result.updated_at,
        'status': result.status,
        'cache_status': result.cache_status,
        'generated_at': result.generated_at,
        'metadata': {
            'count': len(result.items),
            'generated_at': result.generated_at,
            'source': result.source,
            'symbols': symbols,
            'provider_symbols': provider_symbols,
            'requested_symbols': requested_symbols,
            'cache_status': result.cache_status,
        },
        'items': tuple(serialize_market_summary_item(item) for item in result.items),
    }


def set_market_summary_cache_status(summary, cache_status):
    return {
        **summary,
        'cache_status': cache_status,
        'metadata': {
            **summary.get('metadata', {}),
            'cache_status': cache_status,
        },
    }


def log_market_summary_item(item, cache_status):
    logger.info(
        'Market summary asset display_symbol=%s requested_symbol=%s provider_symbol=%s endpoint=%s interval=%s outputsize=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s record_count=%s cache_status=%s used_cache=%s used_fallback=%s data_status=%s',
        item.get('symbol'),
        item.get('requested_symbol'),
        item.get('provider_symbol'),
        item.get('endpoint'),
        item.get('interval'),
        item.get('outputsize'),
        item.get('provider_http_status'),
        item.get('provider_status'),
        item.get('provider_code'),
        item.get('provider_message'),
        len(item.get('sparkline') or ()),
        cache_status,
        cache_status == 'hit',
        item.get('used_fallback', False),
        item.get('data_status'),
    )


def get_market_summary(client=None, force_refresh=False):
    cache_ttl = getattr(settings, 'MARKET_SUMMARY_CACHE_TTL_SECONDS', 60)
    if client is None and cache_ttl > 0 and not force_refresh:
        cached_summary = cache.get(MARKET_SUMMARY_CACHE_KEY)
        if cached_summary is not None:
            cached_summary = set_market_summary_cache_status(cached_summary, 'hit')
            for cached_item in cached_summary.get('items', ()):
                log_market_summary_item(cached_item, 'hit')
            return cached_summary

    market_data_client = client or TwelveDataClient()
    items = []
    for config in MARKET_SUMMARY_ITEMS:
        logger.info(
            'Market summary request display_symbol=%s requested_symbol=%s provider_symbol=%s endpoint=time_series interval=1day outputsize=%s cache_status=%s used_fallback=False',
            config['symbol'],
            config['requested_symbol'],
            config['provider_symbol'],
            MARKET_SUMMARY_HISTORY_BARS,
            'bypass' if force_refresh else 'miss',
        )
        try:
            bars = market_data_client.get_time_series(
                symbol=config['provider_symbol'],
                interval='1day',
                outputsize=MARKET_SUMMARY_HISTORY_BARS,
            )
            item = build_market_summary_item(config, bars, get_client_response_metadata(market_data_client))
            items.append(item)
        except TwelveDataError as exc:
            item = build_unavailable_market_summary_item(config, get_market_summary_error(exc), exc)
            items.append(item)
        except MarketDataUnavailable as exc:
            item = build_unavailable_market_summary_item(config, str(exc), exc)
            items.append(item)

        logger.info(
            'Market summary asset display_symbol=%s requested_symbol=%s provider_symbol=%s endpoint=%s interval=%s outputsize=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s record_count=%s cache_status=%s used_cache=False used_fallback=%s data_status=%s',
            items[-1].symbol,
            items[-1].requested_symbol,
            items[-1].provider_symbol,
            items[-1].endpoint,
            items[-1].interval,
            items[-1].outputsize,
            items[-1].provider_http_status,
            items[-1].provider_status,
            items[-1].provider_code,
            items[-1].provider_message,
            len(items[-1].sparkline),
            'bypass' if force_refresh else 'miss',
            items[-1].used_fallback,
            items[-1].data_status,
        )

    available_items = [item for item in items if item.data_status == 'ok']
    updated_at = max((item.updated_at for item in available_items), default='')
    if len(available_items) == len(items):
        status = 'ok'
    elif available_items:
        status = 'partial'
    else:
        status = 'unavailable'

    summary = serialize_market_summary(MarketSummaryResult(
        source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
        updated_at=updated_at,
        status=status,
        cache_status='fresh',
        generated_at=timezone.now().isoformat(),
        items=tuple(items),
    ))
    if client is None and cache_ttl > 0:
        cache.set(MARKET_SUMMARY_CACHE_KEY, summary, cache_ttl)
    return summary


def get_quote_cache_ttl_seconds():
    return getattr(settings, 'MARKET_DATA_QUOTE_CACHE_TTL_SECONDS', 60)


def get_quote_cache_key(security):
    return f'{MARKET_DATA_QUOTE_CACHE_KEY_PREFIX}:{security.id}:{security.symbol}'


def serialize_quote_for_cache(result):
    return {
        'price': str(result.price),
        'change': str(result.change),
        'percent_change': str(result.percent_change),
        'currency': result.currency,
        'as_of': result.as_of,
    }


def build_quote_result_from_cache(security, payload):
    return MarketDataQuoteResult(
        security=security,
        price=Decimal(str(payload['price'])),
        change=Decimal(str(payload['change'])),
        percent_change=Decimal(str(payload['percent_change'])),
        currency=payload.get('currency') or security.currency,
        source=MARKET_DATA_QUOTE_SOURCE_CACHED,
        as_of=payload.get('as_of', ''),
        data_status=MARKET_DATA_QUOTE_STATUS_OK,
        cache_status='hit',
        is_stale=False,
    )


def cache_quote_result(result):
    cache_ttl = get_quote_cache_ttl_seconds()
    if cache_ttl <= 0:
        return
    cache.set(get_quote_cache_key(result.security), serialize_quote_for_cache(result), cache_ttl)


def calculate_quote_percent_change(change, previous_price):
    if not previous_price:
        return Decimal('0')
    return (change / previous_price) * Decimal('100')


def get_latest_cached_daily_quote(security, error=''):
    latest_price = (
        SecurityDailyPrice.objects
        .filter(security=security)
        .order_by('-date')
        .first()
    )
    if latest_price is None:
        return None

    previous_price = (
        SecurityDailyPrice.objects
        .filter(security=security, date__lt=latest_price.date)
        .order_by('-date')
        .first()
    )
    change = latest_price.close - previous_price.close if previous_price else Decimal('0')
    percent_change = calculate_quote_percent_change(
        change,
        previous_price.close if previous_price else Decimal('0'),
    )

    return MarketDataQuoteResult(
        security=security,
        price=latest_price.close,
        change=change,
        percent_change=percent_change,
        currency=security.currency,
        source=MARKET_DATA_QUOTE_SOURCE_LAST_CLOSE,
        as_of=latest_price.date.isoformat(),
        data_status=MARKET_DATA_QUOTE_STATUS_STALE,
        cache_status='daily_fallback',
        is_stale=True,
        error=error,
    )


def build_unavailable_quote_result(security, error):
    return MarketDataQuoteResult(
        security=security,
        price=Decimal('0'),
        change=Decimal('0'),
        percent_change=Decimal('0'),
        currency=security.currency,
        source=MARKET_DATA_QUOTE_SOURCE_UNAVAILABLE,
        as_of='',
        data_status=MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
        cache_status='unavailable',
        is_stale=True,
        error=error,
    )


def get_security_latest_quote(
    security,
    client=None,
    force_refresh=False,
    allow_cached=True,
    allow_stale=False,
):
    if security.asset_type not in SUPPORTED_MARKET_DATA_ASSET_TYPES:
        raise UnsupportedMarketDataSecurity('Only stocks and ETFs are supported for quote market data.')

    if client is None and allow_cached and not force_refresh and get_quote_cache_ttl_seconds() > 0:
        cached_quote = cache.get(get_quote_cache_key(security))
        if cached_quote is not None:
            return build_quote_result_from_cache(security, cached_quote)

    market_data_client = client or TwelveDataClient()
    try:
        quote = market_data_client.get_quote(symbol=security.symbol)
    except TwelveDataRateLimitError as exc:
        if allow_stale:
            cached_daily_quote = get_latest_cached_daily_quote(
                security,
                error='Market data provider rate limit reached. Last available cached price is shown.',
            )
            if cached_daily_quote is not None:
                return cached_daily_quote
        raise MarketDataRateLimited('Market data provider rate limit reached. Please try again later.') from exc
    except TwelveDataInvalidSymbolError as exc:
        if allow_stale:
            cached_daily_quote = get_latest_cached_daily_quote(
                security,
                error='Market data is not available for this security. Last available cached price is shown.',
            )
            if cached_daily_quote is not None:
                return cached_daily_quote
        raise MarketDataInvalidSymbol('Market data is not available for this security.') from exc
    except TwelveDataError as exc:
        if allow_stale:
            cached_daily_quote = get_latest_cached_daily_quote(
                security,
                error='Latest quote is temporarily unavailable. Last available cached price is shown.',
            )
            if cached_daily_quote is not None:
                return cached_daily_quote
        raise MarketDataUnavailable('Latest quote is temporarily unavailable.') from exc

    result = MarketDataQuoteResult(
        security=security,
        price=quote.price,
        change=quote.change,
        percent_change=quote.percent_change,
        currency=security.currency,
        source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
        as_of=quote.as_of,
        data_status=MARKET_DATA_QUOTE_STATUS_OK,
        cache_status='fresh' if client is None else 'bypass',
        is_stale=False,
    )
    if client is None:
        cache_quote_result(result)
    return result


def get_security_latest_quotes(securities, client=None, force_refresh=False):
    results = []
    for security in tuple(securities):
        try:
            result = get_security_latest_quote(
                security,
                client=client,
                force_refresh=force_refresh,
                allow_cached=True,
                allow_stale=True,
            )
        except UnsupportedMarketDataSecurity as exc:
            result = build_unavailable_quote_result(security, str(exc))
        except MarketDataInvalidSymbol as exc:
            result = build_unavailable_quote_result(security, str(exc))
        except MarketDataRateLimited as exc:
            result = build_unavailable_quote_result(security, str(exc))
        except MarketDataUnavailable as exc:
            result = build_unavailable_quote_result(security, str(exc))

        results.append(result)

    return tuple(results)


def get_security_daily_market_data(
    security,
    range_key=None,
    start_date=None,
    end_date=None,
    interval=None,
    client=None,
    force_refresh=False,
):
    normalized_range = normalize_range(range_key)
    if security.asset_type not in SUPPORTED_MARKET_DATA_ASSET_TYPES:
        raise UnsupportedMarketDataSecurity('Only stocks and ETFs are supported for daily market data.')

    market_data_client = client or TwelveDataClient()
    requested_start_date, requested_end_date = get_range_date_window(
        normalized_range,
        start_date=start_date,
        end_date=end_date,
    )
    interval = get_market_data_interval(normalized_range, requested_start_date, requested_end_date, interval=interval)
    validate_market_data_request_size(requested_start_date, requested_end_date, interval)
    warmup_start_date = get_indicator_warmup_start_date(requested_start_date, interval)
    use_daily_cache = range_uses_daily_cache(normalized_range, interval)
    cached_full_values = get_cached_daily_prices(security, warmup_start_date, requested_end_date) if use_daily_cache else []
    cached_values, cached_warmup_values = split_visible_and_warmup_values(cached_full_values, requested_start_date)

    logger.info(
        'Market data request symbol=%s range=%s interval=%s start_date=%s end_date=%s warmup_start_date=%s use_daily_cache=%s force_refresh=%s',
        security.symbol,
        normalized_range,
        interval,
        requested_start_date,
        requested_end_date,
        warmup_start_date,
        use_daily_cache,
        force_refresh,
    )

    if (
        use_daily_cache
        and not force_refresh
        and cached_values
        and cache_has_requested_coverage(security, warmup_start_date, requested_end_date)
    ):
        return build_market_data_result(
            security=security,
            range_key=normalized_range,
            interval=interval,
            values=cached_values,
            is_stale=False,
            warmup_values=cached_warmup_values,
            data_source='database_cache',
            cache_status='hit',
            provider_metadata={
                'cache': {
                    'record_count': len(cached_full_values),
                    'cached_last_timestamp': get_bar_timestamp(cached_full_values[-1]) if cached_full_values else '',
                },
            },
        )

    provider_metadata = {}
    session_close_adjustments = ()
    try:
        if use_daily_cache:
            fetch_and_cache_daily_prices(security, warmup_start_date, requested_end_date, client=market_data_client)
            provider_metadata['time_series'] = get_provider_response_summary(market_data_client)
        else:
            fetched_values = fetch_time_series_prices(
                security,
                warmup_start_date,
                requested_end_date,
                interval,
                client=market_data_client,
            )
            provider_metadata['time_series'] = build_time_series_provider_metadata(market_data_client, fetched_values)
            if is_intraday_interval(interval):
                try:
                    fetched_values, session_close_adjustments, daily_metadata = apply_official_session_closes(
                        security,
                        fetched_values,
                        warmup_start_date,
                        requested_end_date,
                        market_data_client,
                    )
                    provider_metadata['session_close_source'] = daily_metadata
                except TwelveDataError as exc:
                    provider_metadata['session_close_source'] = {
                        **get_provider_error_metadata(exc),
                        'error': str(exc),
                    }
                    logger.warning(
                        'Market data official session close alignment failed symbol=%s interval=%s is_stale=False upstream_error=%s',
                        security.symbol,
                        interval,
                        str(exc),
                    )
    except TwelveDataRateLimitError as exc:
        if cached_values:
            return build_market_data_result(
                security=security,
                range_key=normalized_range,
                interval=interval,
                values=cached_values,
                is_stale=True,
                warmup_values=cached_warmup_values,
                data_source='stale_database_cache',
                cache_status='stale_fallback',
                upstream_error=str(exc),
                provider_metadata={
                    'error': get_provider_error_metadata(exc),
                    'cached_last_timestamp': get_bar_timestamp(cached_values[-1]) if cached_values else '',
                },
            )
        raise MarketDataRateLimited('Market data provider rate limit reached. Please try again later.') from exc
    except TwelveDataInvalidSymbolError as exc:
        raise MarketDataInvalidSymbol('Market data is not available for this security.') from exc
    except TwelveDataIntervalUnavailableError as exc:
        if cached_values:
            return build_market_data_result(
                security=security,
                range_key=normalized_range,
                interval=interval,
                values=cached_values,
                is_stale=True,
                warmup_values=cached_warmup_values,
                data_source='stale_database_cache',
                cache_status='stale_fallback',
                upstream_error=str(exc),
                provider_metadata={
                    'error': get_provider_error_metadata(exc),
                    'cached_last_timestamp': get_bar_timestamp(cached_values[-1]) if cached_values else '',
                },
            )
        raise MarketDataUnavailable('Market data for this interval is not available. Please choose another range.') from exc
    except TwelveDataError as exc:
        if cached_values:
            return build_market_data_result(
                security=security,
                range_key=normalized_range,
                interval=interval,
                values=cached_values,
                is_stale=True,
                warmup_values=cached_warmup_values,
                data_source='stale_database_cache',
                cache_status='stale_fallback',
                upstream_error=str(exc),
                provider_metadata={
                    'error': get_provider_error_metadata(exc),
                    'cached_last_timestamp': get_bar_timestamp(cached_values[-1]) if cached_values else '',
                },
            )
        raise MarketDataUnavailable('Market data is temporarily unavailable.') from exc

    if not use_daily_cache:
        fetched_values = order_market_data_values(fetched_values)
        visible_values, warmup_values = split_visible_and_warmup_values(fetched_values, requested_start_date)
        if normalized_range == '1D' and interval not in {'1day', '1week'}:
            visible_values, warmup_values = keep_latest_intraday_session_values(visible_values, warmup_values)
        if not visible_values:
            raise MarketDataUnavailable('Market data is temporarily unavailable.')
        return build_market_data_result(
            security=security,
            range_key=normalized_range,
            interval=interval,
            values=visible_values,
            is_stale=False,
            warmup_values=warmup_values,
            data_source='twelve_data',
            cache_status='bypass' if force_refresh else 'not_used',
            provider_metadata=provider_metadata,
            session_close_adjustments=session_close_adjustments,
        )

    refreshed_full_values = get_cached_daily_prices(security, warmup_start_date, requested_end_date)
    refreshed_values, refreshed_warmup_values = split_visible_and_warmup_values(refreshed_full_values, requested_start_date)
    if not refreshed_values:
        raise MarketDataUnavailable('Market data is temporarily unavailable.')

    return build_market_data_result(
        security=security,
        range_key=normalized_range,
        interval=interval,
        values=refreshed_values,
        is_stale=False,
        warmup_values=refreshed_warmup_values,
        data_source='twelve_data',
        cache_status='refreshed' if force_refresh else 'miss',
        provider_metadata=provider_metadata,
    )
