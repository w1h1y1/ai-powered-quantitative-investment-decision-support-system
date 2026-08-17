"""Shared fakes for Agent / LLM tests."""

from agent.analysis_schema import ANALYSIS_VERSION
from agent.llm.base import BaseLLMProvider, ProviderResult


def valid_analysis():
    return {
        'market_summary': 'The market is mixed with elevated volatility.',
        'market_regime_summary': 'The regime is high volatility.',
        'technical_summary': 'Momentum is negative while volatility is elevated.',
        'market_context_summary': 'The broad market is sideways and sector context is available.',
        'historical_evidence_summary': 'Historical evaluation is not applicable for Risk-Off.',
        'risk_assessment': 'Elevated volatility increases downside risk.',
        'key_reasons': ['High volatility percentile', 'Risk-Off selected'],
        'risk_factors': ['Elevated volatility', 'Negative momentum'],
        'limitations': ['Historical evaluation is not applicable for Risk-Off'],
    }


class FakeProvider(BaseLLMProvider):
    """Test provider implementing the same interface as DeepSeekProvider."""

    provider_name = 'fake'
    model = 'fake-model'

    def __init__(self, analysis=None, failure_reason=None, configured=True):
        self.analysis = analysis
        self.failure_reason = failure_reason
        self.configured = configured
        self.last_prompt = None

    def is_configured(self):
        return self.configured

    def generate_structured_analysis(self, prompt):
        self.last_prompt = prompt
        if self.failure_reason is not None:
            return ProviderResult(failure_reason=self.failure_reason)
        return ProviderResult(analysis=self.analysis)


class SequenceProvider(BaseLLMProvider):
    """Test provider returning a fixed sequence of ProviderResults."""

    provider_name = 'sequence'
    model = 'sequence-model'

    def __init__(self, *results, configured=True):
        self.results = list(results)
        self.configured = configured
        self.calls = []

    def is_configured(self):
        return self.configured

    def generate_structured_analysis(self, prompt):
        self.calls.append(prompt)
        if not self.results:
            return ProviderResult(failure_reason='invalid_response')
        return self.results.pop(0)


def deepseek_like_analysis_with_string_limitations():
    """Shape reproduced from the real DeepSeek JPM/AAPL responses."""

    analysis = valid_analysis()
    analysis['limitations'] = (
        'The strategy evaluation is based on historical data and does not '
        'guarantee future performance.'
    )
    return analysis


def _default_technical():
    return {
        'latest': {
            'trend_direction': 'bullish',
            'trend_score': 0.42,
            'trend_strength_score': 0.55,
            'price_vs_ma20': 0.02,
            'ma20_vs_ma60': 0.04,
            'price_vs_ma200': 0.06,
            'ma20_slope': 0.001,
            'ma60_slope': 0.0008,
            'adx': 28.2,
            'momentum_score': 0.31,
            'rsi': 58.4,
            'macd_histogram': 1.2345,
            'return_20d': 0.086742,
            'return_60d': -0.0123,
            'volatility_score': 0.4,
            'atr': 2.4,
            'atr_percent': 0.024,
            'realized_volatility_20d': 0.31,
            'volatility_percentile': 0.9,
            'percentile_available': True,
            'choppiness': 42.5,
            'range_score': 0.32,
        },
        'relative_strength': {
            'score': 0.04,
            'vs_spy_20d': 0.031,
            'vs_spy_60d': -0.01,
            'vs_sector_20d': 0.018,
            'vs_sector_60d': 0.008,
        },
        'units': {
            'return_20d': 'decimal_fraction',
            'return_60d': 'decimal_fraction',
            'rsi': 'index_0_to_100',
            'adx': 'index_0_to_100',
            'atr_percent': 'decimal_fraction',
            'realized_volatility_20d': 'decimal_fraction',
            'volatility_percentile': 'decimal_fraction_0_to_1',
        },
    }


def completed_metrics():
    return {
        'initial_capital': '10000.000000',
        'final_equity': '10056.223040',
        'total_return': '0.562230',
        'maximum_drawdown': '0.086431',
        'annualized_volatility': '0.348989',
        'total_fees': '2.000000',
        'executed_order_count': 2,
    }


def empty_metrics():
    return {
        'initial_capital': None,
        'final_equity': None,
        'total_return': None,
        'maximum_drawdown': None,
        'annualized_volatility': None,
        'total_fees': None,
        'executed_order_count': None,
    }


def build_context(
    *,
    symbol='AAPL',
    regime='high_volatility',
    regime_confidence='medium',
    confidence_score=0.61,
    selected_strategy='risk_off',
    strategy_mode='defensive',
    allow_new_long=False,
    risk_off=True,
    selection_confidence='medium',
    evaluation_status='not_applicable',
    evaluation_available=None,
    metrics=None,
    sector_available=True,
    broad_available=True,
    sector_reason=None,
    broad_reason=None,
    evaluation_unavailable_reason=None,
):
    if evaluation_available is None:
        evaluation_available = evaluation_status == 'completed'
    if metrics is None:
        metrics = completed_metrics() if evaluation_available else empty_metrics()
    if evaluation_unavailable_reason is None:
        evaluation_unavailable_reason = (
            None
            if evaluation_available
            else 'Risk-Off is a defensive state rather than an active trading strategy.'
        )

    sector_regime = 'bullish_trend' if sector_available else None
    market_context = {
        'broad_market': 'SPY',
        'broad_market_available': broad_available,
        'broad_market_reason': broad_reason,
        'spy_regime': 'sideways_range' if broad_available else None,
        'sector': 'Information Technology' if sector_available else None,
        'sector_benchmark': 'XLK' if sector_available else None,
        'sector_available': sector_available,
        'sector_reason': sector_reason,
        'sector_regime': sector_regime,
        'confirmation_score': 0.64 if (broad_available and sector_available) else None,
    }

    context = {
        'context_version': 'agent_context_v1',
        'symbol': symbol,
        'as_of_date': '2026-08-14',
        'security': {
            'id': 3,
            'symbol': symbol,
            'name': f'{symbol} Corp',
            'exchange': 'NASDAQ',
            'currency': 'USD',
        },
        'technical': _default_technical(),
        'market_context': market_context,
        'market_regime': {
            'available': True,
            'unavailable_reason': None,
            'regime': regime,
            'confidence': regime_confidence,
            'confidence_score': confidence_score,
            'explanation': [
                'Price is above MA20 and MA200, while MA20 is above MA60.',
                'ADX indicates a meaningful trend.',
            ],
        },
        'strategy_selection': {
            'available': True,
            'unavailable_reason': None,
            'selected_strategy': selected_strategy,
            'strategy_mode': strategy_mode,
            'execution_mode': 'long_only',
            'allow_new_long': allow_new_long,
            'risk_off': risk_off,
            'selection_confidence': selection_confidence,
            'reason': [
                'The current market regime drives the formal strategy selection.',
            ],
        },
        'strategy_evaluation': {
            'available': evaluation_available,
            'status': evaluation_status,
            'unavailable_reason': evaluation_unavailable_reason,
            'evaluation_strategy': selected_strategy if evaluation_available else None,
            'metrics': metrics,
            'evaluation_window': (
                {'start_date': '2025-08-14', 'end_date': '2026-08-14'}
                if evaluation_available
                else None
            ),
            'data_source': (
                {
                    'source': 'database_cache',
                    'requested_start_date': '2025-08-14',
                    'requested_end_date': '2026-08-14',
                    'warmup_debug': 'internal-only',
                }
                if evaluation_available
                else None
            ),
            'strategy_parameters': (
                {'strategy': 'Independent Mean Reversion v1', 'strategy_id': selected_strategy}
                if evaluation_available
                else None
            ),
            'units': {
                'total_return': 'percentage_points',
                'maximum_drawdown': 'percentage_points',
                'annualized_volatility': 'percentage_points',
                'initial_capital': 'money_security_currency',
                'final_equity': 'money_security_currency',
                'total_fees': 'money_security_currency',
                'executed_order_count': 'count',
            },
        },
    }

    degraded = []
    if not (broad_available and sector_available):
        degraded.append('market_context')
    if not evaluation_available and evaluation_status != 'not_applicable':
        degraded.append('strategy_evaluation')
    context['data_quality'] = {
        'all_modules_available': not degraded,
        'degraded_modules': degraded,
        'as_of_date': '2026-08-14',
        'modules': {
            'market_regime': {
                'available': True,
                'status': 'available',
                'reason': None,
                'latest_market_date': '2026-08-14',
                'data_source': 'database_cache',
                'fetched_from_provider': False,
                'provider_error': None,
                'historical_data_count': 320,
            },
            'market_context': {
                'available': broad_available and sector_available,
                'status': 'available' if (broad_available and sector_available) else 'unavailable',
                'reason': broad_reason or sector_reason,
                'broad_market_available': broad_available,
                'broad_market_reason': broad_reason,
                'sector_available': sector_available,
                'sector_reason': sector_reason,
            },
            'strategy_selection': {
                'available': True,
                'status': 'available',
                'reason': None,
                'selection_confidence': selection_confidence,
            },
            'strategy_evaluation': {
                'available': evaluation_available,
                'status': evaluation_status,
                'reason': evaluation_unavailable_reason,
                'latest_market_date': '2026-08-14',
                'data_source': 'database_cache' if evaluation_available else None,
            },
        },
    }
    return context


def risk_off_context():
    return build_context(
        regime='high_volatility',
        selected_strategy='risk_off',
        strategy_mode='defensive',
        allow_new_long=False,
        risk_off=True,
        evaluation_status='not_applicable',
    )


def mean_reversion_context():
    return build_context(
        symbol='JPM',
        regime='sideways_range',
        regime_confidence='low',
        confidence_score=0.51,
        selected_strategy='mean_reversion',
        strategy_mode='active',
        allow_new_long=True,
        risk_off=False,
        selection_confidence='low',
        evaluation_status='completed',
    )


def xom_mean_reversion_context():
    return build_context(
        symbol='XOM',
        regime='sideways_range',
        regime_confidence='high',
        confidence_score=0.77,
        selected_strategy='mean_reversion',
        strategy_mode='active',
        allow_new_long=True,
        risk_off=False,
        selection_confidence='high',
        evaluation_status='completed',
        metrics={
            'initial_capital': '10000.000000',
            'final_equity': '10056.694112',
            'total_return': '0.566941',
            'maximum_drawdown': '0.439024',
            'annualized_volatility': '0.790409',
            'total_fees': '2.000000',
            'executed_order_count': 2,
        },
    )


def bearish_trend_context():
    return build_context(
        symbol='XOM',
        regime='bearish_trend',
        selected_strategy='trend_following',
        strategy_mode='active',
        allow_new_long=False,
        risk_off=False,
        selection_confidence='medium',
        evaluation_status='completed',
    )


def unavailable_context():
    context = build_context(
        sector_available=False,
        broad_available=True,
        sector_reason='sector_metadata_unavailable',
    )
    return context


def analysis_version():
    return ANALYSIS_VERSION
