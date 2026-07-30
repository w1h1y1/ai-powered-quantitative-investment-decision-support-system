import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings


class TwelveDataError(Exception):
    pass


class TwelveDataConfigurationError(TwelveDataError):
    pass


@dataclass(frozen=True)
class TwelveDataDailyBar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


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


def parse_bar(raw_bar):
    try:
        bar_date = date.fromisoformat(str(raw_bar['datetime'])[:10])
    except (KeyError, TypeError, ValueError) as exc:
        raise TwelveDataError('Invalid datetime value from market data provider.') from exc

    return TwelveDataDailyBar(
        date=bar_date,
        open=parse_decimal(raw_bar.get('open'), 'open'),
        high=parse_decimal(raw_bar.get('high'), 'high'),
        low=parse_decimal(raw_bar.get('low'), 'low'),
        close=parse_decimal(raw_bar.get('close'), 'close'),
        volume=parse_volume(raw_bar.get('volume')),
    )


class TwelveDataClient:
    def __init__(self, api_key=None, base_url=None, timeout=None):
        self.api_key = api_key if api_key is not None else settings.TWELVE_DATA_API_KEY
        self.base_url = (base_url or settings.TWELVE_DATA_BASE_URL).rstrip('/')
        self.timeout = timeout or settings.TWELVE_DATA_TIMEOUT_SECONDS

    def get_daily_time_series(self, symbol, start_date=None, end_date=None, outputsize=None):
        if not self.api_key:
            raise TwelveDataConfigurationError('Twelve Data API key is not configured.')

        params = {
            'symbol': symbol,
            'interval': '1day',
            'order': 'asc',
            'format': 'JSON',
            'apikey': self.api_key,
        }
        if start_date is not None:
            params['start_date'] = start_date.isoformat()
        if end_date is not None:
            params['end_date'] = end_date.isoformat()
        if outputsize is not None:
            params['outputsize'] = outputsize

        query = urlencode(params)
        url = f'{self.base_url}/time_series?{query}'

        try:
            with urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            raise TwelveDataError('Market data provider returned an HTTP error.') from exc
        except URLError as exc:
            raise TwelveDataError('Market data provider is unavailable.') from exc
        except json.JSONDecodeError as exc:
            raise TwelveDataError('Market data provider returned invalid JSON.') from exc

        if payload.get('status') == 'error':
            message = payload.get('message') or 'Market data provider returned an error.'
            raise TwelveDataError(str(message))

        values = payload.get('values')
        if not isinstance(values, list):
            raise TwelveDataError('Market data provider response did not include time series values.')

        return [parse_bar(item) for item in values]
