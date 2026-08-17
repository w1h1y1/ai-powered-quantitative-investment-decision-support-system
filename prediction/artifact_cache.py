from threading import Lock

from django.conf import settings
from django.core.cache import cache


PREDICTION_ARTIFACT_CACHE_PREFIX = 'prediction'
DEFAULT_PREDICTION_ARTIFACT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

_artifact_locks = {}
_artifact_locks_guard = Lock()


def build_prediction_artifact_cache_key(
    symbol,
    classification_forecast_horizon,
    regression_forecast_horizon,
    lookback,
    latest_market_date,
    pipeline_version,
):
    normalized_symbol = str(symbol).strip().upper()
    normalized_date = latest_market_date.isoformat()
    return (
        f'{PREDICTION_ARTIFACT_CACHE_PREFIX}:{normalized_symbol}:'
        f'classification-{int(classification_forecast_horizon)}:'
        f'regression-{int(regression_forecast_horizon)}:'
        f'{int(lookback)}:{normalized_date}:{pipeline_version}'
    )


def _artifact_lock(cache_key):
    with _artifact_locks_guard:
        if cache_key not in _artifact_locks:
            _artifact_locks[cache_key] = Lock()
        return _artifact_locks[cache_key]


def get_or_create_prediction_artifact(
    *,
    symbol,
    classification_forecast_horizon,
    regression_forecast_horizon,
    lookback,
    latest_market_date,
    pipeline_version,
    artifact_factory,
):
    cache_key = build_prediction_artifact_cache_key(
        symbol,
        classification_forecast_horizon,
        regression_forecast_horizon,
        lookback,
        latest_market_date,
        pipeline_version,
    )
    cached_artifact = cache.get(cache_key)
    if cached_artifact is not None:
        return cached_artifact, True

    lock = _artifact_lock(cache_key)
    with lock:
        cached_artifact = cache.get(cache_key)
        if cached_artifact is not None:
            return cached_artifact, True

        artifact = artifact_factory()
        cache_ttl = getattr(
            settings,
            'PREDICTION_ARTIFACT_CACHE_TTL_SECONDS',
            DEFAULT_PREDICTION_ARTIFACT_CACHE_TTL_SECONDS,
        )
        cache.set(cache_key, artifact, cache_ttl)
        return artifact, False


def prediction_cache_metadata(
    *,
    hit,
    latest_market_date,
    pipeline_version,
    classification_forecast_horizon=None,
    regression_forecast_horizon=None,
):
    metadata = {
        'hit': bool(hit),
        'key_date': latest_market_date.isoformat(),
        'pipeline_version': pipeline_version,
    }
    if classification_forecast_horizon is not None:
        metadata['classification_forecast_horizon'] = int(
            classification_forecast_horizon
        )
    if regression_forecast_horizon is not None:
        metadata['regression_forecast_horizon'] = int(
            regression_forecast_horizon
        )
    return metadata
