from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from market.services import (
    MARKET_DATA_QUOTE_SOURCE_UNAVAILABLE,
    MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
    InvalidMarketDataDateRange,
    MarketDataInvalidSymbol,
    MarketDataRateLimited,
    MarketDataUnavailable,
    UnsupportedMarketDataInterval,
    UnsupportedMarketDataRange,
    UnsupportedMarketDataSecurity,
    get_latest_complete_market_date,
    get_security_latest_quotes,
    get_security_daily_market_data,
    subtract_months,
    subtract_years,
)

from .models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction


DEFAULT_PORTFOLIO_NAME = 'My Portfolio'
PORTFOLIO_INITIAL_CASH_FLOW_NOTE = 'Initial cash recorded when the portfolio was created.'
PORTFOLIO_INFERRED_INITIAL_CASH_FLOW_NOTE = (
    'Estimated from current remaining liquidity and recorded buy/sell transactions during migration.'
)
PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX = 'portfolio:performance:v1'
PORTFOLIO_PERFORMANCE_RANGES = {
    '1M': {'months': 1},
    '3M': {'months': 3},
    '6M': {'months': 6},
    '1Y': {'years': 1},
}
PRICE_SOURCE_MIXED = 'MIXED_PRICE_SOURCES'
PRICE_SOURCE_NO_HOLDINGS = 'NO_HOLDINGS'
PRICE_SOURCE_UNAVAILABLE = MARKET_DATA_QUOTE_SOURCE_UNAVAILABLE
ZERO = Decimal('0')
MONEY_QUANT = Decimal('0.01')
PERCENT_QUANT = Decimal('0.01')
QUANTITY_QUANT = Decimal('0.0001')


class UnsupportedPortfolioPerformanceRange(Exception):
    pass


class PortfolioTransactionUndoError(Exception):
    pass


class PortfolioFundingValidationError(Exception):
    pass


def get_primary_portfolio(user):
    if not user or not user.is_authenticated:
        return None

    return (
        Portfolio.objects
        .filter(user=user)
        .order_by('created_at', 'id')
        .first()
    )


def get_portfolio_initial_effective_date(portfolio):
    return portfolio.created_at or timezone.now()


def create_initial_cash_flow(portfolio, amount, *, is_estimated=False, note=''):
    return PortfolioCashFlow.objects.create(
        portfolio=portfolio,
        flow_type=PortfolioCashFlow.FlowType.INITIAL,
        amount=amount or ZERO,
        effective_date=get_portfolio_initial_effective_date(portfolio),
        note=note or (
            PORTFOLIO_INFERRED_INITIAL_CASH_FLOW_NOTE
            if is_estimated
            else PORTFOLIO_INITIAL_CASH_FLOW_NOTE
        ),
        is_estimated=is_estimated,
    )


def get_portfolio_funding_transactions(user):
    portfolio = get_primary_portfolio(user)
    if portfolio is None:
        return []
    return list(
        PortfolioCashFlow.objects
        .filter(portfolio=portfolio)
        .order_by('-effective_date', '-id')
    )


def record_portfolio_funding(user, flow_type, amount, *, note='', effective_date=None):
    normalized_flow_type = str(flow_type or '').strip().upper()
    if normalized_flow_type == 'INITIAL_DEPOSIT':
        normalized_flow_type = PortfolioCashFlow.FlowType.INITIAL
    elif normalized_flow_type == 'DEPOSIT':
        normalized_flow_type = PortfolioCashFlow.FlowType.DEPOSIT
    elif normalized_flow_type == 'WITHDRAWAL':
        normalized_flow_type = PortfolioCashFlow.FlowType.WITHDRAWAL
    else:
        raise PortfolioFundingValidationError(
            'Use Initial Deposit, Deposit, or Withdrawal.'
        )

    amount = quantize_decimal(amount or ZERO, MONEY_QUANT)
    if amount <= ZERO:
        raise PortfolioFundingValidationError('Amount must be greater than 0.')

    if effective_date is None:
        effective_date = timezone.now()
    elif timezone.is_naive(effective_date):
        effective_date = timezone.make_aware(effective_date, timezone.get_current_timezone())

    with transaction.atomic():
        portfolio, _ = get_or_create_primary_portfolio(user)
        portfolio = (
            Portfolio.objects
            .select_for_update()
            .get(pk=portfolio.pk, user=user)
        )

        if normalized_flow_type == PortfolioCashFlow.FlowType.INITIAL:
            has_trades = TradeTransaction.objects.filter(portfolio=portfolio).exists()
            has_other_flows = (
                PortfolioCashFlow.objects
                .filter(portfolio=portfolio)
                .exclude(flow_type=PortfolioCashFlow.FlowType.INITIAL)
                .exists()
            )
            if has_trades or has_other_flows:
                raise PortfolioFundingValidationError(
                    'Initial deposit already recorded. Use a deposit instead.'
                )

            initial_flow = (
                PortfolioCashFlow.objects
                .filter(portfolio=portfolio, flow_type=PortfolioCashFlow.FlowType.INITIAL)
                .order_by('id')
                .first()
            )
            if initial_flow is not None and initial_flow.amount > ZERO:
                raise PortfolioFundingValidationError(
                    'Initial deposit already recorded. Use a deposit instead.'
                )

            if initial_flow is None:
                cash_flow = create_initial_cash_flow(
                    portfolio,
                    amount,
                    note=note or 'Initial deposit',
                )
            else:
                initial_flow.amount = amount
                initial_flow.note = note or initial_flow.note
                initial_flow.effective_date = effective_date
                initial_flow.is_estimated = False
                initial_flow.save(update_fields=[
                    'amount',
                    'note',
                    'effective_date',
                    'is_estimated',
                ])
                cash_flow = initial_flow

            portfolio.initial_balance = amount
            portfolio.available_funds = amount
        elif normalized_flow_type == PortfolioCashFlow.FlowType.DEPOSIT:
            cash_flow = PortfolioCashFlow.objects.create(
                portfolio=portfolio,
                flow_type=PortfolioCashFlow.FlowType.DEPOSIT,
                amount=amount,
                effective_date=effective_date,
                note=note,
                is_estimated=False,
            )
            portfolio.available_funds = quantize_decimal(
                (portfolio.available_funds or ZERO) + amount,
                MONEY_QUANT,
            )
        else:
            available_liquidity = portfolio.available_funds or ZERO
            if amount > available_liquidity:
                raise PortfolioFundingValidationError(
                    'Withdrawal amount cannot exceed available cash.'
                )
            cash_flow = PortfolioCashFlow.objects.create(
                portfolio=portfolio,
                flow_type=PortfolioCashFlow.FlowType.WITHDRAWAL,
                amount=amount,
                effective_date=effective_date,
                note=note,
                is_estimated=False,
            )
            portfolio.available_funds = quantize_decimal(
                available_liquidity - amount,
                MONEY_QUANT,
            )

        portfolio.save(update_fields=['available_funds', 'initial_balance', 'updated_at'])
        invalidate_portfolio_performance_cache(portfolio)
        return portfolio, cash_flow


def get_or_create_primary_portfolio(user, defaults=None):
    defaults = defaults or {}

    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        portfolio = get_primary_portfolio(user)
        if portfolio:
            return portfolio, False

        available_funds = defaults.get('available_funds', Decimal('0.00'))
        initial_balance = defaults.get('initial_balance', available_funds)
        create_defaults = {
            'name': defaults.get('name') or DEFAULT_PORTFOLIO_NAME,
            'description': defaults.get('description', ''),
            'available_funds': available_funds,
            'initial_balance': initial_balance,
            'base_currency': defaults.get('base_currency') or 'USD',
        }
        portfolio = Portfolio.objects.create(user=user, **create_defaults)
        create_initial_cash_flow(portfolio, portfolio.available_funds, is_estimated=False)
        return portfolio, True


def quantize_decimal(value, quantum):
    safe_value = value if value is not None else ZERO
    return safe_value.quantize(quantum, rounding=ROUND_HALF_UP)


def format_decimal(value, quantum=MONEY_QUANT):
    return f'{quantize_decimal(value, quantum):f}'


def format_quantity(value):
    quantized = quantize_decimal(value or ZERO, QUANTITY_QUANT)
    return f'{quantized:f}'.rstrip('0').rstrip('.') or '0'


def calculate_percent(numerator, denominator):
    if not denominator:
        return ZERO
    return (numerator / denominator) * Decimal('100')


def calculate_sell_realized_profit_loss(quantity, price, fee, average_cost):
    gross_amount = (quantity or ZERO) * (price or ZERO)
    cost_basis_sold = (quantity or ZERO) * (average_cost or ZERO)
    return quantize_decimal(
        gross_amount - (fee or ZERO) - cost_basis_sold,
        MONEY_QUANT,
    )


def get_signed_cash_flow_amount(cash_flow):
    amount = get_cash_flow_amount(cash_flow)
    if cash_flow.flow_type in {
        PortfolioCashFlow.FlowType.INITIAL,
        PortfolioCashFlow.FlowType.DEPOSIT,
        PortfolioCashFlow.FlowType.ADJUSTMENT,
    }:
        return amount
    if cash_flow.flow_type == PortfolioCashFlow.FlowType.WITHDRAWAL:
        return -amount
    return ZERO


def get_net_invested_capital(portfolio):
    cash_flows = list(PortfolioCashFlow.objects.filter(portfolio=portfolio))
    if cash_flows:
        return sum((get_signed_cash_flow_amount(cash_flow) for cash_flow in cash_flows), ZERO)
    return portfolio.initial_balance or ZERO


def get_realized_profit_loss(portfolio):
    result = TradeTransaction.objects.filter(portfolio=portfolio).aggregate(
        total=Sum('realized_profit_loss'),
    )
    return result['total'] or ZERO


def get_portfolio_quote_results(holdings):
    securities_by_id = {
        holding.security_id: holding.security
        for holding in holdings
    }
    if not securities_by_id:
        return {}

    quote_results = get_security_latest_quotes(securities_by_id.values())
    return {
        result.security.id: result
        for result in quote_results
    }


def get_quote_current_price(security, quote_results_by_security_id):
    result = quote_results_by_security_id.get(security.id)
    if result is None or result.data_status == MARKET_DATA_QUOTE_STATUS_UNAVAILABLE:
        return {
            'price': ZERO,
            'source': PRICE_SOURCE_UNAVAILABLE,
            'as_of': '',
            'cache_status': 'unavailable',
            'data_status': MARKET_DATA_QUOTE_STATUS_UNAVAILABLE,
            'is_stale': True,
            'error': result.error if result else 'Latest price is unavailable.',
        }

    return {
        'price': result.price,
        'source': result.source,
        'as_of': result.as_of,
        'cache_status': result.cache_status,
        'data_status': result.data_status,
        'is_stale': result.is_stale,
        'error': result.error,
    }


def summarize_price_source(allocation_rows):
    if not allocation_rows:
        return PRICE_SOURCE_NO_HOLDINGS

    sources = {
        row['current_price_source']
        for row in allocation_rows
        if row['current_price_source']
    }
    if not sources:
        return PRICE_SOURCE_UNAVAILABLE
    if len(sources) == 1:
        return sources.pop()
    return PRICE_SOURCE_MIXED


def get_portfolio_summary(user):
    portfolio, _ = get_or_create_primary_portfolio(user)
    available_liquidity = portfolio.available_funds or ZERO
    holdings = list(
        Holding.objects
        .select_related('security')
        .filter(portfolio=portfolio)
        .order_by('security__symbol', 'id')
    )
    quote_results_by_security_id = get_portfolio_quote_results(holdings)

    allocation_rows = []
    total_cost = ZERO
    holdings_market_value = ZERO
    realized_profit_loss = get_realized_profit_loss(portfolio)
    net_invested_capital = get_net_invested_capital(portfolio)

    for holding in holdings:
        current_price_result = get_quote_current_price(holding.security, quote_results_by_security_id)
        current_price = current_price_result['price']
        quantity = holding.quantity or ZERO
        average_price = holding.average_cost or ZERO
        cost = quantity * average_price
        market_value = quantity * current_price
        unrealized_profit_loss = market_value - cost
        unrealized_return_percent = calculate_percent(unrealized_profit_loss, cost)

        total_cost += cost
        holdings_market_value += market_value
        allocation_rows.append({
            'holding': holding,
            'current_price': current_price,
            'current_price_source': current_price_result['source'],
            'current_price_as_of': current_price_result['as_of'],
            'current_price_cache_status': current_price_result['cache_status'],
            'current_price_data_status': current_price_result['data_status'],
            'current_price_is_stale': current_price_result['is_stale'],
            'current_price_error': current_price_result['error'],
            'cost': cost,
            'market_value': market_value,
            'unrealized_profit_loss': unrealized_profit_loss,
            'unrealized_return_percent': unrealized_return_percent,
        })

    unrealized_profit_loss = holdings_market_value - total_cost
    unrealized_return_percent = calculate_percent(unrealized_profit_loss, total_cost)
    total_profit_loss = realized_profit_loss + unrealized_profit_loss
    total_return_percent = calculate_percent(total_profit_loss, net_invested_capital)
    total_asset_value = holdings_market_value + available_liquidity

    allocations = []
    for row in allocation_rows:
        holding = row['holding']
        allocation_percent = calculate_percent(row['market_value'], holdings_market_value)
        allocations.append({
            'holding_id': holding.id,
            'security_id': holding.security_id,
            'symbol': holding.security.symbol,
            'name': holding.security.name,
            'security_type': holding.security.asset_type,
            'currency': holding.security.currency,
            'quantity': format_quantity(holding.quantity),
            'average_price': format_decimal(holding.average_cost),
            'current_price': format_decimal(row['current_price']),
            'current_price_source': row['current_price_source'],
            'current_price_as_of': row['current_price_as_of'],
            'current_price_cache_status': row['current_price_cache_status'],
            'current_price_data_status': row['current_price_data_status'],
            'current_price_is_stale': row['current_price_is_stale'],
            'current_price_error': row['current_price_error'],
            'cost': format_decimal(row['cost']),
            'market_value': format_decimal(row['market_value']),
            'unrealized_profit_loss': format_decimal(row['unrealized_profit_loss']),
            'unrealized_return_percent': format_decimal(
                row['unrealized_return_percent'],
                PERCENT_QUANT,
            ),
            'allocation_percent': format_decimal(allocation_percent, PERCENT_QUANT),
        })

    return {
        'portfolio_id': portfolio.id,
        'portfolio_name': portfolio.name,
        'portfolio_created_at': portfolio.created_at.isoformat() if portfolio.created_at else None,
        'base_currency': portfolio.base_currency,
        'price_source': summarize_price_source(allocation_rows),
        'holdings_count': len(allocation_rows),
        'total_cost': format_decimal(total_cost),
        'holdings_market_value': format_decimal(holdings_market_value),
        'available_liquidity': format_decimal(available_liquidity),
        'remaining_liquidity': format_decimal(available_liquidity),
        'total_asset_value': format_decimal(total_asset_value),
        'realized_profit_loss': format_decimal(realized_profit_loss),
        'unrealized_profit_loss': format_decimal(unrealized_profit_loss),
        'total_profit_loss': format_decimal(total_profit_loss),
        'net_invested_capital': format_decimal(net_invested_capital),
        'unrealized_return_percentage': format_decimal(
            unrealized_return_percent,
            PERCENT_QUANT,
        ),
        'unrealized_return_percent': format_decimal(
            unrealized_return_percent,
            PERCENT_QUANT,
        ),
        'total_return_percentage': format_decimal(
            total_return_percent,
            PERCENT_QUANT,
        ),
        'allocations': allocations,
    }


def normalize_portfolio_performance_range(range_key):
    normalized = str(range_key or '3M').strip().upper()
    if normalized not in PORTFOLIO_PERFORMANCE_RANGES:
        raise UnsupportedPortfolioPerformanceRange('Supported ranges are 1M, 3M, 6M, and 1Y.')
    return normalized


def get_portfolio_performance_cache_ttl_seconds():
    return getattr(settings, 'PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS', 60)


def get_portfolio_performance_cache_version_key(portfolio_id):
    return f'{PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX}:version:{portfolio_id}'


def get_portfolio_performance_cache_version(portfolio_id):
    return cache.get(get_portfolio_performance_cache_version_key(portfolio_id), 1)


def invalidate_portfolio_performance_cache(portfolio):
    if not portfolio:
        return

    version_key = get_portfolio_performance_cache_version_key(portfolio.id)
    try:
        cache.incr(version_key)
    except ValueError:
        cache.set(version_key, 2, None)


def get_revision_timestamp(value):
    if value is None:
        return 'none'
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def get_portfolio_performance_cache_key(portfolio, range_key):
    transaction_revision = TradeTransaction.objects.filter(portfolio=portfolio).aggregate(
        count=Count('id'),
        latest_updated=Max('updated_at'),
    )
    cash_flow_revision = PortfolioCashFlow.objects.filter(portfolio=portfolio).aggregate(
        count=Count('id'),
        latest_created=Max('created_at'),
    )
    return ':'.join([
        PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX,
        str(portfolio.id),
        range_key,
        str(get_portfolio_performance_cache_version(portfolio.id)),
        str(transaction_revision['count'] or 0),
        get_revision_timestamp(transaction_revision['latest_updated']),
        str(cash_flow_revision['count'] or 0),
        get_revision_timestamp(cash_flow_revision['latest_created']),
        get_revision_timestamp(portfolio.updated_at),
    ])


def set_performance_cache_status(payload, cache_status):
    return {
        **payload,
        'metadata': {
            **payload.get('metadata', {}),
            'cache_status': cache_status,
        },
    }


def get_portfolio_performance_window(range_key):
    end_date = get_latest_complete_market_date()
    config = PORTFOLIO_PERFORMANCE_RANGES[range_key]
    if 'months' in config:
        start_date = subtract_months(end_date, config['months'])
    else:
        start_date = subtract_years(end_date, config['years'])
    return start_date, end_date


def get_local_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()


def get_end_of_day(value):
    value_datetime = datetime.combine(value, time.max)
    if timezone.is_naive(value_datetime):
        return timezone.make_aware(value_datetime, timezone.get_current_timezone())
    return value_datetime


def get_performance_weekdays(start_date, end_date):
    current = start_date
    dates = []
    while current <= end_date:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def get_flow_date(cash_flow):
    return get_local_date(cash_flow.effective_date)


def get_transaction_date(trade_transaction):
    return get_local_date(trade_transaction.transaction_date)


def get_trade_gross_amount(trade_transaction):
    return (trade_transaction.quantity or ZERO) * (trade_transaction.price or ZERO)


def get_trade_buy_cash_outflow(trade_transaction):
    return quantize_decimal(
        get_trade_gross_amount(trade_transaction) + (trade_transaction.fee or ZERO),
        MONEY_QUANT,
    )


def get_trade_sell_net_proceeds(trade_transaction):
    return quantize_decimal(
        get_trade_gross_amount(trade_transaction) - (trade_transaction.fee or ZERO),
        MONEY_QUANT,
    )


def get_cash_flow_amount(cash_flow):
    return cash_flow.amount or ZERO


def apply_cash_flow_to_cash(cash, cash_flow):
    amount = get_cash_flow_amount(cash_flow)
    if cash_flow.flow_type in {
        PortfolioCashFlow.FlowType.INITIAL,
        PortfolioCashFlow.FlowType.DEPOSIT,
    }:
        return cash + amount
    if cash_flow.flow_type == PortfolioCashFlow.FlowType.WITHDRAWAL:
        return cash - amount
    if cash_flow.flow_type == PortfolioCashFlow.FlowType.ADJUSTMENT:
        return cash + amount
    return cash


def apply_buy_to_positions(positions, trade_transaction):
    security_id = trade_transaction.security_id
    quantity = trade_transaction.quantity or ZERO
    price = trade_transaction.price or ZERO
    position = positions.get(security_id, {
        'security': trade_transaction.security,
        'quantity': ZERO,
        'average_cost': ZERO,
    })
    current_quantity = position['quantity']
    next_quantity = current_quantity + quantity
    if next_quantity <= ZERO:
        positions.pop(security_id, None)
        return

    current_cost = current_quantity * position['average_cost']
    added_cost = quantity * price + (trade_transaction.fee or ZERO)
    position['quantity'] = next_quantity
    position['average_cost'] = ((current_cost + added_cost) / next_quantity).quantize(
        Decimal('0.0001'),
        rounding=ROUND_HALF_UP,
    )
    positions[security_id] = position


def apply_sell_to_positions(positions, trade_transaction, warnings):
    security_id = trade_transaction.security_id
    quantity = trade_transaction.quantity or ZERO
    position = positions.get(security_id)
    if position is None:
        warnings.append({
            'transaction_id': trade_transaction.id,
            'symbol': trade_transaction.security.symbol,
            'date': get_transaction_date(trade_transaction).isoformat(),
            'message': 'Sell transaction has no preceding reconstructed holding.',
        })
        return

    if quantity > position['quantity']:
        warnings.append({
            'transaction_id': trade_transaction.id,
            'symbol': trade_transaction.security.symbol,
            'date': get_transaction_date(trade_transaction).isoformat(),
            'message': 'Sell quantity exceeds reconstructed holding quantity.',
        })

    position['quantity'] -= quantity
    if position['quantity'] <= ZERO:
        positions.pop(security_id, None)
    else:
        positions[security_id] = position


def apply_trade_transaction(cash, positions, trade_transaction, warnings):
    transaction_type = trade_transaction.transaction_type
    gross_amount = get_trade_gross_amount(trade_transaction)
    fee = trade_transaction.fee or ZERO

    if transaction_type == TradeTransaction.TransactionType.BUY:
        cash -= gross_amount + fee
        apply_buy_to_positions(positions, trade_transaction)
    elif transaction_type == TradeTransaction.TransactionType.SELL:
        cash += gross_amount - fee
        apply_sell_to_positions(positions, trade_transaction, warnings)

    return cash


def get_transactions_before_created_record(trade_transaction):
    return (
        TradeTransaction.objects
        .select_related('security')
        .filter(portfolio=trade_transaction.portfolio, security=trade_transaction.security)
        .filter(
            Q(created_at__lt=trade_transaction.created_at)
            | Q(created_at=trade_transaction.created_at, id__lt=trade_transaction.id)
        )
        .order_by('created_at', 'id')
    )


def reconstruct_position_before_transaction(trade_transaction):
    positions = {}
    warnings = []
    for previous_transaction in get_transactions_before_created_record(trade_transaction):
        if previous_transaction.transaction_type == TradeTransaction.TransactionType.BUY:
            apply_buy_to_positions(positions, previous_transaction)
        elif previous_transaction.transaction_type == TradeTransaction.TransactionType.SELL:
            apply_sell_to_positions(positions, previous_transaction, warnings)

    return positions.get(trade_transaction.security_id, {
        'security': trade_transaction.security,
        'quantity': ZERO,
        'average_cost': ZERO,
    })


def set_holding_from_reconstructed_position(portfolio, security, position):
    quantity = position.get('quantity') or ZERO
    if quantity <= ZERO:
        Holding.objects.filter(portfolio=portfolio, security=security).delete()
        return None

    holding, _ = Holding.objects.update_or_create(
        portfolio=portfolio,
        security=security,
        defaults={
            'quantity': quantity,
            'average_cost': quantize_decimal(
                position.get('average_cost') or ZERO,
                Decimal('0.0001'),
            ),
        },
    )
    return holding


def get_latest_user_trade_transaction(user):
    return (
        TradeTransaction.objects
        .filter(portfolio__user=user)
        .order_by('-created_at', '-id')
        .first()
    )


def undo_trade_transaction_for_user(user, transaction_id):
    with transaction.atomic():
        try:
            trade_transaction = (
                TradeTransaction.objects
                .select_for_update()
                .select_related('portfolio', 'security')
                .get(pk=transaction_id, portfolio__user=user)
            )
        except TradeTransaction.DoesNotExist:
            raise PortfolioTransactionUndoError('Transaction is not available for this user.')

        latest_transaction = get_latest_user_trade_transaction(user)
        if not latest_transaction or latest_transaction.id != trade_transaction.id:
            raise PortfolioTransactionUndoError('Only the latest transaction can be undone.')

        if trade_transaction.transaction_type not in {
            TradeTransaction.TransactionType.BUY,
            TradeTransaction.TransactionType.SELL,
        }:
            raise PortfolioTransactionUndoError('Only buy and sell transactions can be undone.')

        portfolio = (
            Portfolio.objects
            .select_for_update()
            .get(pk=trade_transaction.portfolio_id, user=user)
        )
        Holding.objects.select_for_update().filter(
            portfolio=portfolio,
            security=trade_transaction.security,
        ).first()
        previous_position = reconstruct_position_before_transaction(trade_transaction)

        if trade_transaction.transaction_type == TradeTransaction.TransactionType.BUY:
            portfolio.available_funds = quantize_decimal(
                (portfolio.available_funds or ZERO) + get_trade_buy_cash_outflow(trade_transaction),
                MONEY_QUANT,
            )

        if trade_transaction.transaction_type == TradeTransaction.TransactionType.SELL:
            net_proceeds = get_trade_sell_net_proceeds(trade_transaction)
            if (portfolio.available_funds or ZERO) < net_proceeds:
                raise PortfolioTransactionUndoError(
                    'Insufficient remaining liquidity to undo this sell transaction.'
                )
            portfolio.available_funds = quantize_decimal(
                (portfolio.available_funds or ZERO) - net_proceeds,
                MONEY_QUANT,
            )

        portfolio.save(update_fields=['available_funds', 'updated_at'])
        set_holding_from_reconstructed_position(
            portfolio,
            trade_transaction.security,
            previous_position,
        )
        trade_transaction.delete()
        invalidate_portfolio_performance_cache(portfolio)
        return portfolio


def reset_portfolio_cash_flows_to_initial_balance(portfolio):
    initial_balance = quantize_decimal(portfolio.initial_balance or ZERO, MONEY_QUANT)
    cash_flows = list(
        PortfolioCashFlow.objects
        .select_for_update()
        .filter(portfolio=portfolio)
        .order_by('effective_date', 'id')
    )
    initial_flows = [
        cash_flow
        for cash_flow in cash_flows
        if cash_flow.flow_type == PortfolioCashFlow.FlowType.INITIAL
    ]
    non_initial_ids = [
        cash_flow.id
        for cash_flow in cash_flows
        if cash_flow.flow_type != PortfolioCashFlow.FlowType.INITIAL
    ]
    duplicate_initial_ids = [cash_flow.id for cash_flow in initial_flows[1:]]
    delete_ids = non_initial_ids + duplicate_initial_ids
    if delete_ids:
        PortfolioCashFlow.objects.filter(id__in=delete_ids).delete()

    if not initial_flows:
        return create_initial_cash_flow(
            portfolio,
            initial_balance,
            is_estimated=False,
            note=PORTFOLIO_INITIAL_CASH_FLOW_NOTE,
        )

    initial_flow = initial_flows[0]
    initial_flow.amount = initial_balance
    if not initial_flow.note:
        initial_flow.note = (
            PORTFOLIO_INFERRED_INITIAL_CASH_FLOW_NOTE
            if initial_flow.is_estimated
            else PORTFOLIO_INITIAL_CASH_FLOW_NOTE
        )
    initial_flow.save(update_fields=['amount', 'note'])
    return initial_flow


def reset_test_portfolio_for_user(user):
    with transaction.atomic():
        portfolio, _ = get_or_create_primary_portfolio(user)
        portfolio = Portfolio.objects.select_for_update().get(pk=portfolio.pk, user=user)
        TradeTransaction.objects.select_for_update().filter(portfolio=portfolio).delete()
        Holding.objects.select_for_update().filter(portfolio=portfolio).delete()
        portfolio.available_funds = quantize_decimal(portfolio.initial_balance or ZERO, MONEY_QUANT)
        portfolio.save(update_fields=['available_funds', 'updated_at'])
        reset_portfolio_cash_flows_to_initial_balance(portfolio)
        invalidate_portfolio_performance_cache(portfolio)
        return portfolio


def get_cash_source(cash_flows):
    initial_flows = [
        cash_flow
        for cash_flow in cash_flows
        if cash_flow.flow_type == PortfolioCashFlow.FlowType.INITIAL
    ]
    if not initial_flows:
        return 'missing'
    if any(not cash_flow.is_estimated for cash_flow in initial_flows):
        return 'recorded'
    return 'inferred'


def load_security_daily_prices(security, start_date, end_date, missing_prices):
    try:
        result = get_security_daily_market_data(
            security,
            range_key='CUSTOM',
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            interval='1day',
            force_refresh=False,
        )
    except (
        InvalidMarketDataDateRange,
        MarketDataInvalidSymbol,
        MarketDataRateLimited,
        MarketDataUnavailable,
        UnsupportedMarketDataInterval,
        UnsupportedMarketDataRange,
        UnsupportedMarketDataSecurity,
    ) as exc:
        missing_prices.append({
            'security_id': security.id,
            'symbol': security.symbol,
            'date': '',
            'reason': str(exc),
        })
        return []

    return list(result.warmup_values) + list(result.values)


def get_historical_price_map(securities, start_date, end_date, missing_prices):
    prices_by_security_id = {}
    price_dates = set()

    for security in securities:
        values = load_security_daily_prices(security, start_date, end_date, missing_prices)
        sorted_values = sorted(values, key=lambda value: value.date)
        prices_by_security_id[security.id] = [
            {
                'date': value.date,
                'close': value.close,
            }
            for value in sorted_values
            if value.date <= end_date
        ]
        price_dates.update(
            value.date
            for value in sorted_values
            if start_date <= value.date <= end_date
        )

    return prices_by_security_id, sorted(price_dates)


def get_valuation_dates(start_date, end_date, price_dates):
    if price_dates:
        return price_dates
    return get_performance_weekdays(start_date, end_date)


def get_first_initial_cash_flow_date(cash_flows):
    initial_dates = [
        get_flow_date(cash_flow)
        for cash_flow in cash_flows
        if cash_flow.flow_type == PortfolioCashFlow.FlowType.INITIAL
    ]
    initial_dates = [initial_date for initial_date in initial_dates if initial_date is not None]
    return min(initial_dates) if initial_dates else None


def get_portfolio_inception_date(portfolio, cash_flows):
    first_initial_date = get_first_initial_cash_flow_date(cash_flows)
    if first_initial_date:
        return first_initial_date
    return get_local_date(portfolio.created_at)


def filter_valuation_dates_for_inception(valuation_dates, inception_date):
    if inception_date is None:
        return valuation_dates
    return [
        valuation_date
        for valuation_date in valuation_dates
        if valuation_date >= inception_date
    ]


def update_last_closes_for_date(prices_by_security_id, price_indexes, last_closes, valuation_date):
    for security_id, prices in prices_by_security_id.items():
        price_index = price_indexes.get(security_id, 0)
        while price_index < len(prices) and prices[price_index]['date'] <= valuation_date:
            last_closes[security_id] = prices[price_index]
            price_index += 1
        price_indexes[security_id] = price_index


def calculate_position_values(positions, last_closes, valuation_date, missing_prices):
    holdings_value = ZERO
    cost_basis = ZERO
    total_price_requirements = 0
    missing_price_count = 0

    for security_id, position in positions.items():
        quantity = position['quantity']
        if quantity <= ZERO:
            continue

        cost_basis += quantity * position['average_cost']
        total_price_requirements += 1
        close_point = last_closes.get(security_id)
        if close_point is None:
            missing_price_count += 1
            missing_prices.append({
                'security_id': security_id,
                'symbol': position['security'].symbol,
                'date': valuation_date.isoformat(),
                'reason': 'No current or previous daily close is available.',
            })
            continue

        holdings_value += quantity * close_point['close']

    return holdings_value, cost_basis, total_price_requirements, missing_price_count


def serialize_performance_point(
    valuation_date,
    cash,
    holdings_value,
    cost_basis,
    valuation_source,
    is_live=False,
):
    total_account_value = cash + holdings_value
    return {
        'date': valuation_date.isoformat(),
        'cash': format_decimal(cash),
        'holdings_value': format_decimal(holdings_value),
        'total_account_value': format_decimal(total_account_value),
        'cost_basis': format_decimal(cost_basis),
        'valuation_source': valuation_source,
        'is_live': is_live,
    }


def get_live_valuation_source(price_source):
    if price_source == PRICE_SOURCE_NO_HOLDINGS:
        return 'cash_only'
    if price_source == PRICE_SOURCE_MIXED:
        return 'mixed_price_sources'
    if price_source == MARKET_DATA_QUOTE_SOURCE_UNAVAILABLE:
        return 'price_unavailable'
    if 'CACHED' in str(price_source):
        return 'cached_quote'
    if 'LAST_AVAILABLE' in str(price_source):
        return 'last_available_daily_close'
    return 'latest_quote'


def append_live_summary_point(points, summary):
    live_date = timezone.localdate()
    live_point = {
        'date': live_date.isoformat(),
        'cash': summary.get('remaining_liquidity', '0.00'),
        'holdings_value': summary.get('holdings_market_value', '0.00'),
        'total_account_value': summary.get('total_asset_value', '0.00'),
        'cost_basis': summary.get('total_cost', '0.00'),
        'valuation_source': get_live_valuation_source(summary.get('price_source', '')),
        'is_live': True,
    }

    if points and points[-1]['date'] == live_point['date']:
        return [*points[:-1], live_point]
    return [*points, live_point]


def build_portfolio_performance_payload(portfolio, range_key):
    start_date, end_date = get_portfolio_performance_window(range_key)
    end_datetime = get_end_of_day(end_date)
    all_cash_flows = tuple(
        PortfolioCashFlow.objects
        .filter(portfolio=portfolio)
        .order_by('effective_date', 'id')
    )
    cash_flows = tuple(
        cash_flow
        for cash_flow in all_cash_flows
        if cash_flow.effective_date <= end_datetime
    )
    trade_transactions = tuple(
        TradeTransaction.objects
        .select_related('security')
        .filter(portfolio=portfolio, transaction_date__lte=end_datetime)
        .order_by('transaction_date', 'created_at', 'id')
    )
    securities = tuple({
        trade_transaction.security_id: trade_transaction.security
        for trade_transaction in trade_transactions
        if trade_transaction.transaction_type in {
            TradeTransaction.TransactionType.BUY,
            TradeTransaction.TransactionType.SELL,
        }
    }.values())
    missing_prices = []
    prices_by_security_id, price_dates = get_historical_price_map(
        securities,
        start_date,
        end_date,
        missing_prices,
    )
    raw_valuation_dates = get_valuation_dates(start_date, end_date, price_dates)
    first_initial_cash_flow_date = get_first_initial_cash_flow_date(all_cash_flows)
    portfolio_inception_date = get_portfolio_inception_date(portfolio, all_cash_flows)
    valuation_dates = filter_valuation_dates_for_inception(
        raw_valuation_dates,
        portfolio_inception_date,
    )
    omitted_pre_inception_points = len(raw_valuation_dates) - len(valuation_dates)
    price_indexes = {}
    last_closes = {}
    cash = ZERO
    positions = {}
    cash_flow_index = 0
    transaction_index = 0
    total_price_requirements = 0
    missing_price_count = 0
    warnings = []
    points = []

    for valuation_date in valuation_dates:
        while cash_flow_index < len(cash_flows) and get_flow_date(cash_flows[cash_flow_index]) <= valuation_date:
            cash = apply_cash_flow_to_cash(cash, cash_flows[cash_flow_index])
            cash_flow_index += 1

        while (
            transaction_index < len(trade_transactions)
            and get_transaction_date(trade_transactions[transaction_index]) <= valuation_date
        ):
            cash = apply_trade_transaction(
                cash,
                positions,
                trade_transactions[transaction_index],
                warnings,
            )
            transaction_index += 1

        update_last_closes_for_date(
            prices_by_security_id,
            price_indexes,
            last_closes,
            valuation_date,
        )
        holdings_value, cost_basis, requirements, missing_count = calculate_position_values(
            positions,
            last_closes,
            valuation_date,
            missing_prices,
        )
        total_price_requirements += requirements
        missing_price_count += missing_count

        if requirements == 0:
            valuation_source = 'cash_only'
        elif missing_count:
            valuation_source = 'daily_close_partial'
        else:
            valuation_source = 'daily_close'

        points.append(serialize_performance_point(
            valuation_date,
            cash,
            holdings_value,
            cost_basis,
            valuation_source,
            is_live=False,
        ))

    first_historical_valuation_date = points[0]['date'] if points else None
    summary = get_portfolio_summary(portfolio.user)
    points = append_live_summary_point(points, summary)
    first_valid_valuation_date = points[0]['date'] if points else None
    dividend_count = sum(
        1
        for trade_transaction in trade_transactions
        if trade_transaction.transaction_type == TradeTransaction.TransactionType.DIVIDEND
    )
    holdings_without_transactions = (
        Holding.objects
        .filter(portfolio=portfolio)
        .exclude(security_id__in=[security.id for security in securities])
        .count()
    )
    price_coverage = (
        Decimal('1')
        if total_price_requirements == 0
        else Decimal(total_price_requirements - missing_price_count) / Decimal(total_price_requirements)
    )
    is_partial = bool(missing_prices or warnings or holdings_without_transactions)

    return {
        'range': range_key,
        'as_of': timezone.now().isoformat(),
        'points': points,
        'metadata': {
            'portfolio_id': portfolio.id,
            'portfolio_name': portfolio.name,
            'base_currency': portfolio.base_currency,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'portfolio_created_date': get_local_date(portfolio.created_at).isoformat()
            if get_local_date(portfolio.created_at)
            else None,
            'first_initial_cash_flow_date': (
                first_initial_cash_flow_date.isoformat()
                if first_initial_cash_flow_date
                else None
            ),
            'portfolio_inception_date': (
                portfolio_inception_date.isoformat()
                if portfolio_inception_date
                else None
            ),
            'first_historical_valuation_date': first_historical_valuation_date,
            'first_valid_valuation_date': first_valid_valuation_date,
            'omitted_pre_inception_points': omitted_pre_inception_points,
            'cash_source': get_cash_source(all_cash_flows),
            'is_partial': is_partial,
            'missing_prices': missing_prices[:100],
            'missing_price_count': missing_price_count,
            'price_coverage': format_decimal(price_coverage, Decimal('0.0001')),
            'position_warnings': warnings,
            'untracked_holdings_count': holdings_without_transactions,
            'dividend_transaction_count': dividend_count,
            'dividend_cash_handling': (
                'ignored_current_transaction_service_does_not_update_available_funds'
                if dividend_count
                else 'not_applicable'
            ),
            'cache_status': 'fresh',
        },
    }


def get_portfolio_performance(user, range_key=None, force_refresh=False):
    portfolio, _ = get_or_create_primary_portfolio(user)
    normalized_range = normalize_portfolio_performance_range(range_key)
    cache_ttl = get_portfolio_performance_cache_ttl_seconds()
    cache_key = get_portfolio_performance_cache_key(portfolio, normalized_range)

    if cache_ttl > 0 and not force_refresh:
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return set_performance_cache_status(cached_payload, 'hit')

    payload = build_portfolio_performance_payload(portfolio, normalized_range)
    if cache_ttl > 0:
        cache.set(cache_key, payload, cache_ttl)
    return payload
