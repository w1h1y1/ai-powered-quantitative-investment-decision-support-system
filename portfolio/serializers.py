from decimal import Decimal

from rest_framework import serializers

from market.models import Security
from market.serializers import SecuritySummarySerializer

from .models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction


ZERO = Decimal('0')
SELL_FEE_EXCEEDS_GROSS_PROCEEDS_MESSAGE = 'Fee cannot exceed the gross proceeds of the sale.'


class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = [
            'id',
            'name',
            'description',
            'available_funds',
            'initial_balance',
            'base_currency',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'initial_balance', 'created_at', 'updated_at']


class PortfolioCashFlowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioCashFlow
        fields = [
            'id',
            'flow_type',
            'amount',
            'effective_date',
            'note',
            'is_estimated',
            'created_at',
        ]
        read_only_fields = ['id', 'is_estimated', 'created_at']


class UserPortfolioRelatedField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return Portfolio.objects.none()
        return Portfolio.objects.filter(user=request.user)


class HoldingSerializer(serializers.ModelSerializer):
    portfolio = serializers.PrimaryKeyRelatedField(read_only=True)
    security = SecuritySummarySerializer(read_only=True)
    security_id = serializers.PrimaryKeyRelatedField(
        source='security',
        queryset=Security.objects.all(),
        write_only=True,
    )

    def to_internal_value(self, data):
        data = data.copy()
        if 'security' in data and 'security_id' not in data:
            data['security_id'] = data.get('security')
            data.pop('security', None)
        if 'average_price' in data and 'average_cost' not in data:
            data['average_cost'] = data.get('average_price')
            data.pop('average_price', None)
        return super().to_internal_value(data)

    def validate(self, attrs):
        if 'portfolio' in self.initial_data:
            raise serializers.ValidationError({
                'portfolio': 'Portfolio is assigned from the authenticated user.'
            })
        return attrs

    class Meta:
        model = Holding
        fields = [
            'id',
            'portfolio',
            'security',
            'security_id',
            'quantity',
            'average_cost',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'portfolio', 'security', 'created_at', 'updated_at']


class TradeTransactionSerializer(serializers.ModelSerializer):
    REMOTE_SECURITY_FIELDS = (
        'symbol',
        'name',
        'exchange',
        'mic_code',
        'instrument_type',
        'country',
        'currency',
        'search_query',
    )

    portfolio = UserPortfolioRelatedField()
    security = SecuritySummarySerializer(read_only=True)
    security_id = serializers.PrimaryKeyRelatedField(
        source='security',
        queryset=Security.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    symbol = serializers.CharField(max_length=16, required=False, allow_blank=True, write_only=True)
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, write_only=True)
    exchange = serializers.CharField(max_length=64, required=False, allow_blank=True, write_only=True)
    mic_code = serializers.CharField(max_length=16, required=False, allow_blank=True, write_only=True)
    instrument_type = serializers.CharField(max_length=64, required=False, allow_blank=True, write_only=True)
    country = serializers.CharField(max_length=64, required=False, allow_blank=True, write_only=True)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, write_only=True)
    search_query = serializers.CharField(max_length=255, required=False, allow_blank=True, write_only=True)

    def to_internal_value(self, data):
        data = data.copy()
        if 'security' in data and 'security_id' not in data:
            data['security_id'] = data.get('security')
            data.pop('security', None)
        return super().to_internal_value(data)

    def get_value_for_validation(self, attrs, field_name):
        if field_name in attrs:
            return attrs[field_name]
        if self.instance is not None:
            return getattr(self.instance, field_name)
        return None

    def validate_positive_field(self, errors, field_name, value, message):
        if value is None or value <= 0:
            errors[field_name] = message

    def has_remote_security_submission(self, attrs):
        return any(str(attrs.get(field_name) or '').strip() for field_name in self.REMOTE_SECURITY_FIELDS)

    def get_security_submission(self):
        return {
            field_name: self.validated_data.get(field_name)
            for field_name in self.REMOTE_SECURITY_FIELDS
            if field_name in self.validated_data
        }

    def pop_security_submission(self):
        for field_name in self.REMOTE_SECURITY_FIELDS:
            self.validated_data.pop(field_name, None)

    def validate(self, attrs):
        errors = {}
        transaction_type = self.get_value_for_validation(attrs, 'transaction_type')
        security = self.get_value_for_validation(attrs, 'security')
        has_remote_security_submission = self.has_remote_security_submission(attrs)
        quantity = self.get_value_for_validation(attrs, 'quantity')
        price = self.get_value_for_validation(attrs, 'price')
        cash_amount = self.get_value_for_validation(attrs, 'cash_amount')
        fee = self.get_value_for_validation(attrs, 'fee')

        if transaction_type in {
            TradeTransaction.TransactionType.BUY,
            TradeTransaction.TransactionType.SELL,
            TradeTransaction.TransactionType.DIVIDEND,
        }:
            if not security and not (
                transaction_type == TradeTransaction.TransactionType.BUY
                and has_remote_security_submission
            ):
                errors['security_id'] = 'Please select a security.'

        if transaction_type != TradeTransaction.TransactionType.BUY and has_remote_security_submission:
            errors['security_id'] = 'Remote security search can only be used for buy transactions.'

        if transaction_type in {
            TradeTransaction.TransactionType.BUY,
            TradeTransaction.TransactionType.SELL,
        }:
            self.validate_positive_field(
                errors,
                'quantity',
                quantity,
                'Quantity must be greater than 0 for buy and sell transactions.',
            )
            self.validate_positive_field(
                errors,
                'price',
                price,
                'Price must be greater than 0 for buy and sell transactions.',
            )

        if transaction_type == TradeTransaction.TransactionType.DIVIDEND:
            self.validate_positive_field(
                errors,
                'cash_amount',
                cash_amount,
                'Cash amount must be greater than 0 for dividend transactions.',
            )

        if fee is not None and fee < 0:
            errors['fee'] = 'Fee cannot be negative.'

        if (
            transaction_type == TradeTransaction.TransactionType.SELL
            and quantity is not None
            and quantity > ZERO
            and price is not None
            and price > ZERO
        ):
            gross_proceeds = quantity * price
            if (fee or ZERO) > gross_proceeds:
                errors['fee'] = SELL_FEE_EXCEEDS_GROSS_PROCEEDS_MESSAGE

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    class Meta:
        model = TradeTransaction
        fields = [
            'id',
            'portfolio',
            'security',
            'security_id',
            'symbol',
            'name',
            'exchange',
            'mic_code',
            'instrument_type',
            'country',
            'currency',
            'search_query',
            'transaction_type',
            'quantity',
            'price',
            'cash_amount',
            'fee',
            'realized_profit_loss',
            'transaction_date',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'security', 'realized_profit_loss', 'created_at', 'updated_at']
