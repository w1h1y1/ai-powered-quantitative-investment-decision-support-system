import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings


logger = logging.getLogger(__name__)
INTRADAY_INTERVALS = {'1min', '5min', '15min', '30min', '1h', '2h', '4h'}


class TwelveDataError(Exception):
    def __init__(
        self,
        message='Market data provider returned an error.',
        *,
        endpoint='',
        params=None,
        http_status=None,
        provider_status='',
        provider_code=None,
        provider_message='',
    ):
        super().__init__(message)
        self.endpoint = endpoint
        self.params = params or {}
        self.http_status = http_status
        self.provider_status = provider_status
        self.provider_code = provider_code
        self.provider_message = provider_message or message


class TwelveDataConfigurationError(TwelveDataError):
    pass


class TwelveDataInvalidSymbolError(TwelveDataError):
    pass


class TwelveDataRateLimitError(TwelveDataError):
    pass


class TwelveDataIntervalUnavailableError(TwelveDataError):
    pass


class TwelveDataUnavailableError(TwelveDataError):
    pass


@dataclass(frozen=True)
class TwelveDataDailyBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timestamp: str = ''


@dataclass(frozen=True)
class TwelveDataQuote:
    price: Decimal
    change: Decimal
    percent_change: Decimal
    as_of: str


def parse_decimal(value, field_name):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TwelveDataError(f'Invalid {field_name} value from market data provider.') from exc


def parse_volume(value):
    if value in (None, ''):
        return 0
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TwelveDataError('Invalid volume value from market data provider.') from exc


def parse_optional_decimal(value, field_name, default=Decimal('0')):
    if value in (None, ''):
        return default
    return parse_decimal(value, field_name)


def parse_bar(raw_bar):
    raw_datetime = str(raw_bar.get('datetime') or '')
    try:
        bar_date = date.fromisoformat(raw_datetime[:10])
    except (KeyError, TypeError, ValueError) as exc:
        raise TwelveDataError('Invalid datetime value from market data provider.') from exc

    return TwelveDataDailyBar(
        date=bar_date,
        open=parse_decimal(raw_bar.get('open'), 'open'),
        high=parse_decimal(raw_bar.get('high'), 'high'),
        low=parse_decimal(raw_bar.get('low'), 'low'),
        close=parse_decimal(raw_bar.get('close'), 'close'),
        volume=parse_volume(raw_bar.get('volume')),
        timestamp=raw_datetime,
    )


def parse_quote(raw_quote):
    price_value = raw_quote.get('price')
    if price_value in (None, ''):
        price_value = raw_quote.get('close')

    return TwelveDataQuote(
        price=parse_decimal(price_value, 'price'),
        change=parse_optional_decimal(raw_quote.get('change'), 'change'),
        percent_change=parse_optional_decimal(raw_quote.get('percent_change'), 'percent_change'),
        as_of=str(raw_quote.get('datetime') or raw_quote.get('timestamp') or ''),
    )


def get_provider_error(message, details=None):
    normalized_message = str(message or '').lower()
    details = details or {}
    if any(token in normalized_message for token in ['limit', 'quota', 'credits', 'rate']):
        return TwelveDataRateLimitError('Market data provider rate limit reached.', **details)
    if any(token in normalized_message for token in ['invalid symbol', 'symbol not found', 'not found']):
        return TwelveDataInvalidSymbolError('Market data is not available for this security.', **details)
    if 'interval' in normalized_message and any(token in normalized_message for token in ['not available', 'not supported', 'subscription', 'plan']):
        return TwelveDataIntervalUnavailableError('Market data for this interval is not available.', **details)
    if any(token in normalized_message for token in ['subscription', 'plan', 'permission', 'access', 'upgrade', 'pricing']):
        return TwelveDataUnavailableError('Market data requires additional Twelve Data access.', **details)
    return TwelveDataUnavailableError('Market data provider returned an error.', **details)


class TwelveDataClient:
    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key = api_key if api_key is not None else settings.TWELVE_DATA_API_KEY
        self.base_url = (base_url or settings.TWELVE_DATA_BASE_URL).rstrip('/')
        self.timeout = timeout or settings.TWELVE_DATA_TIMEOUT_SECONDS
        self.last_response_metadata = {}

    def _set_last_response_metadata(self, endpoint, params, http_status=None, payload=None):
        payload = payload if isinstance(payload, dict) else {}
        self.last_response_metadata = {
            'endpoint': endpoint,
            'params': dict(params),
            'http_status': http_status,
            'provider_status': payload.get('status') or '',
            'provider_code': payload.get('code'),
            'provider_message': payload.get('message') or '',
        }
        return self.last_response_metadata

    def _parse_error_payload(self, exc):
        try:
            return json.loads(exc.read().decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _request(self, endpoint, params):
        if not self.api_key:
            raise TwelveDataConfigurationError('Twelve Data API key is not configured.')

        logger.info('Twelve Data request endpoint=%s params=%s', endpoint, params)
        query = urlencode({
            **params,
            'format': 'JSON',
            'apikey': self.api_key,
        })
        url = f'{self.base_url}/{endpoint}?{query}'

        try:
            with urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
                response_metadata = self._set_last_response_metadata(endpoint, params, response.status, payload)
        except HTTPError as exc:
            payload = self._parse_error_payload(exc)
            response_metadata = self._set_last_response_metadata(endpoint, params, exc.code, payload)
            logger.warning(
                'Twelve Data HTTP error endpoint=%s params=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s',
                endpoint,
                params,
                response_metadata['http_status'],
                response_metadata['provider_status'],
                response_metadata['provider_code'],
                response_metadata['provider_message'],
            )
            if exc.code == 429:
                raise TwelveDataRateLimitError('Market data provider rate limit reached.', **response_metadata) from exc
            raise get_provider_error(
                response_metadata['provider_message'] or 'Market data provider returned an HTTP error.',
                response_metadata,
            ) from exc
        except URLError as exc:
            raise TwelveDataUnavailableError('Market data provider is unavailable.', endpoint=endpoint, params=params) from exc
        except json.JSONDecodeError as exc:
            raise TwelveDataUnavailableError('Market data provider returned invalid JSON.', endpoint=endpoint, params=params) from exc

        if payload.get('status') == 'error':
            logger.warning(
                'Twelve Data error endpoint=%s params=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s',
                endpoint,
                params,
                response_metadata['http_status'],
                response_metadata['provider_status'],
                response_metadata['provider_code'],
                response_metadata['provider_message'],
            )
            raise get_provider_error(payload.get('message'), response_metadata)

        logger.info(
            'Twelve Data response endpoint=%s params=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s',
            endpoint,
            params,
            response_metadata['http_status'],
            response_metadata['provider_status'],
            response_metadata['provider_code'],
            response_metadata['provider_message'],
        )

        return payload

    def _format_time_series_boundary(self, value, interval, is_end=False):
        if value is None:
            return None

        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')

        if isinstance(value, date):
            if interval in INTRADAY_INTERVALS:
                boundary_time = time(23, 59, 59) if is_end else time(0, 0, 0)
                return datetime.combine(value, boundary_time).strftime('%Y-%m-%d %H:%M:%S')
            return value.isoformat()

        return str(value)

    def get_time_series(self, symbol, interval, start_date=None, end_date=None, outputsize=None):
        params = {
            'symbol': symbol,
            'interval': interval,
            'order': 'asc',
            'timezone': settings.TWELVE_DATA_TIMEZONE,
        }
        if start_date is not None:
            params['start_date'] = self._format_time_series_boundary(start_date, interval, is_end=False)
        if end_date is not None:
            params['end_date'] = self._format_time_series_boundary(end_date, interval, is_end=True)
        if outputsize is not None:
            params['outputsize'] = outputsize

        logger.info(
            'Twelve Data time_series request endpoint=time_series symbol=%s interval=%s start_date=%s end_date=%s outputsize=%s timezone=%s order=%s',
            symbol,
            interval,
            params.get('start_date'),
            params.get('end_date'),
            outputsize,
            params.get('timezone'),
            params.get('order'),
        )
        payload = self._request('time_series', params)
        values = payload.get('values')
        if not isinstance(values, list):
            raise TwelveDataError('Market data provider response did not include time series values.')

        bars = [parse_bar(item) for item in values]
        response_metadata = self.last_response_metadata or {}
        logger.info(
            'Twelve Data time_series response endpoint=time_series symbol=%s interval=%s http_status=%s provider_status=%s provider_code=%s provider_message=%s count=%s first=%s last=%s',
            symbol,
            interval,
            response_metadata.get('http_status'),
            response_metadata.get('provider_status'),
            response_metadata.get('provider_code'),
            response_metadata.get('provider_message'),
            len(bars),
            bars[0].timestamp if bars else '',
            bars[-1].timestamp if bars else '',
        )
        return bars

    def get_daily_time_series(self, symbol, start_date=None, end_date=None, outputsize=None):
        return self.get_time_series(
            symbol=symbol,
            interval='1day',
            start_date=start_date,
            end_date=end_date,
            outputsize=outputsize,
        )

    def symbol_search(self, symbol):
        payload = self._request('symbol_search', {'symbol': symbol})
        data = payload.get('data')
        if not isinstance(data, list):
            raise TwelveDataError('Market data provider response did not include symbol search data.')
        logger.info('Twelve Data symbol_search response symbol=%s count=%s', symbol, len(data))
        return data

    def get_quote(self, symbol):
        payload = self._request('quote', {'symbol': symbol})
        return parse_quote(payload)
