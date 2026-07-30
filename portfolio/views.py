from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction as db_transaction
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Holding, Portfolio, TradeTransaction
from .serializers import (
    HoldingSerializer,
    PortfolioSerializer,
    TradeTransactionSerializer,
)
from .services import get_or_create_primary_portfolio, get_portfolio_summary, get_primary_portfolio


AVERAGE_COST_QUANTIZER = Decimal('0.0001')
MONEY_QUANTIZER = Decimal('0.01')
ZERO = Decimal('0')


class PortfolioSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(get_portfolio_summary(request.user))


class PortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = PortfolioSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        primary_portfolio = get_primary_portfolio(self.request.user)
        if not primary_portfolio:
            return Portfolio.objects.none()
        return Portfolio.objects.filter(pk=primary_portfolio.pk)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        portfolio, created = get_or_create_primary_portfolio(
            request.user,
            defaults=serializer.validated_data,
        )
        response_serializer = self.get_serializer(portfolio)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class HoldingViewSet(viewsets.ModelViewSet):
    serializer_class = HoldingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['security__symbol']

    def get_queryset(self):
        return (
            Holding.objects
            .select_related('portfolio', 'security')
            .filter(portfolio__user=self.request.user)
            .order_by('portfolio__name', 'security__symbol')
        )

    def perform_create(self, serializer):
        portfolio, _ = get_or_create_primary_portfolio(self.request.user)
        serializer.save(portfolio=portfolio)


class TradeTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TradeTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['transaction_date', 'created_at']
    ordering = ['-transaction_date', '-created_at']

    def get_queryset(self):
        return (
            TradeTransaction.objects
            .select_related('portfolio', 'security')
            .filter(portfolio__user=self.request.user)
            .order_by('-transaction_date', '-created_at')
        )

    def perform_create(self, serializer):
        with db_transaction.atomic():
            portfolio = self._get_locked_portfolio(serializer.validated_data['portfolio'])
            self._apply_portfolio_liquidity(portfolio, serializer.validated_data)
            trade_transaction = serializer.save(portfolio=portfolio)
            self._sync_holding_for_created_transaction(trade_transaction)

    def _get_locked_portfolio(self, portfolio):
        try:
            return (
                Portfolio.objects
                .select_for_update()
                .get(pk=portfolio.pk, user=self.request.user)
            )
        except Portfolio.DoesNotExist:
            raise serializers.ValidationError({
                'portfolio': 'Portfolio is not available for this user.'
            })

    def _quantize_money(self, value):
        return value.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)

    def _get_trade_cash_values(self, trade_data):
        quantity = trade_data.get('quantity') or ZERO
        price = trade_data.get('price') or ZERO
        fee = trade_data.get('fee') or ZERO
        gross_amount = quantity * price
        return gross_amount, fee

    def _apply_portfolio_liquidity(self, portfolio, trade_data):
        transaction_type = trade_data.get('transaction_type')
        if transaction_type not in {
            TradeTransaction.TransactionType.BUY,
            TradeTransaction.TransactionType.SELL,
        }:
            return

        gross_amount, fee = self._get_trade_cash_values(trade_data)
        if transaction_type == TradeTransaction.TransactionType.BUY:
            total_cost = self._quantize_money(gross_amount + fee)
            if portfolio.available_funds < total_cost:
                raise serializers.ValidationError({
                    'remaining_liquidity': 'Insufficient remaining liquidity for this transaction.'
                })
            portfolio.available_funds = self._quantize_money(portfolio.available_funds - total_cost)

        if transaction_type == TradeTransaction.TransactionType.SELL:
            if fee > gross_amount:
                raise serializers.ValidationError({
                    'fee': 'Fee cannot exceed the gross proceeds of the sale.'
                })
            net_proceeds = self._quantize_money(gross_amount - fee)
            portfolio.available_funds = self._quantize_money(portfolio.available_funds + net_proceeds)

        portfolio.save(update_fields=['available_funds', 'updated_at'])

    def _sync_holding_for_created_transaction(self, trade_transaction):
        if trade_transaction.transaction_type == TradeTransaction.TransactionType.BUY:
            self._apply_buy_transaction(trade_transaction)
            return

        if trade_transaction.transaction_type == TradeTransaction.TransactionType.SELL:
            self._apply_sell_transaction(trade_transaction)

    def _apply_buy_transaction(self, trade_transaction):
        holding, created = (
            Holding.objects
            .select_for_update()
            .get_or_create(
                portfolio=trade_transaction.portfolio,
                security=trade_transaction.security,
                defaults={
                    'quantity': trade_transaction.quantity,
                    'average_cost': trade_transaction.price,
                },
            )
        )

        if not created:
            total_cost = (
                holding.quantity * holding.average_cost
                + trade_transaction.quantity * trade_transaction.price
            )
            holding.quantity += trade_transaction.quantity
            holding.average_cost = (total_cost / holding.quantity).quantize(
                AVERAGE_COST_QUANTIZER,
                rounding=ROUND_HALF_UP,
            )
            holding.save(update_fields=['quantity', 'average_cost', 'updated_at'])

    def _apply_sell_transaction(self, trade_transaction):
        try:
            holding = (
                Holding.objects
                .select_for_update()
                .get(
                    portfolio=trade_transaction.portfolio,
                    security=trade_transaction.security,
                )
            )
        except Holding.DoesNotExist:
            raise serializers.ValidationError({
                'quantity': 'Cannot sell a security that is not held in this portfolio.'
            })

        if trade_transaction.quantity > holding.quantity:
            raise serializers.ValidationError({
                'quantity': 'Sell quantity cannot exceed current holding quantity.'
            })

        holding.quantity -= trade_transaction.quantity
        if holding.quantity == 0:
            holding.delete()
        else:
            holding.save(update_fields=['quantity', 'updated_at'])
