from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from math import ceil, sqrt
from statistics import pstdev

from backtest.services import (
    calculate_atr,
    calculate_macd,
    calculate_rsi,
    calculate_simple_moving_average,
)
from market.models import SecurityDailyPrice
from market.services import (
    cache_has_requested_coverage,
    fetch_and_cache_daily_prices,
    get_cached_daily_prices,
    get_latest_complete_market_date,
)
from market.twelve_data import (
    TwelveDataError,
    TwelveDataInvalidSymbolError,
    TwelveDataRateLimitError,
)

from .artifact_cache import (
    get_or_create_prediction_artifact,
    prediction_cache_metadata,
)
from .feature_service import build_prediction_feature_datasets
from .ml_service import (
    PREDICTION_PIPELINE_VERSION,
    generate_machine_learning_prediction,
)


ZERO = Decimal('0')
TRADING_DAYS_PER_YEAR = 252
PREDICTION_CALENDAR_BUFFER_DAYS = 14


class PredictionDataError(Exception):
    pass


class PredictionMarketDataRateLimited(PredictionDataError):
    pass


class PredictionMarketDataUnavailable(PredictionDataError):
    pass


@dataclass(frozen=True)
class PredictionBar:
    date: object
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def _prediction_start_date(end_date, lookback):
    calendar_days = ceil((lookback + 1) * 365 / TRADING_DAYS_PER_YEAR) + PREDICTION_CALENDAR_BUFFER_DAYS
    return end_date - timedelta(days=calendar_days)


def _prices_to_bars(prices):
    return tuple(
        PredictionBar(
            date=price.date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.close,
            volume=max(int(price.volume or 0), 0),
        )
        for price in prices
        if (
            price.open is not None and price.high is not None and price.low is not None and price.close is not None
            and price.open > ZERO and price.high > ZERO and price.low > ZERO and price.close > ZERO
        )
    )


def _load_prediction_bars(security, lookback):
    end_date = get_latest_complete_market_date()
    start_date = _prediction_start_date(end_date, lookback)
    cached_before_fetch = get_cached_daily_prices(security, start_date, end_date)
    fetched_from_provider = False

    if not cache_has_requested_coverage(security, start_date, end_date):
        try:
            fetch_and_cache_daily_prices(security, start_date, end_date, require_exact_window=True)
            fetched_from_provider = True
        except TwelveDataRateLimitError as exc:
            if not cached_before_fetch:
                raise PredictionMarketDataRateLimited(
                    'Market data provider rate limit reached. Please try again later.'
                ) from exc
        except TwelveDataInvalidSymbolError as exc:
            raise PredictionMarketDataUnavailable('Market data is not available for this security.') from exc
        except TwelveDataError as exc:
            if not cached_before_fetch:
                raise PredictionMarketDataUnavailable('Market data is temporarily unavailable.') from exc

    prices = get_cached_daily_prices(security, start_date, end_date)
    bars = _prices_to_bars(prices)
    if len(bars) < lookback:
        raise PredictionMarketDataUnavailable(
            f'Only {len(bars)} valid daily bars are available; {lookback} are required for this lookback.'
        )

    return bars[-lookback:], {
        'source': 'twelve_data' if fetched_from_provider else 'database_cache',
        'price_model': SecurityDailyPrice.SOURCE_TWELVE_DATA,
        'requested_start_date': start_date.isoformat(),
        'requested_end_date': end_date.isoformat(),
        'fetched_from_provider': fetched_from_provider,
    }


def _float(value):
    return None if value is None else float(value)


def _recent_return(bars, period=20):
    if len(bars) <= period or bars[-period - 1].close == ZERO:
        return None
    return ((bars[-1].close / bars[-period - 1].close) - Decimal('1')) * Decimal('100')


def _annualized_volatility(bars):
    returns = [
        float((bar.close / previous.close - Decimal('1')))
        for previous, bar in zip(bars, bars[1:])
        if previous.close > ZERO
    ]
    if len(returns) < 2:
        return None
    return pstdev(returns) * sqrt(TRADING_DAYS_PER_YEAR) * 100


def _volume_trend(bars, period=20):
    recent = bars[-period:]
    previous = bars[-period * 2:-period]
    recent_average = sum((bar.volume for bar in recent), 0) / len(recent) if recent else None
    previous_average = sum((bar.volume for bar in previous), 0) / len(previous) if previous else None
    if len(bars) < period * 2 or not recent_average or not previous_average:
        return {
            'direction': 'unavailable',
            'recent_average': recent_average,
            'previous_average': previous_average if len(bars) >= period * 2 else None,
            'percent_change': None,
        }
    change = ((recent_average / previous_average) - 1) * 100
    return {
        'direction': 'up' if change > 2 else 'down' if change < -2 else 'flat',
        'recent_average': recent_average,
        'previous_average': previous_average,
        'percent_change': change,
    }


def _serialize_bars(bars):
    return [
        {
            'date': bar.date.isoformat(),
            'open': _float(bar.open),
            'high': _float(bar.high),
            'low': _float(bar.low),
            'close': _float(bar.close),
            'volume': bar.volume,
        }
        for bar in bars
    ]


def generate_prediction_market_data(
    security,
    classification_forecast_horizon,
    regression_forecast_horizon,
    lookback,
):
    bars, data_source = _load_prediction_bars(security, lookback)

    def build_ml_artifact():
        feature_datasets = build_prediction_feature_datasets(
            bars,
            classification_forecast_horizon,
            regression_forecast_horizon,
        )
        return generate_machine_learning_prediction(
            feature_datasets['classification'],
            feature_datasets['regression'],
            current_price=float(bars[-1].close),
        )

    cached_ml_result, cache_hit = get_or_create_prediction_artifact(
        symbol=security.symbol,
        classification_forecast_horizon=classification_forecast_horizon,
        regression_forecast_horizon=regression_forecast_horizon,
        lookback=lookback,
        latest_market_date=bars[-1].date,
        pipeline_version=PREDICTION_PIPELINE_VERSION,
        artifact_factory=build_ml_artifact,
    )
    cache_metadata = prediction_cache_metadata(
        hit=cache_hit,
        latest_market_date=bars[-1].date,
        pipeline_version=PREDICTION_PIPELINE_VERSION,
        classification_forecast_horizon=classification_forecast_horizon,
        regression_forecast_horizon=regression_forecast_horizon,
    )
    ml_result = {
        **cached_ml_result,
        'ml_cache': cache_metadata,
        'ml_metadata': {
            **cached_ml_result.get('ml_metadata', {}),
            'ml_cache': cache_metadata,
        },
    }

    ma5 = calculate_simple_moving_average(bars, 5)[-1]
    ma10 = calculate_simple_moving_average(bars, 10)[-1]
    ma20 = calculate_simple_moving_average(bars, 20)[-1]
    ma60 = calculate_simple_moving_average(bars, 60)[-1]
    rsi = calculate_rsi(bars, 14)[-1]
    atr = calculate_atr(bars, 14)[-1]
    macd, macd_signal, _histogram = calculate_macd(bars)
    volume_trend = _volume_trend(bars)
    quality_gate = ml_result.get('prediction_quality_gate')
    quality_gate_failed = bool(
        quality_gate
        and not quality_gate.get('classification', {}).get('passed', False)
    )
    if ml_result['prediction_available']:
        prediction_status = 'available'
        prediction_message = (
            'Machine-learning direction was generated from the selected real historical market data. '
            + (
                'The regression return and price estimate also passed its Walk-Forward and independent Test gates.'
                if ml_result.get('regression_prediction_available')
                else ml_result.get('regression_prediction_unavailable_reason', '')
            )
        ).strip()
    elif quality_gate_failed:
        prediction_status = 'quality_gate_failed'
        prediction_message = ml_result['prediction_unavailable_reason']
    else:
        prediction_status = 'insufficient_data'
        prediction_message = ml_result['prediction_unavailable_reason']

    payload = {
        'symbol': security.symbol,
        'security': {
            'id': security.id,
            'symbol': security.symbol,
            'name': security.name,
            'asset_type': security.asset_type,
            'exchange': security.exchange,
            'currency': security.currency,
        },
        'current_price': _float(bars[-1].close),
        'latest_market_date': bars[-1].date.isoformat(),
        'historical_data_count': len(bars),
        # Deprecated response alias retained for consumers that still display a
        # single direction horizon. New Prediction Lab code uses both fields.
        'horizon': classification_forecast_horizon,
        'classification_forecast_horizon': classification_forecast_horizon,
        'regression_forecast_horizon': regression_forecast_horizon,
        'classification_purge_gap': classification_forecast_horizon,
        'regression_purge_gap': regression_forecast_horizon,
        'lookback': lookback,
        'historical_data': _serialize_bars(bars),
        'technical_indicators': {
            'ma5': _float(ma5),
            'ma10': _float(ma10),
            'ma20': _float(ma20),
            'ma60': _float(ma60),
            'rsi': _float(rsi),
            'macd': _float(macd[-1]),
            'macd_signal': _float(macd_signal[-1]),
            'atr': _float(atr),
            'recent_return': _float(_recent_return(bars)),
            'volatility': _annualized_volatility(bars),
            'volume_trend': {
                'direction': volume_trend['direction'],
                'recent_average': volume_trend['recent_average'],
                'previous_average': volume_trend['previous_average'],
                'percent_change': volume_trend['percent_change'],
            },
        },
        'market_data': data_source,
        'prediction': {
            'status': prediction_status,
            'message': prediction_message,
        },
    }
    payload.update(ml_result)
    return payload
