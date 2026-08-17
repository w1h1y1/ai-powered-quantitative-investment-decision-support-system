import logging

from django.conf import settings
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Security
from .regime_config import (
    BROAD_MARKET_SYMBOL,
    get_backtest_benchmark_options,
    get_sector_benchmark,
    get_security_sector,
)
from .regime_service import (
    MarketRegimeDataRateLimited,
    MarketRegimeDataUnavailable,
    get_market_regime,
)
from .serializers import (
    MarketRegimeQuerySerializer,
    SecurityMarketDataBarSerializer,
    SecuritySelectionSerializer,
    SecuritySerializer,
)
from .strategy_selection_service import select_strategy
from .services import (
    MARKET_DATA_MAX_BATCH_QUOTES,
    MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
    InvalidMarketDataDateRange,
    MarketDataInvalidSymbol,
    MarketDataRateLimited,
    MarketDataUnavailable,
    SecuritySelectionValidationError,
    UnsupportedMarketDataInterval,
    UnsupportedMarketDataRange,
    UnsupportedMarketDataSecurity,
    get_market_summary,
    get_security_daily_market_data,
    get_security_latest_quote,
    get_security_latest_quotes,
    resolve_security_selection,
    search_security_symbols,
)


logger = logging.getLogger(__name__)


class SecurityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Security.objects.all()
    serializer_class = SecuritySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['symbol', 'name', 'exchange']
    ordering_fields = ['symbol', 'name']
    ordering = ['symbol']

    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        try:
            return Response(search_security_symbols(
                request.query_params.get('q', ''),
                force_refresh=parse_refresh_flag(request),
            ))
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

    @action(detail=False, methods=['post'], url_path='resolve')
    def resolve(self, request):
        serializer = SecuritySelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            security, created, _verified_item = resolve_security_selection(serializer.validated_data)
        except SecuritySelectionValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {
                'security': SecuritySerializer(security).data,
                'created': created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=['get'], url_path='sector-context')
    def sector_context(self, request, pk=None):
        security = self.get_object()
        sector, sector_source = get_security_sector(security)
        sector_benchmark = get_sector_benchmark(sector)
        return Response({
            'symbol': security.symbol,
            'sector': sector,
            'sector_source': sector_source,
            'sector_benchmark': sector_benchmark,
            'broad_market': BROAD_MARKET_SYMBOL,
            'allowed_benchmarks': get_backtest_benchmark_options(security),
        })


class MarketDataSecurityMixin:
    def get_security(self, request):
        security_id = request.query_params.get('security') or request.query_params.get('security_id')
        if not security_id:
            return None, Response({'security': 'Security is required.'}, status=400)

        try:
            security = Security.objects.get(pk=security_id, is_active=True)
        except (Security.DoesNotExist, ValueError):
            return None, Response({'security': 'Security is not available.'}, status=404)

        return security, None


def format_decimal(value):
    return f'{value:.6f}'


def format_quote_decimal(result, value):
    if result.data_status == MARKET_DATA_QUOTE_STATUS_UNAVAILABLE:
        return None
    return format_decimal(value)


def serialize_quote_result(result):
    return {
        'security': SecuritySerializer(result.security).data,
        'source': result.source,
        'price': format_quote_decimal(result, result.price),
        'change': format_quote_decimal(result, result.change),
        'percent_change': format_quote_decimal(result, result.percent_change),
        'currency': result.currency,
        'as_of': result.as_of,
        'data_status': result.data_status,
        'cache_status': result.cache_status,
        'is_stale': result.is_stale,
        'error': result.error,
    }


def parse_refresh_flag(request):
    if not settings.DEBUG:
        return False
    return str(request.query_params.get('refresh', '')).lower() in {'1', 'true', 'yes', 'on'}


class SecurityLatestQuoteView(MarketDataSecurityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        security, error_response = self.get_security(request)
        if error_response is not None:
            return error_response

        try:
            result = get_security_latest_quote(security)
        except UnsupportedMarketDataSecurity as exc:
            return Response({'security': str(exc)}, status=400)
        except MarketDataInvalidSymbol as exc:
            return Response({'detail': str(exc)}, status=404)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(serialize_quote_result(result))


class SecurityLatestQuotesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_security_ids(self, request):
        raw_values = []
        raw_values.extend(request.query_params.getlist('security'))
        raw_values.extend(request.query_params.getlist('security_id'))

        for key in ('security_ids', 'securities'):
            value = request.query_params.get(key)
            if value:
                raw_values.extend(value.split(','))

        security_ids = []
        for value in raw_values:
            raw_value = str(value).strip()
            if not raw_value:
                continue
            try:
                security_ids.append(int(raw_value))
            except ValueError:
                return None, Response({'security_ids': 'Security ids must be integers.'}, status=400)

        deduped_ids = []
        seen_ids = set()
        for security_id in security_ids:
            if security_id in seen_ids:
                continue
            deduped_ids.append(security_id)
            seen_ids.add(security_id)

        if not deduped_ids:
            return None, Response({'security_ids': 'At least one security is required.'}, status=400)
        if len(deduped_ids) > MARKET_DATA_MAX_BATCH_QUOTES:
            return None, Response({
                'security_ids': f'At most {MARKET_DATA_MAX_BATCH_QUOTES} securities can be quoted at once.'
            }, status=400)

        return deduped_ids, None

    def get(self, request):
        security_ids, error_response = self.get_security_ids(request)
        if error_response is not None:
            return error_response

        securities_by_id = {
            security.id: security
            for security in Security.objects.filter(pk__in=security_ids, is_active=True)
        }
        missing_ids = [security_id for security_id in security_ids if security_id not in securities_by_id]
        securities = [securities_by_id[security_id] for security_id in security_ids if security_id in securities_by_id]
        if not securities:
            return Response({'security_ids': 'Securities are not available.'}, status=404)

        results = get_security_latest_quotes(securities, force_refresh=parse_refresh_flag(request))
        return Response({
            'items': [serialize_quote_result(result) for result in results],
            'metadata': {
                'requested_count': len(security_ids),
                'returned_count': len(results),
                'missing_security_ids': missing_ids,
            },
        })


class MarketSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(get_market_summary(force_refresh=parse_refresh_flag(request)))


class MarketRegimeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = MarketRegimeQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            payload = get_market_regime(serializer.resolved_security)
        except MarketRegimeDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketRegimeDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)
        return Response(payload)


class StrategySelectionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = MarketRegimeQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            market_regime_result = get_market_regime(serializer.resolved_security)
        except MarketRegimeDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketRegimeDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)
        return Response(select_strategy(market_regime_result))


class SecurityDailyMarketDataView(MarketDataSecurityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

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
                interval=request.query_params.get('interval'),
                force_refresh=parse_refresh_flag(request),
            )
        except UnsupportedMarketDataRange as exc:
            return Response({'range': str(exc)}, status=400)
        except UnsupportedMarketDataInterval as exc:
            return Response({'interval': str(exc)}, status=400)
        except InvalidMarketDataDateRange as exc:
            return Response(exc.errors, status=400)
        except UnsupportedMarketDataSecurity as exc:
            return Response({'security': str(exc)}, status=400)
        except MarketDataInvalidSymbol as exc:
            return Response({'detail': str(exc)}, status=404)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        values_data = SecurityMarketDataBarSerializer(result.values, many=True).data
        warmup_values_data = SecurityMarketDataBarSerializer(result.warmup_values, many=True).data
        metadata = {
            'security_id': result.security.id,
            'symbol': result.security.symbol,
            'requested_range': result.range_key,
            'interval': result.interval,
            'count': len(values_data),
            'record_count': len(values_data),
            'warmup_count': len(warmup_values_data),
            'first_datetime': values_data[0]['date'] if values_data else '',
            'last_datetime': values_data[-1]['date'] if values_data else '',
            'first_timestamp': values_data[0]['date'] if values_data else '',
            'last_timestamp': values_data[-1]['date'] if values_data else '',
            'data_source': result.data_source,
            'source': result.data_source,
            'cache_status': result.cache_status,
            'is_stale': result.is_stale,
            'last_updated': result.last_updated,
            'upstream_error': result.upstream_error,
            'fetched_at': result.fetched_at,
            'provider': result.provider_metadata,
            'session_close_adjustments': result.session_close_adjustments,
        }
        logger.info(
            'Market data API response symbol=%s range=%s interval=%s count=%s first=%s last=%s data_source=%s cache_status=%s is_stale=%s upstream_error=%s provider_last=%s returned_last=%s',
            metadata['symbol'],
            metadata['requested_range'],
            metadata['interval'],
            metadata['count'],
            metadata['first_datetime'],
            metadata['last_datetime'],
            metadata['data_source'],
            metadata['cache_status'],
            metadata['is_stale'],
            metadata['upstream_error'],
            (result.provider_metadata.get('time_series') or {}).get('last_timestamp', ''),
            metadata['last_datetime'],
        )

        return Response({
            'security': SecuritySerializer(result.security).data,
            'range': result.range_key,
            'interval': result.interval,
            'source': result.source,
            'data_source': result.data_source,
            'cache_status': result.cache_status,
            'is_stale': result.is_stale,
            'last_updated': result.last_updated,
            'upstream_error': result.upstream_error,
            'fetched_at': result.fetched_at,
            'metadata': metadata,
            'values': values_data,
            'warmup_values': warmup_values_data,
        })
