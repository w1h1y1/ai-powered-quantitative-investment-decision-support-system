from rest_framework import serializers

from .models import Security, SecurityDailyPrice


class SecuritySerializer(serializers.ModelSerializer):
    class Meta:
        model = Security
        fields = [
            'id',
            'symbol',
            'name',
            'asset_type',
            'exchange',
            'mic_code',
            'country',
            'currency',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class SecuritySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Security
        fields = ['id', 'symbol', 'name', 'asset_type', 'exchange', 'mic_code', 'country', 'currency']
        read_only_fields = fields


class SecurityDailyPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityDailyPrice
        fields = [
            'date',
            'open',
            'high',
            'low',
            'close',
            'volume',
        ]
        read_only_fields = fields


class SecurityMarketDataBarSerializer(serializers.Serializer):
    date = serializers.SerializerMethodField()
    open = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)
    high = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)
    low = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)
    close = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)
    volume = serializers.IntegerField(read_only=True)

    def get_date(self, obj):
        timestamp = getattr(obj, 'timestamp', '')
        if timestamp:
            return timestamp

        value = getattr(obj, 'date', '')
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)
