from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import Holding, Portfolio


DEFAULT_PORTFOLIO_NAME = 'My Portfolio'
PRICE_SOURCE_DEMO = 'DEMO_STATIC'
PRICE_SOURCE_UNAVAILABLE = 'DEMO_UNAVAILABLE'
ZERO = Decimal('0')
MONEY_QUANT = Decimal('0.01')
PERCENT_QUANT = Decimal('0.01')
QUANTITY_QUANT = Decimal('0.0001')

DEMO_CURRENT_PRICES = {
    'AAPL': Decimal('189.84'),
    'MSFT': Decimal('449.52'),
    'NVDA': Decimal('131.88'),
    'TSLA': Decimal('248.23'),
    'AMZN': Decimal('199.34'),
    'GOOGL': Decimal('191.18'),
    'META': Decimal('507.42'),
    'SPY': Decimal('562.21'),
    'QQQ': Decimal('486.30'),
}


def get_primary_portfolio(user):
    if not user or not user.is_authenticated:
        return None

    return (
        Portfolio.objects
        .filter(user=user)
        .order_by('created_at', 'id')
        .first()
    )


def get_or_create_primary_portfolio(user, defaults=None):
    defaults = defaults or {}

    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        portfolio = get_primary_portfolio(user)
        if portfolio:
            return portfolio, False

        create_defaults = {
            'name': defaults.get('name') or DEFAULT_PORTFOLIO_NAME,
            'description': defaults.get('description', ''),
            'available_funds': defaults.get('available_funds', Decimal('0.00')),
            'base_currency': defaults.get('base_currency') or 'USD',
        }
        return Portfolio.objects.create(user=user, **create_defaults), True


def quantize_decimal(value, quantum):
    safe_value = value if value is not None else ZERO
    return safe_value.quantize(quantum, rounding=ROUND_HALF_UP)


def format_decimal(value, quantum=MONEY_QUANT):
    return f'{quantize_decimal(value, quantum):f}'


def format_quantity(value):
    quantized = quantize_decimal(value or ZERO, QUANTITY_QUANT)
    return f'{quantized:f}'.rstrip('0').rstrip('.') or '0'


def get_demo_current_price(security):
    price = DEMO_CURRENT_PRICES.get(security.symbol)
    if price is None or price <= ZERO:
        return ZERO, PRICE_SOURCE_UNAVAILABLE
    return price, PRICE_SOURCE_DEMO


def calculate_percent(numerator, denominator):
    if not denominator:
        return ZERO
    return (numerator / denominator) * Decimal('100')


def get_portfolio_summary(user):
    portfolio, _ = get_or_create_primary_portfolio(user)
    available_liquidity = portfolio.available_funds or ZERO
    holdings = (
        Holding.objects
        .select_related('security')
        .filter(portfolio=portfolio)
        .order_by('security__symbol', 'id')
    )

    allocation_rows = []
    total_cost = ZERO
    holdings_market_value = ZERO

    for holding in holdings:
        current_price, price_source = get_demo_current_price(holding.security)
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
            'current_price_source': price_source,
            'cost': cost,
            'market_value': market_value,
            'unrealized_profit_loss': unrealized_profit_loss,
            'unrealized_return_percent': unrealized_return_percent,
        })

    unrealized_profit_loss = holdings_market_value - total_cost
    unrealized_return_percent = calculate_percent(unrealized_profit_loss, total_cost)
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
        'price_source': PRICE_SOURCE_DEMO,
        'holdings_count': len(allocation_rows),
        'total_cost': format_decimal(total_cost),
        'holdings_market_value': format_decimal(holdings_market_value),
        'available_liquidity': format_decimal(available_liquidity),
        'remaining_liquidity': format_decimal(available_liquidity),
        'total_asset_value': format_decimal(total_asset_value),
        'unrealized_profit_loss': format_decimal(unrealized_profit_loss),
        'unrealized_return_percent': format_decimal(
            unrealized_return_percent,
            PERCENT_QUANT,
        ),
        'allocations': allocations,
    }
