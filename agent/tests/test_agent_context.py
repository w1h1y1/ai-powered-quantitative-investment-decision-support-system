from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from backtest.strategy_evaluation_service import (
    STRATEGY_EVALUATOR_REGISTRY,
    StrategyEvaluatorRegistration,
    evaluate_selected_strategy,
)
from market.regime_config import (
    REGIME_BEARISH,
    REGIME_BULLISH,
    REGIME_HIGH_VOLATILITY,
    REGIME_SIDEWAYS,
)
from market.strategy_selection_service import (
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RISK_OFF,
    STRATEGY_TREND_FOLLOWING,
    select_strategy,
)

from agent.agent_context_service import (
    AGENT_CONTEXT_VERSION,
    build_agent_context,
    build_agent_context_from_parts,
)
from agent.schemas import EVALUATION_UNITS, RELATIVE_STRENGTH_UNITS, TECHNICAL_UNITS


TOP_LEVEL_KEYS = (
    'context_version',
    'symbol',
    'as_of_date',
    'security',
    'technical',
    'market_context',
    'market_regime',
    'strategy_selection',
    'strategy_evaluation',
    'data_quality',
)

FORBIDDEN_LARGE_FIELDS = ('equity_curve', 'drawdown_curve', 'trades', 'values', 'warmup_values')


def fake_security(symbol, pk):
    return SimpleNamespace(
        id=pk,
        pk=pk,
        symbol=symbol,
        name=f'{symbol} Security',
        asset_type='STOCK' if symbol != 'SPY' else 'ETF',
        exchange='NASDAQ',
        currency='USD',
    )


def regime_payload(
    regime=REGIME_BULLISH,
    *,
    available=True,
    broad_available=True,
    sector_available=True,
    symbol='AAPL',
):
    if not available:
        broad_available = False
        sector_available = False
    trend = available
    return {
        'symbol': symbol,
        'security_id': 1,
        'latest_market_date': '2026-08-14' if available else '2026-08-14',
        'historical_data_count': 320 if available else 100,
        'required_core_history_count': 205,
        'regime_available': available,
        'regime_unavailable_reason': None if available else 'insufficient_history',
        'regime': regime if available else None,
        'confidence': 'medium' if available else None,
        'confidence_score': 0.61 if available else None,
        'trend': {
            'direction': 'bullish' if trend else None,
            'score': 0.42 if trend else None,
            'strength_score': 0.55 if trend else None,
            'price_vs_ma20': 0.02 if trend else None,
            'ma20_vs_ma60': 0.04 if trend else None,
            'price_vs_ma200': 0.06 if trend else None,
            'ma20_slope': 0.001 if trend else None,
            'ma60_slope': 0.0008 if trend else None,
            'adx': 28.2 if trend else None,
        },
        'range': {
            'choppiness': 42.5 if available else None,
            'score': 0.32 if available else None,
        },
        'momentum': {
            'score': 0.31 if available else None,
            'rsi': 58.4 if available else None,
            'macd_histogram': 1.2345 if available else None,
            'return_20d': 0.086742 if available else None,
            'return_60d': -0.0123 if available else None,
        },
        'volatility': {
            'score': 0.4 if available else None,
            'atr': 2.4 if available else None,
            'atr_percent': 0.024 if available else None,
            'realized_volatility_20d': 0.31 if available else None,
            'volatility_percentile': 0.9 if available else None,
            'percentile_available': available,
            'percentile_unavailable_reason': None if available else 'insufficient_volatility_history',
        },
        'relative_strength': {
            'score': 0.04 if available else None,
            'vs_spy_20d': 0.031 if available else None,
            'vs_spy_60d': -0.01 if available else None,
            'vs_sector_20d': 0.018 if available else None,
            'vs_sector_60d': 0.008 if available else None,
        },
        'sector': 'Information Technology' if sector_available else None,
        'sector_source': 'symbol_mapping' if sector_available else None,
        'sector_benchmark': 'XLK' if sector_available else None,
        'sector_context_available': sector_available,
        'sector_context_reason': None if sector_available else 'sector_metadata_unavailable',
        'market_context': {
            'broad_market': 'SPY',
            'broad_market_context_available': broad_available,
            'broad_market_context_reason': None if broad_available else (
                'benchmark_market_data_unavailable'
                if available
                else None
            ),
            'spy_regime': 'sideways_range' if broad_available else None,
            'sector': 'Information Technology' if sector_available else None,
            'sector_source': 'symbol_mapping' if sector_available else None,
            'sector_benchmark': 'XLK' if sector_available else None,
            'sector_context_available': sector_available,
            'sector_context_reason': None if sector_available else 'sector_metadata_unavailable',
            'sector_regime': 'bullish_trend' if sector_available else None,
            'confirmation_score': 0.64 if (broad_available and sector_available) else None,
        },
        'market_data': {
            'stock': {
                'source': 'database_cache',
                'price_model': 'TEST_DAILY_OHLC',
                'record_count': 320 if available else 100,
                'first_date': '2025-08-01',
                'last_date': '2026-08-14',
                'fetched_from_provider': False,
                'provider_error': None,
            },
            'spy': {
                'source': 'database_cache',
                'fetched_from_provider': False,
            } if broad_available else None,
            'sector': {
                'source': 'database_cache',
                'fetched_from_provider': False,
            } if sector_available else None,
        },
        'explanation': (
            [
                'Price is above MA20 and MA200, while MA20 is above MA60.',
                'ADX indicates a meaningful trend.',
            ]
            if available
            else ['Insufficient historical data to calculate the core market regime.']
        ),
        'engine': {
            'name': 'deterministic_market_regime_v1',
            'uses_llm': False,
            'contextual_regime_recursion': False,
        },
    }


def completed_evaluation(strategy_id):
    return {
        'evaluation_available': True,
        'evaluation_status': 'completed',
        'evaluation_unavailable_reason': None,
        'evaluation_strategy': strategy_id,
        'initial_capital': '10000.000000',
        'final_equity': '10123.450000',
        'total_return': '12.345678',
        'maximum_drawdown': '8.123456',
        'annualized_volatility': '15.250000',
        'total_fees': '2.000000',
        'executed_order_count': 3,
        'evaluation_window': {
            'start_date': '2025-08-14',
            'end_date': '2026-08-14',
        },
        'data_source': {
            'source': 'database_cache',
            'requested_start_date': '2025-08-14',
            'requested_end_date': '2026-08-14',
        },
        'strategy_parameters': {
            'strategy': 'Independent Mean Reversion v1',
            'strategy_id': strategy_id,
            'adapter': 'independent',
            'risk_fraction': '0.010000',
        },
        'market_regime_latest_market_date': '2026-08-14',
    }


def not_applicable_evaluation():
    return {
        'evaluation_available': False,
        'evaluation_status': 'not_applicable',
        'evaluation_unavailable_reason': (
            'Risk-Off is a defensive state rather than an active trading strategy.'
        ),
        'evaluation_strategy': None,
        'initial_capital': None,
        'final_equity': None,
        'total_return': None,
        'maximum_drawdown': None,
        'annualized_volatility': None,
        'total_fees': None,
        'executed_order_count': None,
        'evaluation_window': None,
        'data_source': None,
        'strategy_parameters': None,
        'market_regime_latest_market_date': '2026-08-14',
    }


def unavailable_evaluation():
    return {
        **not_applicable_evaluation(),
        'evaluation_status': 'unavailable',
        'evaluation_unavailable_reason': 'market_regime_unavailable',
    }


def assert_no_large_arrays(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in FORBIDDEN_LARGE_FIELDS, f'forbidden field present: {key}'
            assert_no_large_arrays(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_large_arrays(item)


class AgentContextSchemaTests(SimpleTestCase):
    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)

    def context_for(
        self,
        *,
        regime,
        evaluation,
        broad_available=True,
        sector_available=True,
        available=True,
    ):
        regime_result = regime_payload(
            regime,
            available=available,
            broad_available=broad_available,
            sector_available=sector_available,
        )
        strategy_selection = select_strategy(regime_result)
        return build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=evaluation,
        )

    def test_schema_has_stable_top_level_fields_and_version(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )

        for key in TOP_LEVEL_KEYS:
            self.assertIn(key, context)
        self.assertEqual(context['context_version'], AGENT_CONTEXT_VERSION)
        self.assertEqual(context['symbol'], 'AAPL')
        self.assertEqual(context['as_of_date'], '2026-08-14')

    def test_schema_never_contains_large_arrays(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        assert_no_large_arrays(context)

    def test_security_payload_is_minimal(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        self.assertEqual(context['security'], {
            'id': 1,
            'symbol': 'AAPL',
            'name': 'AAPL Security',
            'exchange': 'NASDAQ',
            'currency': 'USD',
        })

    def test_technical_payload_carries_latest_indicators_and_units(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        technical = context['technical']
        self.assertEqual(technical['latest']['trend_direction'], 'bullish')
        self.assertEqual(technical['latest']['adx'], 28.2)
        self.assertEqual(technical['latest']['return_20d'], 0.086742)
        self.assertEqual(technical['units']['return_20d'], 'decimal_fraction')
        self.assertEqual(technical['units']['rsi'], 'index_0_to_100')
        self.assertEqual(
            technical['units']['relative_strength'],
            RELATIVE_STRENGTH_UNITS,
        )
        self.assertEqual(
            technical['relative_strength']['vs_spy_20d'],
            0.031,
        )

    def test_units_never_confuse_technical_fractions_with_evaluation_percentage_points(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        self.assertEqual(
            context['technical']['units']['return_20d'],
            'decimal_fraction',
        )
        self.assertEqual(
            context['technical']['units']['return_60d'],
            'decimal_fraction',
        )
        evaluation_units = context['strategy_evaluation']['units']
        self.assertEqual(evaluation_units['total_return'], 'percentage_points')
        self.assertEqual(evaluation_units['maximum_drawdown'], 'percentage_points')
        self.assertEqual(evaluation_units['annualized_volatility'], 'percentage_points')
        self.assertEqual(evaluation_units['initial_capital'], 'money_security_currency')
        self.assertEqual(evaluation_units['executed_order_count'], 'count')
        self.assertEqual(EVALUATION_UNITS['total_return'], 'percentage_points')
        self.assertEqual(TECHNICAL_UNITS['return_20d'], 'decimal_fraction')

    def test_market_context_payload_keeps_real_fields(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        market_context = context['market_context']
        self.assertEqual(market_context['broad_market'], 'SPY')
        self.assertEqual(market_context['spy_regime'], 'sideways_range')
        self.assertEqual(market_context['sector'], 'Information Technology')
        self.assertEqual(market_context['sector_benchmark'], 'XLK')
        self.assertEqual(market_context['sector_regime'], 'bullish_trend')
        self.assertEqual(market_context['confirmation_score'], 0.64)

    def test_strategy_evaluation_payload_keeps_only_small_parameters(self):
        context = self.context_for(
            regime=REGIME_BULLISH,
            evaluation=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        evaluation = context['strategy_evaluation']
        self.assertTrue(evaluation['available'])
        self.assertEqual(evaluation['status'], 'completed')
        self.assertEqual(evaluation['evaluation_strategy'], STRATEGY_TREND_FOLLOWING)
        self.assertEqual(evaluation['metrics']['total_return'], '12.345678')
        self.assertEqual(evaluation['metrics']['executed_order_count'], 3)
        self.assertEqual(
            evaluation['strategy_parameters'],
            {
                'strategy': 'Independent Mean Reversion v1',
                'strategy_id': STRATEGY_TREND_FOLLOWING,
            },
        )
        self.assertEqual(
            evaluation['evaluation_window'],
            {'start_date': '2025-08-14', 'end_date': '2026-08-14'},
        )
        self.assertEqual(evaluation['data_source']['source'], 'database_cache')

    def test_as_of_date_falls_back_to_evaluation_provenance(self):
        regime_result = regime_payload(REGIME_BULLISH)
        regime_result['latest_market_date'] = None
        strategy_selection = select_strategy(regime_result)
        evaluation = completed_evaluation(STRATEGY_TREND_FOLLOWING)
        context = build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=evaluation,
        )
        self.assertEqual(context['as_of_date'], '2026-08-14')

    def test_as_of_date_is_null_when_no_module_has_one(self):
        regime_result = regime_payload(REGIME_BULLISH)
        regime_result['latest_market_date'] = None
        strategy_selection = select_strategy(regime_result)
        evaluation = not_applicable_evaluation()
        evaluation['market_regime_latest_market_date'] = None
        context = build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=evaluation,
        )
        self.assertIsNone(context['as_of_date'])


class AgentContextRegimeTests(SimpleTestCase):
    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)

    def run_context(self, regime, evaluation):
        regime_result = regime_payload(regime)
        with (
            patch(
                'agent.agent_context_service.get_market_regime',
                return_value=regime_result,
            ) as get_regime,
            patch(
                'agent.agent_context_service.select_strategy',
                wraps=select_strategy,
            ) as select_mock,
            patch(
                'agent.agent_context_service.evaluate_selected_strategy',
                return_value=evaluation,
            ) as evaluate_mock,
        ):
            context = build_agent_context(self.security, benchmark=self.benchmark)
        return context, get_regime, select_mock, evaluate_mock

    def test_bullish_trend_selects_trend_following(self):
        context, get_regime, select_mock, evaluate_mock = self.run_context(
            REGIME_BULLISH,
            completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        self.assertEqual(context['market_regime']['regime'], REGIME_BULLISH)
        self.assertEqual(
            context['strategy_selection']['selected_strategy'],
            STRATEGY_TREND_FOLLOWING,
        )
        self.assertTrue(context['strategy_selection']['allow_new_long'])
        self.assertFalse(context['strategy_selection']['risk_off'])
        self.assertTrue(context['strategy_evaluation']['available'])
        self.assertEqual(context['data_quality']['all_modules_available'], True)
        get_regime.assert_called_once_with(self.security)
        evaluate_mock.assert_called_once()
        kwargs = evaluate_mock.call_args.kwargs
        self.assertEqual(kwargs['market_regime_result']['regime'], REGIME_BULLISH)
        self.assertEqual(
            kwargs['strategy_selection_result']['selected_strategy'],
            STRATEGY_TREND_FOLLOWING,
        )

    def test_bearish_trend_stays_trend_following_with_long_constraint(self):
        context, *_ = self.run_context(
            REGIME_BEARISH,
            completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        self.assertEqual(context['market_regime']['regime'], REGIME_BEARISH)
        self.assertEqual(
            context['strategy_selection']['selected_strategy'],
            STRATEGY_TREND_FOLLOWING,
        )
        self.assertNotEqual(
            context['strategy_selection']['selected_strategy'],
            STRATEGY_RISK_OFF,
        )
        self.assertFalse(context['strategy_selection']['allow_new_long'])
        self.assertFalse(context['strategy_selection']['risk_off'])
        self.assertTrue(context['strategy_evaluation']['available'])

    def test_sideways_range_selects_mean_reversion(self):
        context, *_ = self.run_context(
            REGIME_SIDEWAYS,
            completed_evaluation(STRATEGY_MEAN_REVERSION),
        )
        self.assertEqual(context['market_regime']['regime'], REGIME_SIDEWAYS)
        self.assertEqual(
            context['strategy_selection']['selected_strategy'],
            STRATEGY_MEAN_REVERSION,
        )
        self.assertTrue(context['strategy_selection']['allow_new_long'])
        self.assertEqual(
            context['strategy_evaluation']['evaluation_strategy'],
            STRATEGY_MEAN_REVERSION,
        )

    def test_high_volatility_selects_risk_off_without_degrading_context(self):
        context, *_ = self.run_context(
            REGIME_HIGH_VOLATILITY,
            not_applicable_evaluation(),
        )
        self.assertEqual(context['market_regime']['regime'], REGIME_HIGH_VOLATILITY)
        self.assertEqual(
            context['strategy_selection']['selected_strategy'],
            STRATEGY_RISK_OFF,
        )
        self.assertEqual(context['strategy_selection']['strategy_mode'], 'defensive')
        self.assertFalse(context['strategy_selection']['allow_new_long'])
        self.assertTrue(context['strategy_selection']['risk_off'])
        self.assertFalse(context['strategy_evaluation']['available'])
        self.assertEqual(
            context['strategy_evaluation']['status'],
            'not_applicable',
        )
        self.assertEqual(context['data_quality']['all_modules_available'], True)
        self.assertEqual(context['data_quality']['degraded_modules'], [])

    def test_high_volatility_keeps_not_applicable_out_of_degraded_modules(self):
        context, *_ = self.run_context(
            REGIME_HIGH_VOLATILITY,
            not_applicable_evaluation(),
        )
        self.assertNotIn('strategy_evaluation', context['data_quality']['degraded_modules'])
        self.assertEqual(
            context['data_quality']['modules']['strategy_evaluation']['status'],
            'not_applicable',
        )
        self.assertTrue(context['data_quality']['modules']['strategy_evaluation']['available'] is False)


class AgentContextAvailabilityTests(SimpleTestCase):
    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)

    def test_broad_market_unavailable_keeps_reason_and_downgrades_context(self):
        regime_result = regime_payload(
            REGIME_BULLISH,
            broad_available=False,
        )
        strategy_selection = select_strategy(regime_result)
        context = build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        market_context = context['market_context']
        self.assertFalse(market_context['broad_market_available'])
        self.assertEqual(
            market_context['broad_market_reason'],
            'benchmark_market_data_unavailable',
        )
        self.assertIsNone(market_context['spy_regime'])
        self.assertIn('market_context', context['data_quality']['degraded_modules'])
        self.assertFalse(context['data_quality']['all_modules_available'])

    def test_sector_unavailable_never_fabricates_sector_regime(self):
        regime_result = regime_payload(
            REGIME_BULLISH,
            sector_available=False,
        )
        strategy_selection = select_strategy(regime_result)
        context = build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=completed_evaluation(STRATEGY_TREND_FOLLOWING),
        )
        market_context = context['market_context']
        self.assertFalse(market_context['sector_available'])
        self.assertEqual(
            market_context['sector_reason'],
            'sector_metadata_unavailable',
        )
        self.assertIsNone(market_context['sector_regime'])
        self.assertIn('market_context', context['data_quality']['degraded_modules'])

    def test_unavailable_evaluation_is_degraded_but_regime_context_remains(self):
        regime_result = regime_payload(REGIME_BULLISH, available=False)
        strategy_selection = select_strategy(regime_result)
        context = build_agent_context_from_parts(
            security=self.security,
            market_regime_result=regime_result,
            strategy_selection=strategy_selection,
            evaluation_result=unavailable_evaluation(),
        )
        self.assertFalse(context['market_regime']['available'])
        self.assertEqual(
            context['market_regime']['unavailable_reason'],
            'insufficient_history',
        )
        self.assertFalse(context['strategy_selection']['available'])
        self.assertEqual(context['strategy_evaluation']['status'], 'unavailable')
        for module in ('market_regime', 'market_context', 'strategy_selection', 'strategy_evaluation'):
            self.assertIn(module, context['data_quality']['degraded_modules'])
        self.assertFalse(context['data_quality']['all_modules_available'])
        assert_no_large_arrays(context)


class AgentContextComputationTests(SimpleTestCase):
    def setUp(self):
        self.security = fake_security('AAPL', 1)
        self.benchmark = fake_security('SPY', 2)
        self.registry = {
            STRATEGY_TREND_FOLLOWING: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_TREND_FOLLOWING,
                evaluator=Mock(return_value=completed_evaluation(STRATEGY_TREND_FOLLOWING)),
                active_backtest=True,
            ),
            STRATEGY_MEAN_REVERSION: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_MEAN_REVERSION,
                evaluator=Mock(return_value=completed_evaluation(STRATEGY_MEAN_REVERSION)),
                active_backtest=True,
            ),
            STRATEGY_RISK_OFF: StrategyEvaluatorRegistration(
                strategy_id=STRATEGY_RISK_OFF,
                evaluator=None,
                active_backtest=False,
            ),
        }

    def test_build_agent_context_calls_market_regime_only_once(self):
        regime_result = regime_payload(REGIME_BULLISH)
        with (
            patch(
                'agent.agent_context_service.get_market_regime',
                return_value=regime_result,
            ) as context_get_regime,
            patch(
                'agent.agent_context_service.select_strategy',
                wraps=select_strategy,
            ) as context_select_strategy,
            patch(
                'backtest.strategy_evaluation_service.get_market_regime',
            ) as evaluation_get_regime,
            patch(
                'backtest.strategy_evaluation_service.select_strategy',
            ) as evaluation_select_strategy,
            patch.dict(
                STRATEGY_EVALUATOR_REGISTRY,
                self.registry,
                clear=True,
            ),
        ):
            context = build_agent_context(self.security, benchmark=self.benchmark)

        self.assertEqual(context['market_regime']['regime'], REGIME_BULLISH)
        context_get_regime.assert_called_once_with(self.security)
        self.assertEqual(context_select_strategy.call_count, 1)
        evaluation_get_regime.assert_not_called()
        evaluation_select_strategy.assert_not_called()
        self.registry[STRATEGY_TREND_FOLLOWING].evaluator.assert_called_once()
        self.assertTrue(context['strategy_evaluation']['available'])

    def test_evaluate_selected_strategy_without_precomputed_results_keeps_old_behavior(self):
        regime_result = regime_payload(REGIME_BULLISH)
        with (
            patch(
                'backtest.strategy_evaluation_service.get_market_regime',
                return_value=regime_result,
            ) as get_regime,
            patch(
                'backtest.strategy_evaluation_service.select_strategy',
                wraps=select_strategy,
            ) as select_mock,
            patch.dict(
                STRATEGY_EVALUATOR_REGISTRY,
                self.registry,
                clear=True,
            ),
        ):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
            )

        self.assertTrue(result['evaluation_available'])
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        get_regime.assert_called_once_with(self.security)
        self.assertEqual(select_mock.call_count, 1)

    def test_evaluate_selected_strategy_reuses_precomputed_results(self):
        regime_result = regime_payload(REGIME_BULLISH)
        strategy_selection = select_strategy(regime_result)
        with (
            patch(
                'backtest.strategy_evaluation_service.get_market_regime',
            ) as get_regime,
            patch(
                'backtest.strategy_evaluation_service.select_strategy',
            ) as select_mock,
            patch.dict(
                STRATEGY_EVALUATOR_REGISTRY,
                self.registry,
                clear=True,
            ),
        ):
            result = evaluate_selected_strategy(
                security=self.security,
                benchmark=self.benchmark,
                market_regime_result=regime_result,
                strategy_selection_result=strategy_selection,
            )

        self.assertTrue(result['evaluation_available'])
        self.assertEqual(result['selected_strategy'], STRATEGY_TREND_FOLLOWING)
        get_regime.assert_not_called()
        select_mock.assert_not_called()
