"""Additional trailing-only indicators used by the deterministic regime engine."""

from math import log10, sqrt
from statistics import pstdev

from .regime_config import TRADING_DAYS_PER_YEAR


def calculate_adx(bars, period=14):
    """Return classic Wilder ADX values without using future observations."""
    values = [None] * len(bars)
    if len(bars) < (period * 2):
        return tuple(values)

    true_ranges = [None]
    positive_dm = [None]
    negative_dm = [None]
    for index in range(1, len(bars)):
        current = bars[index]
        previous = bars[index - 1]
        true_ranges.append(float(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )))
        upward_move = float(current.high - previous.high)
        downward_move = float(previous.low - current.low)
        positive_dm.append(upward_move if upward_move > downward_move and upward_move > 0 else 0.0)
        negative_dm.append(downward_move if downward_move > upward_move and downward_move > 0 else 0.0)

    dx_values = [None] * len(bars)
    smoothed_tr = sum(true_ranges[1:period + 1])
    smoothed_positive_dm = sum(positive_dm[1:period + 1])
    smoothed_negative_dm = sum(negative_dm[1:period + 1])

    for index in range(period, len(bars)):
        if index > period:
            smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[index]
            smoothed_positive_dm = (
                smoothed_positive_dm - (smoothed_positive_dm / period) + positive_dm[index]
            )
            smoothed_negative_dm = (
                smoothed_negative_dm - (smoothed_negative_dm / period) + negative_dm[index]
            )
        if smoothed_tr <= 0:
            continue
        positive_di = 100.0 * smoothed_positive_dm / smoothed_tr
        negative_di = 100.0 * smoothed_negative_dm / smoothed_tr
        denominator = positive_di + negative_di
        dx_values[index] = 0.0 if denominator <= 0 else 100.0 * abs(positive_di - negative_di) / denominator

    first_adx_index = (period * 2) - 1
    seed = [value for value in dx_values[period:first_adx_index + 1] if value is not None]
    if len(seed) != period:
        return tuple(values)
    current_adx = sum(seed) / period
    values[first_adx_index] = current_adx
    for index in range(first_adx_index + 1, len(bars)):
        if dx_values[index] is None:
            continue
        current_adx = ((current_adx * (period - 1)) + dx_values[index]) / period
        values[index] = current_adx
    return tuple(values)


def calculate_choppiness_index(bars, period=14):
    """Return trailing Choppiness Index values in the [0, 100] range."""
    values = [None] * len(bars)
    if len(bars) < period + 1:
        return tuple(values)

    true_ranges = []
    for index, current in enumerate(bars):
        if index == 0:
            true_range = current.high - current.low
        else:
            previous_close = bars[index - 1].close
            true_range = max(
                current.high - current.low,
                abs(current.high - previous_close),
                abs(current.low - previous_close),
            )
        true_ranges.append(float(true_range))

    denominator_scale = log10(period)
    for index in range(period - 1, len(bars)):
        window = bars[index - period + 1:index + 1]
        price_range = float(max(bar.high for bar in window) - min(bar.low for bar in window))
        true_range_sum = sum(true_ranges[index - period + 1:index + 1])
        if price_range <= 0 or true_range_sum <= 0:
            continue
        raw_value = 100.0 * log10(true_range_sum / price_range) / denominator_scale
        values[index] = min(max(raw_value, 0.0), 100.0)
    return tuple(values)


def calculate_realized_volatility(bars, period=20):
    """Annualized population standard deviation of trailing daily returns."""
    values = [None] * len(bars)
    returns = [None]
    for previous, current in zip(bars, bars[1:]):
        returns.append(float((current.close / previous.close) - 1) if previous.close else None)

    for index in range(period, len(bars)):
        window = returns[index - period + 1:index + 1]
        if len(window) != period or any(value is None for value in window):
            continue
        values[index] = pstdev(window) * sqrt(TRADING_DAYS_PER_YEAR)
    return tuple(values)


def volatility_percentile(volatility_values, window=252):
    valid_values = [value for value in volatility_values if value is not None]
    if len(valid_values) < window:
        return None
    sample = valid_values[-window:]
    current = sample[-1]
    below = sum(value < current for value in sample)
    equal = sum(value == current for value in sample)
    return (below + (0.5 * equal)) / len(sample)


def period_return_as_of(bars, period, as_of_date=None):
    if not bars:
        return None
    if as_of_date is None:
        index = len(bars) - 1
    else:
        index = next((position for position, bar in enumerate(bars) if bar.date == as_of_date), -1)
    if index < period:
        return None
    previous_close = bars[index - period].close
    if not previous_close:
        return None
    return float((bars[index].close / previous_close) - 1)
