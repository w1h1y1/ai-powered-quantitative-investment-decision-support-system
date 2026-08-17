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


class SecuritySelectionSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    symbol = serializers.CharField(max_length=16, trim_whitespace=True)
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=True)
    exchange = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    mic_code = serializers.CharField(max_length=16, required=False, allow_blank=True, trim_whitespace=True)
    instrument_type = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    country = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, trim_whitespace=True)
    search_query = serializers.CharField(max_length=255, required=False, allow_blank=True, trim_whitespace=True)

    def validate_symbol(self, value):
        normalized = value.strip().upper()
        if not normalized:
            raise serializers.ValidationError('Symbol is required.')
        return normalized

    def validate_mic_code(self, value):
        return value.strip().upper()

    def validate_currency(self, value):
        return (value.strip() or 'USD').upper()


class MarketRegimeQuerySerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=16, trim_whitespace=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._resolved_security = None

    def validate_symbol(self, value):
        normalized = value.strip().upper()
        if not normalized:
            raise serializers.ValidationError('Symbol is required.')
        return normalized

    def validate(self, attrs):
        security = (
            Security.objects
            .filter(symbol=attrs['symbol'], is_active=True)
            .order_by('-country', 'mic_code', 'exchange', 'id')
            .first()
        )
        if security is None:
            raise serializers.ValidationError({'symbol': 'Security is not available.'})
        # Keep normalized request data and the resolved model object as two
        # explicit contracts. The View must not depend on an undeclared
        # ``validated_data['security']`` key.
        self._resolved_security = security
        return attrs

    @property
    def resolved_security(self):
        if self._resolved_security is None:
            raise AssertionError(
                'Call is_valid(raise_exception=True) before accessing resolved_security.'
            )
        return self._resolved_security


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
