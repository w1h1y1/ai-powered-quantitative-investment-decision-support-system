from rest_framework import serializers

from market.models import Security


class AgentContextQuerySerializer(serializers.Serializer):
    """Public input for the deterministic Agent Context endpoint."""

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
        self._resolved_security = security
        return attrs

    @property
    def resolved_security(self):
        if self._resolved_security is None:
            raise AssertionError(
                'Call is_valid(raise_exception=True) before accessing resolved_security.'
            )
        return self._resolved_security
