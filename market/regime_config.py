"""Central, deterministic configuration for Market Regime Detection v1."""

REGIME_BULLISH = 'bullish_trend'
REGIME_BEARISH = 'bearish_trend'
REGIME_SIDEWAYS = 'sideways_range'
REGIME_HIGH_VOLATILITY = 'high_volatility'
MARKET_REGIMES = (
    REGIME_BULLISH,
    REGIME_BEARISH,
    REGIME_SIDEWAYS,
    REGIME_HIGH_VOLATILITY,
)

# Display-ready trend direction. Unlike the aggregate trend score alone, this
# state requires the price/MA structure and both MA slopes to agree, while
# reusing the existing trend-score thresholds below for meaningful magnitude.
TREND_DIRECTION_BULLISH = 'bullish'
TREND_DIRECTION_BEARISH = 'bearish'
TREND_DIRECTION_MIXED = 'mixed'
TREND_DIRECTIONS = (
    TREND_DIRECTION_BULLISH,
    TREND_DIRECTION_BEARISH,
    TREND_DIRECTION_MIXED,
)

BROAD_MARKET_SYMBOL = 'SPY'
REGIME_HISTORY_BARS = 320
CORE_MINIMUM_HISTORY_BARS = 205
MA_SHORT_PERIOD = 20
MA_MEDIUM_PERIOD = 60
MA_LONG_PERIOD = 200
MA_SLOPE_WINDOW = 5
ADX_PERIOD = 14
CHOPPINESS_PERIOD = 14
RSI_PERIOD = 14
ATR_PERIOD = 14
REALIZED_VOLATILITY_PERIOD = 20
VOLATILITY_PERCENTILE_WINDOW = 252
RETURN_PERIODS = (20, 60)
TRADING_DAYS_PER_YEAR = 252

# Interpretation and decision thresholds. Keeping these values together makes
# the first version transparent and prevents rule drift across functions.
ADX_WEAK_THRESHOLD = 20.0
ADX_TREND_THRESHOLD = 25.0
ADX_STRONG_THRESHOLD = 40.0
CHOPPINESS_TREND_THRESHOLD = 45.0
CHOPPINESS_RANGE_THRESHOLD = 55.0
HIGH_VOLATILITY_PERCENTILE_THRESHOLD = 0.85
BULLISH_TREND_SCORE_THRESHOLD = 0.35
BEARISH_TREND_SCORE_THRESHOLD = -0.35
BULLISH_MOMENTUM_THRESHOLD = 0.05
BEARISH_MOMENTUM_THRESHOLD = -0.05

CONFIDENCE_MEDIUM_THRESHOLD = 0.55
CONFIDENCE_HIGH_THRESHOLD = 0.75
MOMENTUM_EXPLANATION_THRESHOLD = 0.15
CORE_CONFIDENCE_WEIGHT = 0.75
CONTEXT_CONFIRMATION_WEIGHT = 0.25
MISSING_CONTEXT_CONFIDENCE_DISCOUNT = 0.85

# Ratio scales used to normalize directional inputs to [-1, +1]. They are
# dimensional rather than price-level thresholds, so they work across assets.
TREND_NORMALIZATION_SCALES = {
    'price_vs_ma20': 0.04,
    'ma20_vs_ma60': 0.06,
    'price_vs_ma200': 0.12,
    'ma20_slope': 0.02,
    'ma60_slope': 0.015,
}
MOMENTUM_NORMALIZATION_SCALES = {
    'rsi': 20.0,
    'macd_histogram_percent': 0.01,
    'return_20d': 0.08,
    'return_60d': 0.16,
}
RELATIVE_STRENGTH_NORMALIZATION_SCALES = {
    20: 0.08,
    60: 0.16,
}
ATR_PERCENT_NORMALIZATION_SCALE = 0.05
REALIZED_VOLATILITY_NORMALIZATION_SCALE = 0.60

SECTOR_ETF_MAP = {
    'Information Technology': 'XLK',
    'Financials': 'XLF',
    'Health Care': 'XLV',
    'Energy': 'XLE',
    'Industrials': 'XLI',
    'Consumer Discretionary': 'XLY',
    'Consumer Staples': 'XLP',
    'Utilities': 'XLU',
    'Materials': 'XLB',
    'Real Estate': 'XLRE',
    'Communication Services': 'XLC',
}

SECTOR_ALIASES = {
    'technology': 'Information Technology',
    'information technology': 'Information Technology',
    'tech': 'Information Technology',
    'financial': 'Financials',
    'financials': 'Financials',
    'financial services': 'Financials',
    'healthcare': 'Health Care',
    'health care': 'Health Care',
    'energy': 'Energy',
    'industrial': 'Industrials',
    'industrials': 'Industrials',
    'consumer cyclical': 'Consumer Discretionary',
    'consumer discretionary': 'Consumer Discretionary',
    'consumer defensive': 'Consumer Staples',
    'consumer staples': 'Consumer Staples',
    'utilities': 'Utilities',
    'basic materials': 'Materials',
    'materials': 'Materials',
    'real estate': 'Real Estate',
    'communication': 'Communication Services',
    'communication services': 'Communication Services',
}

QQQ_ELIGIBLE_SECTORS = frozenset({
    'Information Technology',
    'Communication Services',
    'Consumer Discretionary',
})

# Security currently has no sector/industry columns. This focused first-version
# mapping covers the system's common US equities without a schema migration.
# Unknown or remotely-created symbols degrade to sector_context_available=false.
SECURITY_SECTOR_MAP = {
    'AAPL': 'Information Technology',
    'MSFT': 'Information Technology',
    'NVDA': 'Information Technology',
    'AMD': 'Information Technology',
    'AVGO': 'Information Technology',
    'ORCL': 'Information Technology',
    'CRM': 'Information Technology',
    'JPM': 'Financials',
    'BAC': 'Financials',
    'WFC': 'Financials',
    'GS': 'Financials',
    'JNJ': 'Health Care',
    'UNH': 'Health Care',
    'PFE': 'Health Care',
    'LLY': 'Health Care',
    'XOM': 'Energy',
    'CVX': 'Energy',
    'CAT': 'Industrials',
    'GE': 'Industrials',
    'BA': 'Industrials',
    'AMZN': 'Consumer Discretionary',
    'TSLA': 'Consumer Discretionary',
    'HD': 'Consumer Discretionary',
    'WMT': 'Consumer Staples',
    'PG': 'Consumer Staples',
    'KO': 'Consumer Staples',
    'NEE': 'Utilities',
    'DUK': 'Utilities',
    'LIN': 'Materials',
    'APD': 'Materials',
    'AMT': 'Real Estate',
    'PLD': 'Real Estate',
    'GOOG': 'Communication Services',
    'GOOGL': 'Communication Services',
    'META': 'Communication Services',
    'NFLX': 'Communication Services',
}

BENCHMARK_SECURITY_METADATA = {
    'SPY': {'name': 'SPDR S&P 500 ETF Trust', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLK': {'name': 'Technology Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLF': {'name': 'Financial Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLV': {'name': 'Health Care Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLE': {'name': 'Energy Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLI': {'name': 'Industrial Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLY': {'name': 'Consumer Discretionary Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLP': {'name': 'Consumer Staples Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLU': {'name': 'Utilities Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLB': {'name': 'Materials Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLRE': {'name': 'Real Estate Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
    'XLC': {'name': 'Communication Services Select Sector SPDR Fund', 'exchange': 'NYSEARCA', 'mic_code': 'ARCX'},
}


def normalize_sector_name(value):
    normalized = ' '.join(str(value or '').strip().replace('&', ' and ').split()).lower()
    return SECTOR_ALIASES.get(normalized)


def get_sector_benchmark(sector):
    normalized_sector = normalize_sector_name(sector)
    return SECTOR_ETF_MAP.get(normalized_sector) if normalized_sector else None


def get_security_sector(security):
    model_sector = normalize_sector_name(getattr(security, 'sector', None))
    if model_sector:
        return model_sector, 'security_metadata'
    mapped_sector = normalize_sector_name(SECURITY_SECTOR_MAP.get(security.symbol.upper()))
    return (mapped_sector, 'symbol_mapping') if mapped_sector else (None, None)


def get_backtest_benchmark_options(security):
    """Return benchmark symbols relevant to one backtest asset.

    SPY is always the broad-market reference.  The asset's existing sector
    benchmark is added when available, and QQQ is added only for the sectors
    where it is a meaningful growth/Nasdaq alternative.
    """

    sector, _sector_source = get_security_sector(security)
    sector_benchmark = get_sector_benchmark(sector)
    options = [BROAD_MARKET_SYMBOL]
    if sector_benchmark and sector_benchmark != BROAD_MARKET_SYMBOL:
        options.append(sector_benchmark)
    if sector in QQQ_ELIGIBLE_SECTORS:
        options.append('QQQ')
    return options
