from decimal import Decimal

from rest_framework import serializers

from market.models import Security
from market.serializers import SecuritySelectionSerializer
from market.services import SecuritySelectionValidationError, resolve_security_selection


class StrategyEvaluationSerializer(serializers.Serializer):
    """Public inputs for server-selected historical strategy evaluation.

    Strategy and regime fields are deliberately not accepted.  The server
    resolves both through the formal Market Regime and Strategy Selection
    services so callers cannot choose an evaluator directly.
    """

    symbol = serializers.CharField(max_length=16, trim_whitespace=True)
    benchmark = serializers.CharField(
        required=False,
        default='SPY',
        allow_blank=False,
        max_length=16,
        trim_whitespace=True,
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    initial_capital = serializers.DecimalField(
        required=False,
        default=Decimal('10000'),
        max_digits=20,
        decimal_places=6,
        min_value=Decimal('0.000001'),
    )
    transaction_fee = serializers.DecimalField(
        required=False,
        default=Decimal('1.00'),
        max_digits=20,
        decimal_places=6,
        min_value=Decimal('0'),
    )

    def validate_symbol(self, value):
        normalized = value.strip().upper()
        if not normalized:
            raise serializers.ValidationError('Symbol is required.')
        return normalized

    def validate_benchmark(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        for server_owned_field in ('selected_strategy', 'market_regime'):
            if server_owned_field in self.initial_data:
                raise serializers.ValidationError({
                    server_owned_field: (
                        f'{server_owned_field} is determined by the server and must not be supplied.'
                    ),
                })

        has_start = 'start_date' in attrs
        has_end = 'end_date' in attrs
        if has_start != has_end:
            raise serializers.ValidationError({
                'start_date': 'start_date and end_date must be supplied together.',
                'end_date': 'start_date and end_date must be supplied together.',
            })
        if has_start and attrs['start_date'] >= attrs['end_date']:
            raise serializers.ValidationError({
                'start_date': 'Start date must be earlier than end date.',
            })

        security = (
            Security.objects
            .filter(symbol=attrs['symbol'], is_active=True)
            .order_by('-country', 'mic_code', 'exchange', 'id')
            .first()
        )
        if security is None:
            raise serializers.ValidationError({'symbol': 'Security is not available.'})

        benchmark = (
            Security.objects
            .filter(symbol=attrs['benchmark'], is_active=True)
            .order_by('-country', 'mic_code', 'exchange', 'id')
            .first()
        )
        if benchmark is None:
            raise serializers.ValidationError({
                'benchmark': 'Benchmark security must exist in the system.',
            })

        attrs['security_obj'] = security
        attrs['benchmark_obj'] = benchmark
        return attrs


class BacktestRunSerializer(serializers.Serializer):
    security = serializers.IntegerField(required=False)
    symbol = serializers.CharField(required=False, allow_blank=False, max_length=16)
    security_selection = SecuritySelectionSerializer(required=False)
    benchmark = serializers.CharField(required=False, default='SPY', allow_blank=False, max_length=16)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0.000001'))
    transaction_fee = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0'))
    core_fast_ma = serializers.IntegerField(required=False, default=20, min_value=1)
    core_slow_ma = serializers.IntegerField(required=False, default=60, min_value=1)
    core_risk_fraction = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.001'),
        max_value=Decimal('0.05'),
        error_messages={
            'min_value': 'Core Risk must be between 0.1%% and 5%%.',
            'max_value': 'Core Risk must be between 0.1%% and 5%%.',
        },
    )
    core_risk_percentage = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.001'),
        max_value=Decimal('0.05'),
        error_messages={
            'min_value': 'Core Risk must be between 0.1%% and 5%%.',
            'max_value': 'Core Risk must be between 0.1%% and 5%%.',
        },
    )
    core_atr_multiplier = serializers.DecimalField(
        required=False,
        default=Decimal('2.5'),
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.5'),
        max_value=Decimal('8.0'),
        error_messages={
            'min_value': 'Core ATR Multiplier must be between 0.5 and 8.0.',
            'max_value': 'Core ATR Multiplier must be between 0.5 and 8.0.',
        },
    )
    max_core_exposure = serializers.DecimalField(
        required=False,
        default=Decimal('0.80'),
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.10'),
        max_value=Decimal('1'),
        error_messages={
            'min_value': 'Max Core Exposure must be between 10%% and 100%%.',
            'max_value': 'Max Core Exposure must be between 10%% and 100%%.',
        },
    )
    core_reduce_fraction = serializers.DecimalField(
        required=False,
        default=Decimal('0.25'),
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.05'),
        max_value=Decimal('0.90'),
        error_messages={
            'min_value': 'Core Reduce Fraction must be between 5%% and 90%%.',
            'max_value': 'Core Reduce Fraction must be between 5%% and 90%%.',
        },
    )
    swing_risk_fraction = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.001'),
        max_value=Decimal('0.02'),
        error_messages={
            'min_value': 'Swing Risk must be between 0.1%% and 2%%.',
            'max_value': 'Swing Risk must be between 0.1%% and 2%%.',
        },
    )
    swing_risk_percentage = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.001'),
        max_value=Decimal('0.02'),
        error_messages={
            'min_value': 'Swing Risk must be between 0.1%% and 2%%.',
            'max_value': 'Swing Risk must be between 0.1%% and 2%%.',
        },
    )
    swing_atr_multiplier = serializers.DecimalField(
        required=False,
        default=Decimal('1.5'),
        max_digits=8,
        decimal_places=6,
        min_value=Decimal('0.5'),
        max_value=Decimal('5.0'),
        error_messages={
            'min_value': 'Swing ATR Multiplier must be between 0.5 and 5.0.',
            'max_value': 'Swing ATR Multiplier must be between 0.5 and 5.0.',
        },
    )
    swing_rsi_lookback = serializers.IntegerField(required=False, default=10, min_value=1, max_value=60)
    swing_rsi_entry_level = serializers.DecimalField(
        required=False,
        default=Decimal('45'),
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('1'),
        max_value=Decimal('99'),
    )
    swing_rsi_exit_level = serializers.DecimalField(
        required=False,
        default=Decimal('60'),
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('1'),
        max_value=Decimal('99'),
    )
    swing_trend_average = serializers.ChoiceField(required=False, choices=('EMA10', 'SMA10'))
    swing_average_type = serializers.ChoiceField(required=False, choices=('EMA10', 'SMA10'))

    def validate(self, attrs):
        core_risk_fraction = attrs.pop('core_risk_percentage', None)
        requested_core_risk = attrs.get('core_risk_fraction')
        if requested_core_risk is not None and core_risk_fraction is not None and requested_core_risk != core_risk_fraction:
            raise serializers.ValidationError({'core_risk_fraction': 'Submit only one Core Risk value.'})
        attrs['core_risk_fraction'] = requested_core_risk or core_risk_fraction or Decimal('0.02')

        swing_risk_fraction = attrs.pop('swing_risk_percentage', None)
        requested_swing_risk = attrs.get('swing_risk_fraction')
        if requested_swing_risk is not None and swing_risk_fraction is not None and requested_swing_risk != swing_risk_fraction:
            raise serializers.ValidationError({'swing_risk_fraction': 'Submit only one Swing Risk value.'})
        attrs['swing_risk_fraction'] = requested_swing_risk or swing_risk_fraction or Decimal('0.01')

        legacy_swing_average = attrs.pop('swing_average_type', None)
        requested_swing_average = attrs.get('swing_trend_average')
        if (
            requested_swing_average is not None
            and legacy_swing_average is not None
            and requested_swing_average != legacy_swing_average
        ):
            raise serializers.ValidationError({
                'swing_trend_average': 'Submit only one Swing Trend Average value.',
            })
        attrs['swing_trend_average'] = requested_swing_average or legacy_swing_average or 'EMA10'

        if attrs['swing_rsi_entry_level'] >= attrs['swing_rsi_exit_level']:
            raise serializers.ValidationError({
                'swing_rsi_entry_level': 'Swing RSI Entry Level must be lower than Swing RSI Exit Level.',
            })

        security_id = attrs.get('security')
        symbol = str(attrs.get('symbol', '')).strip().upper()
        security_selection = attrs.get('security_selection')
        if not security_id and not symbol and not security_selection:
            raise serializers.ValidationError({'security': 'Security or symbol is required.'})

        if attrs['start_date'] >= attrs['end_date']:
            raise serializers.ValidationError({'start_date': 'Start date must be earlier than end date.'})

        if attrs['core_fast_ma'] >= attrs['core_slow_ma']:
            raise serializers.ValidationError({'core_fast_ma': 'Core fast MA must be smaller than Core slow MA.'})

        benchmark_symbol = str(attrs.get('benchmark', 'SPY')).strip().upper()
        benchmark = (
            Security.objects
            .filter(symbol=benchmark_symbol, is_active=True)
            .order_by('-country', 'mic_code', 'exchange', 'id')
            .first()
        )
        if benchmark is None:
            raise serializers.ValidationError({
                'benchmark': 'Benchmark security must exist in the system.',
            })

        if security_selection:
            selection_symbol = str(security_selection.get('symbol', '')).strip().upper()
            selection_id = security_selection.get('id')
            if symbol and selection_symbol != symbol:
                raise serializers.ValidationError({
                    'security_selection': 'Selected security does not match the requested symbol.',
                })
            if security_id and selection_id and security_id != selection_id:
                raise serializers.ValidationError({
                    'security_selection': 'Selected security does not match the requested security id.',
                })
            try:
                security, security_created, _verified_item = resolve_security_selection(security_selection)
            except SecuritySelectionValidationError as exc:
                raise serializers.ValidationError(exc.detail) from None
            attrs['security_created'] = security_created
        else:
            try:
                if security_id:
                    security = Security.objects.get(pk=security_id, is_active=True)
                else:
                    matches = Security.objects.filter(symbol=symbol, is_active=True).order_by(
                        '-country',
                        'symbol',
                        'mic_code',
                        'exchange',
                    )
                    security = matches.first()
                    if security is None:
                        raise Security.DoesNotExist
            except (Security.DoesNotExist, ValueError):
                raise serializers.ValidationError({'security': 'Security must exist in the system.'}) from None
            attrs['security_created'] = False

        attrs['security_obj'] = security
        attrs['benchmark_obj'] = benchmark
        attrs['symbol'] = security.symbol
        attrs['benchmark'] = benchmark.symbol
        return attrs
