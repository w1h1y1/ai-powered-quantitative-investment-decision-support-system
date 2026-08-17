from rest_framework import serializers

from market.models import Security
from market.serializers import SecuritySelectionSerializer
from market.services import SecuritySelectionValidationError, resolve_security_selection


class PredictionGenerateSerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=16, trim_whitespace=True)
    classification_forecast_horizon = serializers.ChoiceField(
        choices=(1, 5),
        required=False,
        default=1,
    )
    regression_forecast_horizon = serializers.ChoiceField(
        choices=(5, 10, 20),
        required=False,
        default=10,
    )
    # Temporary compatibility input. A single legacy horizon is unambiguous
    # only at 5 days because that is the sole value valid for both new fields.
    horizon = serializers.IntegerField(min_value=1, max_value=60, required=False)
    lookback = serializers.IntegerField(min_value=30, max_value=2000)
    security_selection = SecuritySelectionSerializer(required=False)

    def validate_symbol(self, value):
        normalized = value.strip().upper()
        if not normalized:
            raise serializers.ValidationError('Symbol is required.')
        return normalized

    def validate(self, attrs):
        initial_data = self.initial_data if isinstance(self.initial_data, dict) else {}
        new_horizon_present = (
            'classification_forecast_horizon' in initial_data
            or 'regression_forecast_horizon' in initial_data
        )
        legacy_horizon = attrs.pop('horizon', None)
        if legacy_horizon is not None and not new_horizon_present:
            if legacy_horizon != 5:
                raise serializers.ValidationError({
                    'horizon': (
                        'Legacy horizon is ambiguous. Send classification_forecast_horizon '
                        'and regression_forecast_horizon separately; only legacy horizon=5 '
                        'can be applied to both targets.'
                    ),
                })
            attrs['classification_forecast_horizon'] = 5
            attrs['regression_forecast_horizon'] = 5

        symbol = attrs['symbol']
        selection = attrs.get('security_selection')

        if selection:
            selection_symbol = str(selection.get('symbol', '')).strip().upper()
            if selection_symbol != symbol:
                raise serializers.ValidationError({
                    'security_selection': 'Selected security does not match the requested symbol.',
                })
            try:
                security, created, _verified_item = resolve_security_selection(selection)
            except SecuritySelectionValidationError as exc:
                raise serializers.ValidationError(exc.detail) from None
        else:
            security = (
                Security.objects
                .filter(symbol=symbol, is_active=True)
                .order_by('-country', 'mic_code', 'exchange', 'id')
                .first()
            )
            created = False
            if security is None:
                try:
                    security, created, _verified_item = resolve_security_selection({
                        'symbol': symbol,
                        'search_query': symbol,
                    })
                except SecuritySelectionValidationError as exc:
                    raise serializers.ValidationError(exc.detail) from None

        attrs['security_obj'] = security
        attrs['security_created'] = created
        return attrs
