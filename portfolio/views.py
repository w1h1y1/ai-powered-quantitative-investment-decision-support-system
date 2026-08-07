from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from market.services import MarketDataRateLimited, MarketDataUnavailable
from watchlist.services import (
    WatchlistSymbolValidationError,
    get_or_create_verified_security,
    get_verified_search_item,
)

from .models import Holding, Portfolio, TradeTransaction
from .serializers import (
    HoldingSerializer,
    PortfolioSerializer,
    TradeTransactionSerializer,
)
from .services import (
    UnsupportedPortfolioPerformanceRange,
    PortfolioTransactionUndoError,
    calculate_sell_realized_profit_loss,
    get_or_create_primary_portfolio,
    get_portfolio_summary,
    get_portfolio_performance,
    get_primary_portfolio,
    invalidate_portfolio_performance_cache,
    reset_test_portfolio_for_user,
    undo_trade_transaction_for_user,
)


AVERAGE_COST_QUANTIZER = Decimal('0.0001')
MONEY_QUANTIZER = Decimal('0.01')
ZERO = Decimal('0')
ALLOWED_TRANSACTION_PAGE_SIZES = {10, 25, 50}


class TradeTransactionPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_page_size(self, request):
        raw_page_size = request.query_params.get(self.page_size_query_param)
        if raw_page_size in {None, ''}:
            return self.page_size

        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError):
            raise serializers.ValidationError({
                'page_size': 'Page size must be one of 10, 25, or 50.'
            })

        if page_size not in ALLOWED_TRANSACTION_PAGE_SIZES:
            raise serializers.ValidationError({
                'page_size': 'Page size must be one of 10, 25, or 50.'
            })
        return page_size


def can_use_test_transaction_controls(request):
    return settings.DEBUG or request.user.is_staff


def enforce_test_transaction_controls(request):
    if not can_use_test_transaction_controls(request):
        raise PermissionDenied('This test-only action is unavailable for ordinary users.')


class PortfolioSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(get_portfolio_summary(request.user))


class PortfolioPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            return Response(get_portfolio_performance(
                request.user,
                range_key=request.query_params.get('range'),
                force_refresh=parse_refresh_flag(request),
            ))
        except UnsupportedPortfolioPerformanceRange as exc:
            return Response({'range': str(exc)}, status=400)


def parse_refresh_flag(request):
    return str(request.query_params.get('refresh', '')).lower() in {'1', 'true', 'yes', 'on'}


def parse_transaction_date_filter(query_params, field_name):
    raw_value = query_params.get(field_name)
    if raw_value in {None, ''}:
        return None

    try:
        parsed_value = parse_date(str(raw_value))
    except ValueError:
        parsed_value = None
    if parsed_value is None:
        raise serializers.ValidationError({
            field_name: 'Use YYYY-MM-DD date format.'
        })
    return parsed_value


def get_transaction_date_range(query_params):
    start_date = parse_transaction_date_filter(query_params, 'start_date')
    end_date = parse_transaction_date_filter(query_params, 'end_date')

    if start_date is None and end_date is None:
        today = timezone.localdate()
        start_date = today
        end_date = today

    if start_date and end_date and start_date > end_date:
        raise serializers.ValidationError({
            'start_date': 'Start date cannot be later than end date.'
        })

    current_timezone = timezone.get_current_timezone()
    start_datetime = (
        timezone.make_aware(datetime.combine(start_date, time.min), current_timezone)
        if start_date
        else None
    )
    end_datetime = (
        timezone.make_aware(datetime.combine(end_date, time.max), current_timezone)
        if end_date
        else None
    )
    return start_datetime, end_datetime


def build_portfolio_refresh_payload(user, serializer_context=None, status_label='updated'):
    summary = get_portfolio_summary(user)
    transactions = (
        TradeTransaction.objects
        .select_related('portfolio', 'security')
        .filter(portfolio__user=user)
        .order_by('-transaction_date', '-created_at')
    )
    transaction_serializer = TradeTransactionSerializer(
        transactions,
        many=True,
        context=serializer_context or {},
    )
    return {
        'status': status_label,
        'portfolio_summary': summary,
        'transactions': transaction_serializer.data,
        'holdings': summary.get('allocations', []),
        'remaining_liquidity': summary.get('remaining_liquidity'),
        'total_account_value': summary.get('total_asset_value'),
        'cost_basis': summary.get('total_cost'),
        'realized_profit_loss': summary.get('realized_profit_loss'),
        'unrealized_profit_loss': summary.get('unrealized_profit_loss'),
        'total_profit_loss': summary.get('total_profit_loss'),
    }


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
    pagination_class = TradeTransactionPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['transaction_date', 'created_at']
    ordering = ['-transaction_date', '-created_at']

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except WatchlistSymbolValidationError as exc:
            return Response(exc.detail, status=400)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

    def destroy(self, request, *args, **kwargs):
        self.get_object()
        raise PermissionDenied(
            'Completed trade transactions cannot be deleted. Record an offsetting transaction instead.'
        )

    def get_queryset(self):
        queryset = (
            TradeTransaction.objects
            .select_related('portfolio', 'security')
            .filter(portfolio__user=self.request.user)
        )
        if self.action == 'list':
            queryset = self._apply_list_filters(queryset)
        return queryset.order_by('-transaction_date', '-created_at', '-id')

    def _apply_list_filters(self, queryset):
        query_params = self.request.query_params
        start_datetime, end_datetime = get_transaction_date_range(query_params)

        if start_datetime:
            queryset = queryset.filter(transaction_date__gte=start_datetime)
        if end_datetime:
            queryset = queryset.filter(transaction_date__lte=end_datetime)

        transaction_type = str(query_params.get('transaction_type', '')).strip().upper()
        if transaction_type:
            valid_types = {
                choice_value
                for choice_value, _ in TradeTransaction.TransactionType.choices
            }
            if transaction_type not in valid_types:
                raise serializers.ValidationError({
                    'transaction_type': 'Use one of BUY, SELL, or DIVIDEND.'
                })
            queryset = queryset.filter(transaction_type=transaction_type)

        security = str(query_params.get('security', '')).strip()
        if security:
            if security.isdigit():
                queryset = queryset.filter(security_id=int(security))
            else:
                queryset = queryset.filter(security__symbol__iexact=security)

        return queryset

    def perform_create(self, serializer):
        verified_search_item = self._get_verified_search_item_for_transaction(serializer)

        with db_transaction.atomic():
            portfolio = self._get_locked_portfolio(serializer.validated_data['portfolio'])
            self._resolve_transaction_security(serializer, verified_search_item)
            realized_profit_loss = self._calculate_realized_profit_loss(portfolio, serializer.validated_data)
            self._apply_portfolio_liquidity(portfolio, serializer.validated_data)
            serializer.pop_security_submission()
            trade_transaction = serializer.save(
                portfolio=portfolio,
                realized_profit_loss=realized_profit_loss,
            )
            self._sync_holding_for_created_transaction(trade_transaction)
            invalidate_portfolio_performance_cache(portfolio)

    @action(detail=True, methods=['post'])
    def undo(self, request, pk=None):
        enforce_test_transaction_controls(request)
        self.get_object()
        try:
            undo_trade_transaction_for_user(request.user, pk)
        except PortfolioTransactionUndoError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(build_portfolio_refresh_payload(
            request.user,
            serializer_context=self.get_serializer_context(),
            status_label='undone',
        ))

    def _get_verified_search_item_for_transaction(self, serializer):
        transaction_type = serializer.validated_data.get('transaction_type')
        if transaction_type != TradeTransaction.TransactionType.BUY:
            return None
        if serializer.validated_data.get('security'):
            return None
        return get_verified_search_item(serializer.get_security_submission())

    def _resolve_transaction_security(self, serializer, verified_search_item):
        if serializer.validated_data.get('security'):
            return
        if verified_search_item is None:
            raise serializers.ValidationError({
                'security_id': 'Please select a security.'
            })
        security, _ = get_or_create_verified_security(verified_search_item)
        serializer.validated_data['security'] = security

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

    def _calculate_realized_profit_loss(self, portfolio, trade_data):
        if trade_data.get('transaction_type') != TradeTransaction.TransactionType.SELL:
            return ZERO

        try:
            holding = (
                Holding.objects
                .select_for_update()
                .get(
                    portfolio=portfolio,
                    security=trade_data.get('security'),
                )
            )
        except Holding.DoesNotExist:
            raise serializers.ValidationError({
                'quantity': 'Cannot sell a security that is not held in this portfolio.'
            })

        quantity = trade_data.get('quantity') or ZERO
        if quantity > holding.quantity:
            raise serializers.ValidationError({
                'quantity': 'Sell quantity cannot exceed current holding quantity.'
            })

        return calculate_sell_realized_profit_loss(
            quantity,
            trade_data.get('price') or ZERO,
            trade_data.get('fee') or ZERO,
            holding.average_cost or ZERO,
        )

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
                    'quantity': ZERO,
                    'average_cost': ZERO,
                },
            )
        )

        total_cost = (
            holding.quantity * holding.average_cost
            + trade_transaction.quantity * trade_transaction.price
            + (trade_transaction.fee or ZERO)
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


class PortfolioResetTestDataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        enforce_test_transaction_controls(request)
        reset_test_portfolio_for_user(request.user)
        return Response(build_portfolio_refresh_payload(
            request.user,
            serializer_context={'request': request},
            status_label='reset',
        ))
