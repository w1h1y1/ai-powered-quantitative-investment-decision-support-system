from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import pstdev

from backtest.services import (
    calculate_atr,
    calculate_macd,
    calculate_rsi,
    calculate_simple_moving_average,
)


TRADING_DAYS_PER_YEAR = 252
VOLATILITY_PERIOD = 20

FEATURE_NAMES = (
    'daily_return',
    'ma5',
    'ma10',
    'ma20',
    'ma60',
    'price_ma5_ratio',
    'price_ma10_ratio',
    'price_ma20_ratio',
    'price_ma60_ratio',
    'rsi',
    'macd',
    'macd_signal',
    'macd_histogram',
    'atr',
    'atr_price_ratio',
    'volume',
    'volume_change',
    'volatility_20',
)

# Regression uses a separate, scale-stable feature view so classification keeps
# the already-validated feature matrix and results unchanged. Every value below
# is available at time t and is derived only from bars at or before t.
REGRESSION_FEATURE_NAMES = (
    'return_1',
    'return_3',
    'return_5',
    'return_10',
    'return_20',
    'volatility_5',
    'volatility_10',
    'volatility_20',
    'price_ma5_ratio',
    'price_ma10_ratio',
    'price_ma20_ratio',
    'price_ma60_ratio',
    'ma5_slope_5',
    'ma10_slope_5',
    'ma20_slope_5',
    'rsi',
    'macd_price_ratio',
    'macd_signal_price_ratio',
    'macd_histogram_price_ratio',
    'atr_price_ratio',
    'volume_change_1',
    'volume_average_20_ratio',
    'distance_to_20_day_high',
    'distance_from_20_day_low',
)


@dataclass(frozen=True)
class PredictionFeatureDataset:
    horizon: int
    feature_names: tuple
    features: tuple
    classification_labels: tuple
    regression_labels: tuple
    regression_feature_names: tuple
    regression_features: tuple
    sample_indices: tuple
    latest_features: tuple | None
    latest_regression_features: tuple | None
    discarded_labeled_rows: int

    @property
    def sample_count(self):
        return len(self.features)


def _float(value):
    return None if value is None else float(value)


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float((numerator / denominator) - 1)


def _plain_ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator / denominator)


def _is_complete(values):
    return all(value is not None and isfinite(value) for value in values)


def _daily_returns(bars):
    values = [None]
    values.extend(
        float((bar.close / previous.close) - 1) if previous.close else None
        for previous, bar in zip(bars, bars[1:])
    )
    return tuple(values)


def _rolling_volatility(returns, period=VOLATILITY_PERIOD):
    values = []
    for index in range(len(returns)):
        window = returns[index - period + 1:index + 1]
        if len(window) < period or not _is_complete(window):
            values.append(None)
        else:
            values.append(pstdev(window) * sqrt(TRADING_DAYS_PER_YEAR))
    return tuple(values)


def _period_return(bars, index, period):
    if index < period or not bars[index - period].close:
        return None
    return float((bars[index].close / bars[index - period].close) - 1)


def _moving_average(values, index, period):
    if index < period - 1:
        return None
    window = values[index - period + 1:index + 1]
    if not _is_complete(window):
        return None
    return float(sum(window) / period)


def _moving_extreme(values, index, period, operation):
    if index < period - 1:
        return None
    window = values[index - period + 1:index + 1]
    if not _is_complete(window):
        return None
    return float(operation(window))


def _slope_ratio(values, index, period):
    if index < period:
        return None
    return _ratio(values[index], values[index - period])


def build_prediction_feature_dataset(bars, horizon):
    """Build point-in-time features and shift(-horizon) labels from ascending bars."""
    if any(current.date >= following.date for current, following in zip(bars, bars[1:])):
        raise ValueError('Prediction bars must be strictly ordered by ascending market date.')
    ma5 = calculate_simple_moving_average(bars, 5)
    ma10 = calculate_simple_moving_average(bars, 10)
    ma20 = calculate_simple_moving_average(bars, 20)
    ma60 = calculate_simple_moving_average(bars, 60)
    rsi = calculate_rsi(bars, 14)
    atr = calculate_atr(bars, 14)
    macd, macd_signal, macd_histogram = calculate_macd(bars)
    daily_returns = _daily_returns(bars)
    volatility_5 = _rolling_volatility(daily_returns, 5)
    volatility_10 = _rolling_volatility(daily_returns, 10)
    volatility = _rolling_volatility(daily_returns)
    close_values = tuple(float(bar.close) for bar in bars)
    volume_values = tuple(float(bar.volume) for bar in bars)

    feature_rows = []
    regression_feature_rows = []
    for index, bar in enumerate(bars):
        previous_volume = bars[index - 1].volume if index else None
        volume_change = (
            (bar.volume / previous_volume) - 1
            if previous_volume is not None and previous_volume > 0
            else None
        )
        feature_rows.append((
            daily_returns[index],
            _float(ma5[index]),
            _float(ma10[index]),
            _float(ma20[index]),
            _float(ma60[index]),
            _ratio(bar.close, ma5[index]),
            _ratio(bar.close, ma10[index]),
            _ratio(bar.close, ma20[index]),
            _ratio(bar.close, ma60[index]),
            _float(rsi[index]),
            _float(macd[index]),
            _float(macd_signal[index]),
            _float(macd_histogram[index]),
            _float(atr[index]),
            _plain_ratio(atr[index], bar.close),
            float(bar.volume),
            float(volume_change) if volume_change is not None else None,
            volatility[index],
        ))
        average_volume_20 = _moving_average(volume_values, index, 20)
        high_20 = _moving_extreme(close_values, index, 20, max)
        low_20 = _moving_extreme(close_values, index, 20, min)
        regression_feature_rows.append((
            daily_returns[index],
            _period_return(bars, index, 3),
            _period_return(bars, index, 5),
            _period_return(bars, index, 10),
            _period_return(bars, index, 20),
            volatility_5[index],
            volatility_10[index],
            volatility[index],
            _ratio(bar.close, ma5[index]),
            _ratio(bar.close, ma10[index]),
            _ratio(bar.close, ma20[index]),
            _ratio(bar.close, ma60[index]),
            _slope_ratio(ma5, index, 5),
            _slope_ratio(ma10, index, 5),
            _slope_ratio(ma20, index, 5),
            _float(rsi[index]),
            _plain_ratio(macd[index], bar.close),
            _plain_ratio(macd_signal[index], bar.close),
            _plain_ratio(macd_histogram[index], bar.close),
            _plain_ratio(atr[index], bar.close),
            float(volume_change) if volume_change is not None else None,
            _ratio(bar.volume, average_volume_20),
            _ratio(float(bar.close), high_20),
            _ratio(float(bar.close), low_20),
        ))

    features = []
    regression_features = []
    classification_labels = []
    regression_labels = []
    sample_indices = []
    discarded_labeled_rows = 0
    labeled_row_count = max(len(bars) - horizon, 0)

    for index in range(labeled_row_count):
        row = feature_rows[index]
        if not _is_complete(row):
            discarded_labeled_rows += 1
            continue
        regression_row = regression_feature_rows[index]
        if not _is_complete(regression_row):
            raise RuntimeError(
                'Regression feature warm-up exceeded the validated classification warm-up.'
            )
        future_return = float((bars[index + horizon].close / bars[index].close) - 1)
        if not isfinite(future_return):
            discarded_labeled_rows += 1
            continue
        features.append(tuple(row))
        regression_features.append(tuple(regression_row))
        classification_labels.append(1 if future_return > 0 else 0)
        regression_labels.append(future_return)
        sample_indices.append(index)

    latest_row = tuple(feature_rows[-1]) if feature_rows else None
    latest_features = latest_row if latest_row is not None and _is_complete(latest_row) else None
    latest_regression_row = (
        tuple(regression_feature_rows[-1])
        if regression_feature_rows
        else None
    )
    latest_regression_features = (
        latest_regression_row
        if latest_regression_row is not None and _is_complete(latest_regression_row)
        else None
    )
    return PredictionFeatureDataset(
        horizon=horizon,
        feature_names=FEATURE_NAMES,
        features=tuple(features),
        classification_labels=tuple(classification_labels),
        regression_labels=tuple(regression_labels),
        regression_feature_names=REGRESSION_FEATURE_NAMES,
        regression_features=tuple(regression_features),
        sample_indices=tuple(sample_indices),
        latest_features=latest_features,
        latest_regression_features=latest_regression_features,
        discarded_labeled_rows=discarded_labeled_rows,
    )


def build_prediction_feature_datasets(
    bars,
    classification_forecast_horizon,
    regression_forecast_horizon,
):
    """Build independent point-in-time datasets for direction and return targets."""
    return {
        'classification': build_prediction_feature_dataset(
            bars,
            classification_forecast_horizon,
        ),
        'regression': build_prediction_feature_dataset(
            bars,
            regression_forecast_horizon,
        ),
    }
