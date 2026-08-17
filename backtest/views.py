from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from market.services import MarketDataRateLimited, MarketDataUnavailable
from market.regime_service import (
    MarketRegimeDataRateLimited,
    MarketRegimeDataUnavailable,
)

from .serializers import BacktestRunSerializer, StrategyEvaluationSerializer
from .services import (
    BacktestDataError,
    BacktestInsufficientHistoryError,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
    StrategyParameters,
    run_market_regime_core_swing_backtest,
)
from .strategy_evaluation_service import evaluate_selected_strategy


class BacktestRunView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BacktestRunSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            payload = run_market_regime_core_swing_backtest(
                security=data['security_obj'],
                benchmark=data['benchmark_obj'],
                start_date=data['start_date'],
                end_date=data['end_date'],
                initial_capital=data['initial_capital'],
                transaction_fee=data['transaction_fee'],
                parameters=StrategyParameters(
                    core_fast_ma=data['core_fast_ma'],
                    core_slow_ma=data['core_slow_ma'],
                    core_risk_percentage=data['core_risk_fraction'],
                    core_atr_multiplier=data['core_atr_multiplier'],
                    max_core_exposure=data['max_core_exposure'],
                    core_reduce_fraction=data['core_reduce_fraction'],
                    swing_risk_percentage=data['swing_risk_fraction'],
                    swing_atr_multiplier=data['swing_atr_multiplier'],
                    swing_rsi_lookback=data['swing_rsi_lookback'],
                    swing_rsi_entry_level=data['swing_rsi_entry_level'],
                    swing_rsi_exit_level=data['swing_rsi_exit_level'],
                    swing_average_type=data['swing_trend_average'],
                ),
            )
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except BacktestMarketDataRateLimited as exc:
            return Response({'detail': str(exc), **exc.details}, status=429)
        except BacktestMarketDataUnavailable as exc:
            return Response({'detail': str(exc), **exc.details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        payload['security_resolution'] = {
            'created': data.get('security_created', False),
            'source': 'remote_selection' if data.get('security_selection') else 'local_security',
        }

        return Response(payload)


class StrategyEvaluationView(APIView):
    """Evaluate the strategy chosen by the server-side selection pipeline."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = StrategyEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payload = evaluate_selected_strategy(
                security=data['security_obj'],
                benchmark=data['benchmark_obj'],
                start_date=data.get('start_date'),
                end_date=data.get('end_date'),
                initial_capital=data['initial_capital'],
                transaction_fee=data['transaction_fee'],
            )
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except (MarketRegimeDataRateLimited, BacktestMarketDataRateLimited) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=429)
        except (MarketRegimeDataUnavailable, BacktestMarketDataUnavailable) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(payload)
