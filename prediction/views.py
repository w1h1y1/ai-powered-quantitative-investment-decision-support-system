from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import PredictionGenerateSerializer
from .services import (
    PredictionMarketDataRateLimited,
    PredictionMarketDataUnavailable,
    generate_prediction_market_data,
)


class PredictionGenerateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PredictionGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payload = generate_prediction_market_data(
                security=data['security_obj'],
                classification_forecast_horizon=data['classification_forecast_horizon'],
                regression_forecast_horizon=data['regression_forecast_horizon'],
                lookback=data['lookback'],
            )
        except PredictionMarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except PredictionMarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        payload['security_resolution'] = {
            'created': data['security_created'],
            'source': 'remote_selection' if data.get('security_selection') else 'local_security',
        }
        return Response(payload)
