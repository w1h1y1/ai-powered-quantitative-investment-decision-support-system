from rest_framework import serializers

from market.models import Security
from market.serializers import SecuritySelectionSerializer, SecuritySummarySerializer

from .models import Watchlist, WatchlistItem


class UserWatchlistRelatedField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return Watchlist.objects.none()
        return Watchlist.objects.filter(user=request.user)


class WatchlistItemNestedSerializer(serializers.ModelSerializer):
    security = SecuritySummarySerializer(read_only=True)

    class Meta:
        model = WatchlistItem
        fields = ['id', 'security', 'added_at']
        read_only_fields = fields


class WatchlistSerializer(serializers.ModelSerializer):
    items = WatchlistItemNestedSerializer(many=True, read_only=True)

    class Meta:
        model = Watchlist
        fields = ['id', 'name', 'items', 'created_at', 'updated_at']
        read_only_fields = ['id', 'items', 'created_at', 'updated_at']


class WatchlistItemSerializer(serializers.ModelSerializer):
    watchlist = UserWatchlistRelatedField()
    security = SecuritySummarySerializer(read_only=True)
    security_id = serializers.PrimaryKeyRelatedField(
        source='security',
        queryset=Security.objects.all(),
        write_only=True,
    )

    def validate(self, attrs):
        watchlist = attrs.get('watchlist') or getattr(self.instance, 'watchlist', None)
        security = attrs.get('security') or getattr(self.instance, 'security', None)

        if watchlist and security:
            duplicate_items = WatchlistItem.objects.filter(
                watchlist=watchlist,
                security=security,
            )
            if self.instance:
                duplicate_items = duplicate_items.exclude(pk=self.instance.pk)

            if duplicate_items.exists():
                raise serializers.ValidationError({
                    'security_id': 'This security is already in this watchlist.'
                })

        return attrs

    class Meta:
        model = WatchlistItem
        fields = ['id', 'watchlist', 'security', 'security_id', 'added_at']
        read_only_fields = ['id', 'security', 'added_at']
        validators = []


class WatchlistAddSymbolSerializer(SecuritySelectionSerializer):
    pass
