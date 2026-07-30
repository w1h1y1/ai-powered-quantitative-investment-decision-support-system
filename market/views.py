from rest_framework import filters, permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Security
from .serializers import SecurityDailyPriceSerializer, SecuritySerializer
from .services import (
    InvalidMarketDataDateRange,
    MarketDataUnavailable,
    UnsupportedMarketDataRange,
    UnsupportedMarketDataSecurity,
    get_security_daily_market_data,
)


class SecurityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Security.objects.all()
    serializer_class = SecuritySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['symbol', 'name', 'exchange']
    ordering_fields = ['symbol', 'name']
    ordering = ['symbol']


class SecurityDailyMarketDataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_security(self, request):
        security_id = request.query_params.get('security')
        if not security_id:
            return None, Response({'security': 'Security is required.'}, status=400)

        try:
            security = Security.objects.get(pk=security_id, is_active=True)
        except (Security.DoesNotExist, ValueError):
            return None, Response({'security': 'Security is not available.'}, status=404)

        return security, None

    def get(self, request):
        security, error_response = self.get_security(request)
        if error_response is not None:
            return error_response

        range_key = request.query_params.get('range')
        try:
            result = get_security_daily_market_data(
                security,
                range_key=range_key,
                start_date=request.query_params.get('start_date'),
                end_date=request.query_params.get('end_date'),
            )
        except UnsupportedMarketDataRange as exc:
            return Response({'range': str(exc)}, status=400)
        except InvalidMarketDataDateRange as exc:
            return Response(exc.errors, status=400)
        except UnsupportedMarketDataSecurity as exc:
            return Response({'security': str(exc)}, status=400)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response({
            'security': SecuritySerializer(result.security).data,
            'range': result.range_key,
            'source': result.source,
            'is_stale': result.is_stale,
            'values': SecurityDailyPriceSerializer(result.values, many=True).data,
        })
