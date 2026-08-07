from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import BacktestRunSerializer
from .services import (
    BacktestDataError,
    BacktestInsufficientHistoryError,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
    StrategyParameters,
    run_market_regime_core_swing_backtest,
)


class BacktestRunView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BacktestRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
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
                    swing_risk_percentage=data['swing_risk_fraction'],
                    swing_atr_multiplier=data['swing_atr_multiplier'],
                    swing_rsi_lookback=data['swing_rsi_lookback'],
                    swing_rsi_entry_level=data['swing_rsi_entry_level'],
                    swing_rsi_exit_level=data['swing_rsi_exit_level'],
                    swing_cooldown_days=data['swing_cooldown_days'],
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

        return Response(payload)
