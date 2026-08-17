"""Deterministic Market Regime Detection service.

The core layer uses only one security's trailing OHLCV history. The contextual
layer adds SPY, a dynamic sector ETF, and relative returns without recursively
asking benchmarks for their own contextual regime.
"""

from datetime import timedelta
from decimal import Decimal
from math import ceil

from django.db import IntegrityError, transaction

from backtest.services import (
    DailyBacktestBar,
    calculate_atr,
    calculate_macd,
    calculate_rsi,
    calculate_simple_moving_average,
)

from .models import Security, SecurityDailyPrice
from .regime_config import (
    ADX_PERIOD,
    ADX_STRONG_THRESHOLD,
    ADX_TREND_THRESHOLD,
    ADX_WEAK_THRESHOLD,
    ATR_PERCENT_NORMALIZATION_SCALE,
    ATR_PERIOD,
    BEARISH_MOMENTUM_THRESHOLD,
    BEARISH_TREND_SCORE_THRESHOLD,
    BENCHMARK_SECURITY_METADATA,
    BROAD_MARKET_SYMBOL,
    BULLISH_MOMENTUM_THRESHOLD,
    BULLISH_TREND_SCORE_THRESHOLD,
    CHOPPINESS_PERIOD,
    CHOPPINESS_RANGE_THRESHOLD,
    CHOPPINESS_TREND_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    CONTEXT_CONFIRMATION_WEIGHT,
    CORE_CONFIDENCE_WEIGHT,
    CORE_MINIMUM_HISTORY_BARS,
    HIGH_VOLATILITY_PERCENTILE_THRESHOLD,
    MA_LONG_PERIOD,
    MA_MEDIUM_PERIOD,
    MA_SHORT_PERIOD,
    MA_SLOPE_WINDOW,
    MOMENTUM_NORMALIZATION_SCALES,
    MOMENTUM_EXPLANATION_THRESHOLD,
    MISSING_CONTEXT_CONFIDENCE_DISCOUNT,
    REALIZED_VOLATILITY_NORMALIZATION_SCALE,
    REALIZED_VOLATILITY_PERIOD,
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_HISTORY_BARS,
    REGIME_SIDEWAYS,
    RELATIVE_STRENGTH_NORMALIZATION_SCALES,
    RETURN_PERIODS,
    RSI_PERIOD,
    TREND_DIRECTION_BEARISH,
    TREND_DIRECTION_BULLISH,
    TREND_DIRECTION_MIXED,
    TREND_NORMALIZATION_SCALES,
    VOLATILITY_PERCENTILE_WINDOW,
    get_security_sector,
    get_sector_benchmark,
)
from .regime_indicators import (
    calculate_adx,
    calculate_choppiness_index,
    calculate_realized_volatility,
    period_return_as_of,
    volatility_percentile,
)
from .services import (
    cache_has_requested_coverage,
    fetch_and_cache_daily_prices,
    get_cached_daily_prices,
    get_latest_complete_market_date,
)
from .twelve_data import (
    TwelveDataError,
    TwelveDataInvalidSymbolError,
    TwelveDataRateLimitError,
)


ZERO = Decimal('0')


class MarketRegimeDataUnavailable(Exception):
    pass


class MarketRegimeDataRateLimited(MarketRegimeDataUnavailable):
    pass


def _clamp(value, minimum, maximum):
    return min(max(value, minimum), maximum)


def _round(value):
    return None if value is None else round(float(value), 6)


def _ordinal(value):
    integer = int(round(value))
    if 10 <= integer % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(integer % 10, 'th')
    return f'{integer}{suffix}'


def _ratio(value, reference):
    if value is None or reference in (None, ZERO, 0):
        return None
    return float((value / reference) - 1)


def _normalized(value, scale):
    if value is None or not scale:
        return 0.0
    return _clamp(float(value) / float(scale), -1.0, 1.0)


def _mean(values, default=0.0):
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else default


def determine_trend_direction(trend_components, *, trend_score):
    """Return a display direction only when all existing trend inputs agree.

    It uses the same price/MA relationships and MA slopes that drive the
    deterministic explanation, plus the existing core trend-score thresholds.
    Mixed or near-neutral structure is therefore not reduced to an average's
    sign, and no separate display threshold is introduced.
    """
    component_names = (
        'price_vs_ma20',
        'ma20_vs_ma60',
        'price_vs_ma200',
        'ma20_slope',
        'ma60_slope',
    )
    values = tuple(trend_components.get(name) for name in component_names)
    if (
        all(value is not None and value > 0 for value in values)
        and trend_score >= BULLISH_TREND_SCORE_THRESHOLD
    ):
        return TREND_DIRECTION_BULLISH
    if (
        all(value is not None and value < 0 for value in values)
        and trend_score <= BEARISH_TREND_SCORE_THRESHOLD
    ):
        return TREND_DIRECTION_BEARISH
    return TREND_DIRECTION_MIXED


def _history_start_date(end_date, requested_bars=REGIME_HISTORY_BARS):
    calendar_days = ceil((requested_bars + 10) * 365 / 252) + 30
    return end_date - timedelta(days=calendar_days)


def _prices_to_bars(prices):
    return tuple(
        DailyBacktestBar(
            date=price.date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.close,
        )
        for price in prices
        if (
            price.open is not None
            and price.high is not None
            and price.low is not None
            and price.close is not None
            and price.open > ZERO
            and price.high > ZERO
            and price.low > ZERO
            and price.close > ZERO
        )
    )


class MarketRegimeDataLoader:
    """Load each symbol at most once per regime request."""

    def __init__(self, requested_bars=REGIME_HISTORY_BARS):
        self.requested_bars = requested_bars
        self._results = {}

    def load(self, security):
        cache_key = security.pk or (security.symbol, security.mic_code)
        if cache_key in self._results:
            return self._results[cache_key]

        end_date = get_latest_complete_market_date()
        start_date = _history_start_date(end_date, self.requested_bars)
        cached_before_fetch = get_cached_daily_prices(security, start_date, end_date)
        fetched_from_provider = False
        provider_error = None

        if not cache_has_requested_coverage(security, start_date, end_date):
            try:
                fetch_and_cache_daily_prices(
                    security,
                    start_date,
                    end_date,
                    require_exact_window=True,
                )
                fetched_from_provider = True
            except TwelveDataRateLimitError as exc:
                provider_error = str(exc)
                if not cached_before_fetch:
                    raise MarketRegimeDataRateLimited(
                        f'Market data provider rate limit reached for {security.symbol}.'
                    ) from exc
            except TwelveDataInvalidSymbolError as exc:
                provider_error = str(exc)
                if not cached_before_fetch:
                    raise MarketRegimeDataUnavailable(
                        f'Market data is not available for {security.symbol}.'
                    ) from exc
            except TwelveDataError as exc:
                provider_error = str(exc)
                if not cached_before_fetch:
                    raise MarketRegimeDataUnavailable(
                        f'Market data is temporarily unavailable for {security.symbol}.'
                    ) from exc

        prices = get_cached_daily_prices(security, start_date, end_date)
        bars = _prices_to_bars(prices)[-self.requested_bars:]
        metadata = {
            'symbol': security.symbol,
            'source': 'twelve_data' if fetched_from_provider else 'database_cache',
            'price_model': SecurityDailyPrice.SOURCE_TWELVE_DATA,
            'record_count': len(bars),
            'requested_bars': self.requested_bars,
            'first_date': bars[0].date.isoformat() if bars else None,
            'last_date': bars[-1].date.isoformat() if bars else None,
            'fetched_from_provider': fetched_from_provider,
            'provider_error': provider_error,
        }
        self._results[cache_key] = (bars, metadata)
        return self._results[cache_key]


def ensure_benchmark_security(symbol):
    normalized_symbol = symbol.strip().upper()
    security = (
        Security.objects
        .filter(symbol=normalized_symbol, is_active=True)
        .order_by('-country', 'mic_code', 'exchange', 'id')
        .first()
    )
    if security is not None:
        return security

    metadata = BENCHMARK_SECURITY_METADATA.get(normalized_symbol)
    if metadata is None:
        return None
    defaults = {
        'name': metadata['name'],
        'asset_type': Security.AssetType.ETF,
        'exchange': metadata['exchange'],
        'country': 'United States',
        'currency': 'USD',
        'is_active': True,
    }
    try:
        with transaction.atomic():
            return Security.objects.create(
                symbol=normalized_symbol,
                mic_code=metadata['mic_code'],
                **defaults,
            )
    except IntegrityError:
        return Security.objects.filter(
            symbol=normalized_symbol,
            mic_code=metadata['mic_code'],
        ).first()


def classify_core_regime(*, trend_score, adx, choppiness, momentum_score, volatility_percentile_value):
    if (
        volatility_percentile_value is not None
        and volatility_percentile_value >= HIGH_VOLATILITY_PERCENTILE_THRESHOLD
    ):
        return REGIME_HIGH_VOLATILITY
    if (
        trend_score >= BULLISH_TREND_SCORE_THRESHOLD
        and adx >= ADX_TREND_THRESHOLD
        and choppiness <= CHOPPINESS_RANGE_THRESHOLD
        and momentum_score >= BULLISH_MOMENTUM_THRESHOLD
    ):
        return REGIME_BULLISH
    if (
        trend_score <= BEARISH_TREND_SCORE_THRESHOLD
        and adx >= ADX_TREND_THRESHOLD
        and choppiness <= CHOPPINESS_RANGE_THRESHOLD
        and momentum_score <= BEARISH_MOMENTUM_THRESHOLD
    ):
        return REGIME_BEARISH
    return REGIME_SIDEWAYS


def _confidence_label(score):
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return 'high'
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return 'medium'
    return 'low'


def _core_confidence_score(regime, *, trend_score, strength_score, range_score, momentum_score, volatility_score):
    if regime == REGIME_HIGH_VOLATILITY:
        return _clamp(volatility_score, 0.0, 1.0)
    if regime == REGIME_BULLISH:
        return _mean((
            max(trend_score, 0.0),
            strength_score,
            1.0 - range_score,
            max(momentum_score, 0.0),
        ))
    if regime == REGIME_BEARISH:
        return _mean((
            max(-trend_score, 0.0),
            strength_score,
            1.0 - range_score,
            max(-momentum_score, 0.0),
        ))
    return _mean((
        1.0 - abs(trend_score),
        1.0 - strength_score,
        range_score,
        1.0 - abs(momentum_score),
    ))


def _core_explanation(*, regime, trend, momentum, volatility, range_data):
    explanations = []
    price_relations = (
        trend['price_vs_ma20'],
        trend['ma20_vs_ma60'],
        trend['price_vs_ma200'],
    )
    if all(value is not None and value > 0 for value in price_relations):
        explanations.append('Price is above MA20 and MA200, while MA20 is above MA60.')
    elif all(value is not None and value < 0 for value in price_relations):
        explanations.append('Price is below MA20 and MA200, while MA20 is below MA60.')
    else:
        explanations.append('Moving-average direction is mixed.')

    if trend['ma20_slope'] > 0 and trend['ma60_slope'] > 0:
        explanations.append('MA20 and MA60 slopes are positive.')
    elif trend['ma20_slope'] < 0 and trend['ma60_slope'] < 0:
        explanations.append('MA20 and MA60 slopes are negative.')
    else:
        explanations.append('MA20 and MA60 slopes do not agree.')

    adx = trend['adx']
    if adx >= ADX_STRONG_THRESHOLD:
        explanations.append('ADX indicates a strong trend.')
    elif adx >= ADX_TREND_THRESHOLD:
        explanations.append('ADX indicates a meaningful trend.')
    elif adx < ADX_WEAK_THRESHOLD:
        explanations.append('ADX indicates weak or absent trend strength.')
    else:
        explanations.append('ADX indicates a forming trend.')

    choppiness = range_data['choppiness']
    if choppiness > CHOPPINESS_RANGE_THRESHOLD:
        explanations.append('Choppiness is range-friendly.')
    elif choppiness < CHOPPINESS_TREND_THRESHOLD:
        explanations.append('Choppiness is trend-friendly.')
    else:
        explanations.append('Choppiness is in a mixed zone.')

    percentile = volatility['volatility_percentile']
    if percentile is None:
        explanations.append('Volatility percentile is unavailable because its full history window is incomplete.')
    else:
        explanations.append(
            f'Current volatility is in approximately the {_ordinal(percentile * 100)} percentile.'
        )

    if momentum['score'] > MOMENTUM_EXPLANATION_THRESHOLD:
        explanations.append('RSI, MACD and trailing returns provide positive momentum confirmation.')
    elif momentum['score'] < -MOMENTUM_EXPLANATION_THRESHOLD:
        explanations.append('RSI, MACD and trailing returns provide negative momentum confirmation.')
    else:
        explanations.append('Momentum confirmation is mixed or weak.')

    if regime == REGIME_HIGH_VOLATILITY:
        explanations.append('High volatility takes priority over directional trend classification.')
    return explanations


def _empty_core(reason='insufficient_history'):
    return {
        'regime_available': False,
        'regime_unavailable_reason': reason,
        'regime': None,
        'confidence': None,
        'confidence_score': None,
        'trend': {
            'direction': None, 'score': None, 'strength_score': None, 'price_vs_ma20': None,
            'ma20_vs_ma60': None, 'price_vs_ma200': None, 'ma20_slope': None,
            'ma60_slope': None, 'adx': None,
        },
        'range': {'choppiness': None, 'score': None},
        'momentum': {
            'score': None, 'rsi': None, 'macd_histogram': None,
            'return_20d': None, 'return_60d': None,
        },
        'volatility': {
            'score': None, 'atr': None, 'atr_percent': None,
            'realized_volatility_20d': None, 'volatility_percentile': None,
            'percentile_available': False,
            'percentile_unavailable_reason': 'insufficient_volatility_history',
        },
        'explanation': ['Insufficient historical data to calculate the core market regime.'],
    }


def compute_core_regime(bars):
    if len(bars) < CORE_MINIMUM_HISTORY_BARS:
        return _empty_core()

    ma20_values = calculate_simple_moving_average(bars, MA_SHORT_PERIOD)
    ma60_values = calculate_simple_moving_average(bars, MA_MEDIUM_PERIOD)
    ma200_values = calculate_simple_moving_average(bars, MA_LONG_PERIOD)
    rsi_values = calculate_rsi(bars, RSI_PERIOD)
    atr_values = calculate_atr(bars, ATR_PERIOD)
    _, _, macd_histogram_values = calculate_macd(bars)
    adx_values = calculate_adx(bars, ADX_PERIOD)
    choppiness_values = calculate_choppiness_index(bars, CHOPPINESS_PERIOD)
    realized_volatility_values = calculate_realized_volatility(
        bars,
        REALIZED_VOLATILITY_PERIOD,
    )

    close = bars[-1].close
    ma20 = ma20_values[-1]
    ma60 = ma60_values[-1]
    ma200 = ma200_values[-1]
    previous_ma20 = ma20_values[-1 - MA_SLOPE_WINDOW]
    previous_ma60 = ma60_values[-1 - MA_SLOPE_WINDOW]
    adx = adx_values[-1]
    choppiness = choppiness_values[-1]
    rsi = rsi_values[-1]
    atr = atr_values[-1]
    macd_histogram = macd_histogram_values[-1]
    realized_volatility = realized_volatility_values[-1]
    return_20d = period_return_as_of(bars, 20)
    return_60d = period_return_as_of(bars, 60)
    required_values = (
        ma20, ma60, ma200, previous_ma20, previous_ma60, adx, choppiness,
        rsi, atr, macd_histogram, realized_volatility, return_20d, return_60d,
    )
    if any(value is None for value in required_values):
        return _empty_core()

    price_vs_ma20 = _ratio(close, ma20)
    ma20_vs_ma60 = _ratio(ma20, ma60)
    price_vs_ma200 = _ratio(close, ma200)
    ma20_slope = _ratio(ma20, previous_ma20)
    ma60_slope = _ratio(ma60, previous_ma60)
    trend_components = {
        'price_vs_ma20': price_vs_ma20,
        'ma20_vs_ma60': ma20_vs_ma60,
        'price_vs_ma200': price_vs_ma200,
        'ma20_slope': ma20_slope,
        'ma60_slope': ma60_slope,
    }
    trend_score = _mean([
        _normalized(value, TREND_NORMALIZATION_SCALES[name])
        for name, value in trend_components.items()
    ])
    strength_score = _clamp(
        (float(adx) - ADX_WEAK_THRESHOLD) / (ADX_STRONG_THRESHOLD - ADX_WEAK_THRESHOLD),
        0.0,
        1.0,
    )
    range_score = _clamp(
        (float(choppiness) - CHOPPINESS_TREND_THRESHOLD)
        / (CHOPPINESS_RANGE_THRESHOLD - CHOPPINESS_TREND_THRESHOLD),
        0.0,
        1.0,
    )
    macd_histogram_percent = float(macd_histogram / close)
    momentum_score = _mean((
        _normalized(float(rsi) - 50.0, MOMENTUM_NORMALIZATION_SCALES['rsi']),
        _normalized(
            macd_histogram_percent,
            MOMENTUM_NORMALIZATION_SCALES['macd_histogram_percent'],
        ),
        _normalized(return_20d, MOMENTUM_NORMALIZATION_SCALES['return_20d']),
        _normalized(return_60d, MOMENTUM_NORMALIZATION_SCALES['return_60d']),
    ))
    atr_percent = float(atr / close)
    percentile = volatility_percentile(
        realized_volatility_values,
        VOLATILITY_PERCENTILE_WINDOW,
    )
    volatility_score = _mean((
        percentile,
        _clamp(atr_percent / ATR_PERCENT_NORMALIZATION_SCALE, 0.0, 1.0),
        _clamp(
            realized_volatility / REALIZED_VOLATILITY_NORMALIZATION_SCALE,
            0.0,
            1.0,
        ),
    ))
    regime = classify_core_regime(
        trend_score=trend_score,
        adx=float(adx),
        choppiness=float(choppiness),
        momentum_score=momentum_score,
        volatility_percentile_value=percentile,
    )
    core_confidence_score = _core_confidence_score(
        regime,
        trend_score=trend_score,
        strength_score=strength_score,
        range_score=range_score,
        momentum_score=momentum_score,
        volatility_score=volatility_score,
    )
    trend = {
        'direction': determine_trend_direction(
            trend_components,
            trend_score=trend_score,
        ),
        'score': _round(trend_score),
        'strength_score': _round(strength_score),
        **{name: _round(value) for name, value in trend_components.items()},
        'adx': _round(adx),
    }
    range_data = {'choppiness': _round(choppiness), 'score': _round(range_score)}
    momentum = {
        'score': _round(momentum_score),
        'rsi': _round(rsi),
        'macd_histogram': _round(macd_histogram),
        'return_20d': _round(return_20d),
        'return_60d': _round(return_60d),
    }
    volatility = {
        'score': _round(volatility_score),
        'atr': _round(atr),
        'atr_percent': _round(atr_percent),
        'realized_volatility_20d': _round(realized_volatility),
        'volatility_percentile': _round(percentile),
        'percentile_available': percentile is not None,
        'percentile_unavailable_reason': None if percentile is not None else 'insufficient_volatility_history',
    }
    return {
        'regime_available': True,
        'regime_unavailable_reason': None,
        'regime': regime,
        'confidence': _confidence_label(core_confidence_score),
        'confidence_score': _round(core_confidence_score),
        'trend': trend,
        'range': range_data,
        'momentum': momentum,
        'volatility': volatility,
        'explanation': _core_explanation(
            regime=regime,
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            range_data=range_data,
        ),
    }


def _benchmark_context(loader, symbol, as_of_date):
    security = ensure_benchmark_security(symbol)
    if security is None:
        return None, None, None, None, 'benchmark_security_unavailable'
    try:
        bars, metadata = loader.load(security)
    except MarketRegimeDataRateLimited:
        return security, None, None, None, 'benchmark_rate_limited'
    except MarketRegimeDataUnavailable:
        return security, None, None, None, 'benchmark_market_data_unavailable'

    positions = [index for index, bar in enumerate(bars) if bar.date == as_of_date]
    if not positions:
        return security, bars, None, metadata, 'benchmark_date_unavailable'
    aligned_bars = bars[:positions[-1] + 1]
    core = compute_core_regime(aligned_bars)
    if not core['regime_available']:
        return security, aligned_bars, core, metadata, 'benchmark_insufficient_history'
    return security, aligned_bars, core, metadata, None


def _relative_strength(stock_core, spy_bars, sector_bars, as_of_date):
    values = {
        'vs_spy_20d': None,
        'vs_spy_60d': None,
        'vs_sector_20d': None,
        'vs_sector_60d': None,
    }
    score_components = []
    for period in RETURN_PERIODS:
        stock_return = stock_core['momentum'][f'return_{period}d']
        spy_return = period_return_as_of(spy_bars or (), period, as_of_date)
        sector_return = period_return_as_of(sector_bars or (), period, as_of_date)
        if stock_return is not None and spy_return is not None:
            relative_value = stock_return - spy_return
            values[f'vs_spy_{period}d'] = _round(relative_value)
            score_components.append(_normalized(
                relative_value,
                RELATIVE_STRENGTH_NORMALIZATION_SCALES[period],
            ))
        if stock_return is not None and sector_return is not None:
            relative_value = stock_return - sector_return
            values[f'vs_sector_{period}d'] = _round(relative_value)
            score_components.append(_normalized(
                relative_value,
                RELATIVE_STRENGTH_NORMALIZATION_SCALES[period],
            ))
    values['score'] = _round(_mean(score_components)) if score_components else None
    return values


def _regime_alignment(stock_regime, context_regime):
    if context_regime is None:
        return None
    if stock_regime == REGIME_HIGH_VOLATILITY:
        return 1.0 if context_regime == REGIME_HIGH_VOLATILITY else 0.5
    if stock_regime == REGIME_SIDEWAYS:
        return 1.0 if context_regime == REGIME_SIDEWAYS else 0.0
    stock_direction = 1.0 if stock_regime == REGIME_BULLISH else -1.0
    context_direction = {
        REGIME_BULLISH: 1.0,
        REGIME_BEARISH: -1.0,
        REGIME_SIDEWAYS: 0.0,
        REGIME_HIGH_VOLATILITY: 0.0,
    }[context_regime]
    return (1.0 + (stock_direction * context_direction)) / 2.0


def _market_confirmation_score(stock_regime, spy_regime, sector_regime, relative_strength_score):
    components = [
        _regime_alignment(stock_regime, spy_regime),
        _regime_alignment(stock_regime, sector_regime),
    ]
    if relative_strength_score is not None and stock_regime in (REGIME_BULLISH, REGIME_BEARISH):
        direction = 1.0 if stock_regime == REGIME_BULLISH else -1.0
        components.append((1.0 + (direction * relative_strength_score)) / 2.0)
    present = [value for value in components if value is not None]
    return _mean(present) if present else None


def _context_explanations(relative_strength, spy_core, sector_core, sector_symbol):
    explanations = []
    spy_20d = relative_strength['vs_spy_20d']
    if spy_20d is not None:
        relation = 'outperforming' if spy_20d > 0 else 'underperforming'
        explanations.append(f'The stock is {relation} SPY over 20 trading days.')
    sector_20d = relative_strength['vs_sector_20d']
    if sector_20d is not None and sector_symbol:
        relation = 'outperforming' if sector_20d > 0 else 'underperforming'
        explanations.append(f'The stock is {relation} {sector_symbol} over 20 trading days.')
    if spy_core and spy_core['regime_available']:
        explanations.append(f'SPY core regime is {spy_core["regime"]}.')
    if sector_core and sector_core['regime_available'] and sector_symbol:
        explanations.append(f'{sector_symbol} core regime is {sector_core["regime"]}.')
    return explanations


def get_market_regime(security, *, loader=None):
    data_loader = loader or MarketRegimeDataLoader()
    stock_bars, stock_metadata = data_loader.load(security)
    stock_core = compute_core_regime(stock_bars)
    sector, sector_source = get_security_sector(security)
    sector_benchmark = get_sector_benchmark(sector)
    base_response = {
        'symbol': security.symbol,
        'security_id': security.pk,
        'latest_market_date': stock_bars[-1].date.isoformat() if stock_bars else None,
        'historical_data_count': len(stock_bars),
        'required_core_history_count': CORE_MINIMUM_HISTORY_BARS,
        'regime_available': stock_core['regime_available'],
        'regime_unavailable_reason': stock_core['regime_unavailable_reason'],
        'regime': stock_core['regime'],
        'confidence': stock_core['confidence'],
        'confidence_score': stock_core['confidence_score'],
        'trend': stock_core['trend'],
        'range': stock_core['range'],
        'momentum': stock_core['momentum'],
        'volatility': stock_core['volatility'],
        'relative_strength': {
            'score': None,
            'vs_spy_20d': None, 'vs_spy_60d': None,
            'vs_sector_20d': None, 'vs_sector_60d': None,
        },
        'sector': sector,
        'sector_source': sector_source,
        'sector_benchmark': sector_benchmark,
        'sector_context_available': False,
        'sector_context_reason': 'sector_metadata_unavailable' if not sector else None,
        'market_context': {
            'broad_market': BROAD_MARKET_SYMBOL,
            'broad_market_context_available': False,
            'broad_market_context_reason': None,
            'spy_regime': None,
            'sector': sector,
            'sector_source': sector_source,
            'sector_benchmark': sector_benchmark,
            'sector_context_available': False,
            'sector_context_reason': 'sector_metadata_unavailable' if not sector else None,
            'sector_regime': None,
            'confirmation_score': None,
        },
        'market_data': {'stock': stock_metadata, 'spy': None, 'sector': None},
        'explanation': list(stock_core['explanation']),
        'engine': {
            'name': 'deterministic_market_regime_v1',
            'uses_llm': False,
            'contextual_regime_recursion': False,
        },
    }
    if not stock_core['regime_available']:
        return base_response

    as_of_date = stock_bars[-1].date
    _, spy_bars, spy_core, spy_metadata, spy_reason = _benchmark_context(
        data_loader,
        BROAD_MARKET_SYMBOL,
        as_of_date,
    )
    sector_bars = sector_core = sector_metadata = None
    sector_reason = 'sector_metadata_unavailable' if not sector else None
    if sector_benchmark:
        _, sector_bars, sector_core, sector_metadata, sector_reason = _benchmark_context(
            data_loader,
            sector_benchmark,
            as_of_date,
        )

    relative_strength = _relative_strength(
        stock_core,
        spy_bars,
        sector_bars,
        as_of_date,
    )
    confirmation_score = _market_confirmation_score(
        stock_core['regime'],
        spy_core['regime'] if spy_core and spy_core['regime_available'] else None,
        sector_core['regime'] if sector_core and sector_core['regime_available'] else None,
        relative_strength['score'],
    )
    contextual_confidence_score = (
        (CORE_CONFIDENCE_WEIGHT * stock_core['confidence_score'])
        + (CONTEXT_CONFIRMATION_WEIGHT * confirmation_score)
        if confirmation_score is not None
        else MISSING_CONTEXT_CONFIDENCE_DISCOUNT * stock_core['confidence_score']
    )
    base_response.update({
        'confidence': _confidence_label(contextual_confidence_score),
        'confidence_score': _round(contextual_confidence_score),
        'relative_strength': relative_strength,
        'sector_context_available': sector_reason is None,
        'sector_context_reason': sector_reason,
        'market_context': {
            'broad_market': BROAD_MARKET_SYMBOL,
            'broad_market_context_available': spy_reason is None,
            'broad_market_context_reason': spy_reason,
            'spy_regime': spy_core['regime'] if spy_core and spy_core['regime_available'] else None,
            'sector': sector,
            'sector_source': sector_source,
            'sector_benchmark': sector_benchmark,
            'sector_context_available': sector_reason is None,
            'sector_context_reason': sector_reason,
            'sector_regime': (
                sector_core['regime']
                if sector_core and sector_core['regime_available'] else None
            ),
            'confirmation_score': _round(confirmation_score),
        },
        'market_data': {
            'stock': stock_metadata,
            'spy': spy_metadata,
            'sector': sector_metadata,
        },
    })
    base_response['explanation'].extend(_context_explanations(
        relative_strength,
        spy_core,
        sector_core,
        sector_benchmark,
    ))
    return base_response


__all__ = [
    'MarketRegimeDataLoader',
    'MarketRegimeDataRateLimited',
    'MarketRegimeDataUnavailable',
    'classify_core_regime',
    'compute_core_regime',
    'determine_trend_direction',
    'ensure_benchmark_security',
    'get_market_regime',
]
