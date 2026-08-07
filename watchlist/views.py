from rest_framework import permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from market.services import MarketDataRateLimited, MarketDataUnavailable

from .models import Watchlist, WatchlistItem
from .serializers import WatchlistAddSymbolSerializer, WatchlistItemSerializer, WatchlistSerializer
from .services import (
    WatchlistSymbolValidationError,
    add_symbol_to_watchlist,
    get_or_create_primary_watchlist,
    get_watchlist_summary,
)


class WatchlistViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Watchlist.objects
            .filter(user=self.request.user)
            .prefetch_related('items__security')
            .order_by('created_at', 'id')
        )

    def list(self, request, *args, **kwargs):
        get_or_create_primary_watchlist(request.user)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WatchlistItemViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            WatchlistItem.objects
            .select_related('watchlist', 'security')
            .filter(watchlist__user=self.request.user)
            .order_by('-added_at')
        )

        watchlist_id = self.request.query_params.get('watchlist')
        if watchlist_id:
            queryset = queryset.filter(watchlist_id=watchlist_id)

        return queryset


def parse_refresh_flag(request):
    return str(request.query_params.get('refresh', '')).lower() in {'1', 'true', 'yes', 'on'}


class WatchlistSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(get_watchlist_summary(request.user, force_refresh=parse_refresh_flag(request)))


class WatchlistAddSymbolView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = WatchlistAddSymbolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = add_symbol_to_watchlist(request.user, serializer.validated_data)
        except WatchlistSymbolValidationError as exc:
            return Response(exc.detail, status=400)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(result, status=201 if result['created_item'] else 200)
