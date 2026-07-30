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
            'currency',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class SecuritySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Security
        fields = ['id', 'symbol', 'name', 'asset_type', 'currency']
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
