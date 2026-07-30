from rest_framework import permissions, viewsets

from .models import Watchlist, WatchlistItem
from .serializers import WatchlistItemSerializer, WatchlistSerializer
from .services import get_or_create_primary_watchlist


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
