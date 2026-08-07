from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security, SecurityDailyPrice
from market.services import MarketDataResult

from .models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction
from .services import (
    get_or_create_primary_portfolio,
    get_portfolio_performance,
    reset_test_portfolio_for_user,
)


ZERO = Decimal('0')
MONEY_QUANTIZER = Decimal('0.01')


def aware_datetime(year, month, day, hour=12):
    return timezone.make_aware(datetime(year, month, day, hour, 0, 0))


def money(value):
    return f'{(value or ZERO).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP):f}'


@override_settings(PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS=0)
class PortfolioPerformanceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='performance_user_a', password='pass')
        self.user_b = User.objects.create_user(username='performance_user_b', password='pass')
        self.security_a = Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            currency='USD',
        )
        self.security_b = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            mic_code='ARCX',
            currency='USD',
        )
        self.daily_prices = {}

        self.market_date_patch = patch(
            'portfolio.services.get_latest_complete_market_date',
            return_value=date(2026, 7, 31),
        )
        self.market_date_patch.start()
        self.addCleanup(self.market_date_patch.stop)

        self.market_data_patch = patch(
            'portfolio.services.get_security_daily_market_data',
            side_effect=self.get_fake_daily_market_data,
        )
        self.market_data_patch.start()
        self.addCleanup(self.market_data_patch.stop)

        self.summary_patch = patch(
            'portfolio.services.get_portfolio_summary',
            side_effect=self.get_fake_portfolio_summary,
        )
        self.summary_patch.start()
        self.addCleanup(self.summary_patch.stop)

    def create_portfolio(self, user=None, cash='1000.00', effective_date=None):
        portfolio = Portfolio.objects.create(
            user=user or self.user_a,
            name='Performance Portfolio',
            available_funds=Decimal(cash),
            initial_balance=Decimal(cash),
        )
        PortfolioCashFlow.objects.create(
            portfolio=portfolio,
            flow_type=PortfolioCashFlow.FlowType.INITIAL,
            amount=Decimal(cash),
            effective_date=effective_date or aware_datetime(2026, 6, 1),
            is_estimated=False,
        )
        return portfolio

    def create_trade(self, portfolio, security=None, **overrides):
        data = {
            'security': security or self.security_a,
            'transaction_type': TradeTransaction.TransactionType.BUY,
            'quantity': Decimal('1.000000'),
            'price': Decimal('100.0000'),
            'fee': Decimal('0.00'),
            'transaction_date': aware_datetime(2026, 7, 1),
        }
        data.update(overrides)
        return TradeTransaction.objects.create(portfolio=portfolio, **data)

    def set_daily_prices(self, security, close_by_date):
        self.daily_prices[security.symbol] = [
            SimpleNamespace(date=price_date, close=Decimal(str(close)))
            for price_date, close in close_by_date
        ]

    def get_fake_daily_market_data(self, security, range_key, start_date, end_date, interval, **kwargs):
        requested_start = date.fromisoformat(start_date)
        requested_end = date.fromisoformat(end_date)
        values = []
        warmup_values = []
        for price_point in self.daily_prices.get(security.symbol, []):
            if requested_start <= price_point.date <= requested_end:
                values.append(price_point)
            elif price_point.date < requested_start:
                warmup_values.append(price_point)

        return MarketDataResult(
            security=security,
            range_key=range_key,
            interval=interval,
            values=values,
            warmup_values=tuple(warmup_values[-30:]),
            source=SecurityDailyPrice.SOURCE_TWELVE_DATA,
            data_source='twelve_data',
            cache_status='test',
        )

    def get_fake_portfolio_summary(self, user):
        portfolio = (
            Portfolio.objects
            .filter(user=user)
            .order_by('created_at', 'id')
            .first()
        )
        if portfolio is None:
            return {}

        total_cost = ZERO
        holdings_market_value = ZERO
        holdings = Holding.objects.filter(portfolio=portfolio).select_related('security')
        for holding in holdings:
            quantity = holding.quantity or ZERO
            total_cost += quantity * (holding.average_cost or ZERO)
            prices = self.daily_prices.get(holding.security.symbol, [])
            latest_close = prices[-1].close if prices else ZERO
            holdings_market_value += quantity * latest_close

        available_liquidity = portfolio.available_funds or ZERO
        return {
            'portfolio_id': portfolio.id,
            'portfolio_name': portfolio.name,
            'base_currency': portfolio.base_currency,
            'price_source': (
                SecurityDailyPrice.SOURCE_TWELVE_DATA
                if holdings_market_value
                else 'NO_HOLDINGS'
            ),
            'holdings_count': holdings.count(),
            'total_cost': money(total_cost),
            'holdings_market_value': money(holdings_market_value),
            'available_liquidity': money(available_liquidity),
            'remaining_liquidity': money(available_liquidity),
            'total_asset_value': money(available_liquidity + holdings_market_value),
            'unrealized_profit_loss': money(holdings_market_value - total_cost),
            'unrealized_return_percent': '0.00',
            'allocations': [],
        }

    def historical_points(self, payload):
        return [point for point in payload['points'] if not point['is_live']]

    def historical_point(self, payload, point_date):
        return {
            point['date']: point
            for point in self.historical_points(payload)
        }[point_date.isoformat()]

    def test_only_initial_cash_without_trades_returns_cash_history(self):
        self.create_portfolio(cash='10000.00')

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        points = self.historical_points(payload)

        self.assertGreater(len(points), 0)
        self.assertEqual(points[0]['cash'], '10000.00')
        self.assertEqual(points[0]['holdings_value'], '0.00')
        self.assertEqual(points[0]['total_account_value'], '10000.00')
        self.assertEqual(points[-1]['cost_basis'], '0.00')
        self.assertFalse(payload['metadata']['is_partial'])

    def test_initial_cash_flow_inside_range_omits_pre_inception_zero_points(self):
        self.create_portfolio(cash='11072.00', effective_date=aware_datetime(2026, 7, 15))

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        points = self.historical_points(payload)

        self.assertGreater(len(points), 0)
        self.assertEqual(points[0]['date'], '2026-07-15')
        self.assertEqual(points[0]['cash'], '11072.00')
        self.assertEqual(points[0]['holdings_value'], '0.00')
        self.assertEqual(points[0]['cost_basis'], '0.00')
        self.assertEqual(points[0]['total_account_value'], '11072.00')
        self.assertFalse(any(point['date'] < '2026-07-15' for point in points))
        self.assertFalse(any(point['total_account_value'] == '0.00' for point in points))
        self.assertEqual(payload['metadata']['first_initial_cash_flow_date'], '2026-07-15')
        self.assertEqual(payload['metadata']['portfolio_inception_date'], '2026-07-15')
        self.assertEqual(payload['metadata']['first_historical_valuation_date'], '2026-07-15')
        self.assertGreater(payload['metadata']['omitted_pre_inception_points'], 0)

    def test_initial_cash_flow_before_range_keeps_cash_value_through_range(self):
        self.create_portfolio(cash='11072.00', effective_date=aware_datetime(2026, 6, 1))

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        points = self.historical_points(payload)

        self.assertGreater(len(points), 0)
        self.assertEqual(points[0]['cash'], '11072.00')
        self.assertEqual(points[0]['holdings_value'], '0.00')
        self.assertEqual(points[0]['cost_basis'], '0.00')
        self.assertEqual(points[0]['total_account_value'], '11072.00')
        self.assertEqual(payload['metadata']['omitted_pre_inception_points'], 0)

    def test_only_one_valid_point_when_inception_is_after_historical_window(self):
        self.create_portfolio(cash='11072.00', effective_date=aware_datetime(2026, 8, 4))

        with patch('portfolio.services.timezone.localdate', return_value=date(2026, 8, 4)):
            payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)

        self.assertEqual(self.historical_points(payload), [])
        self.assertEqual(len(payload['points']), 1)
        self.assertTrue(payload['points'][0]['is_live'])
        self.assertEqual(payload['points'][0]['cash'], '11072.00')
        self.assertEqual(payload['points'][0]['holdings_value'], '0.00')
        self.assertEqual(payload['points'][0]['cost_basis'], '0.00')
        self.assertEqual(payload['points'][0]['total_account_value'], '11072.00')
        self.assertEqual(payload['metadata']['first_valid_valuation_date'], '2026-08-04')

    def test_reset_pure_cash_portfolio_does_not_create_false_zero_jump(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Reset Performance Portfolio',
            available_funds=Decimal('500.00'),
            initial_balance=Decimal('11072.00'),
        )
        portfolio.created_at = aware_datetime(2026, 7, 15)
        portfolio.save(update_fields=['created_at'])
        TradeTransaction.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('500.0000'),
            transaction_date=aware_datetime(2026, 7, 20),
        )
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('500.0000'),
        )

        reset_test_portfolio_for_user(self.user_a)
        portfolio.refresh_from_db()
        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        points = self.historical_points(payload)

        self.assertEqual(portfolio.available_funds, Decimal('11072.00'))
        self.assertFalse(Holding.objects.filter(portfolio=portfolio).exists())
        self.assertFalse(TradeTransaction.objects.filter(portfolio=portfolio).exists())
        self.assertGreater(len(points), 0)
        self.assertEqual(points[0]['date'], '2026-07-15')
        self.assertFalse(any(point['date'] < '2026-07-15' for point in points))
        self.assertFalse(any(point['total_account_value'] == '0.00' for point in points))
        self.assertEqual(payload['points'][-1]['cash'], '11072.00')
        self.assertEqual(payload['points'][-1]['holdings_value'], '0.00')
        self.assertEqual(payload['points'][-1]['cost_basis'], '0.00')
        self.assertEqual(payload['points'][-1]['total_account_value'], '11072.00')

    def test_buy_transaction_reconstructs_cash_and_holdings_value(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('5.00'),
            transaction_date=aware_datetime(2026, 7, 2),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 2), '110.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 2))

        self.assertEqual(point['cash'], '795.00')
        self.assertEqual(point['holdings_value'], '220.00')
        self.assertEqual(point['total_account_value'], '1015.00')
        self.assertEqual(point['cost_basis'], '205.00')

    def test_multiple_buys_reconstruct_weighted_average_cost_basis(self):
        portfolio = self.create_portfolio(cash='2000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('200.0000'),
            transaction_date=aware_datetime(2026, 7, 2),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 2), '210.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 2))

        self.assertEqual(point['cash'], '1700.00')
        self.assertEqual(point['cost_basis'], '300.00')
        self.assertEqual(point['holdings_value'], '420.00')

    def test_sell_reduces_quantity_and_keeps_average_cost(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('3.000000'),
            price=Decimal('100.0000'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        self.create_trade(
            portfolio,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('120.0000'),
            fee=Decimal('2.00'),
            transaction_date=aware_datetime(2026, 7, 3),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 3), '130.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 3))

        self.assertEqual(point['cash'], '818.00')
        self.assertEqual(point['cost_basis'], '200.00')
        self.assertEqual(point['holdings_value'], '260.00')

    def test_full_sell_clears_position_cost_basis(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        self.create_trade(
            portfolio,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('2.000000'),
            price=Decimal('120.0000'),
            fee=Decimal('1.00'),
            transaction_date=aware_datetime(2026, 7, 3),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 3), '130.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 3))

        self.assertEqual(point['cash'], '1039.00')
        self.assertEqual(point['holdings_value'], '0.00')
        self.assertEqual(point['cost_basis'], '0.00')

    def test_buy_fee_affects_cash_and_average_cost_basis(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('7.00'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 1), '100.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 1))

        self.assertEqual(point['cash'], '893.00')
        self.assertEqual(point['cost_basis'], '107.00')

    def test_sell_fee_reduces_cash_and_total_account_value_without_double_counting_realized_profit(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('5.00'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        self.create_trade(
            portfolio,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('120.0000'),
            fee=Decimal('3.00'),
            realized_profit_loss=Decimal('12.0000'),
            transaction_date=aware_datetime(2026, 7, 2),
        )
        self.set_daily_prices(self.security_a, [
            (date(2026, 7, 1), '110.00'),
            (date(2026, 7, 2), '120.00'),
        ])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 2))

        self.assertEqual(point['cash'], '1012.00')
        self.assertEqual(point['holdings_value'], '0.00')
        self.assertEqual(point['cost_basis'], '0.00')
        self.assertEqual(point['total_account_value'], '1012.00')

    def test_live_performance_point_matches_current_summary_cost_and_total_value(self):
        portfolio = self.create_portfolio(cash='1000.00')
        portfolio.available_funds = Decimal('893.00')
        portfolio.save(update_fields=['available_funds'])
        Holding.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('107.0000'),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 31), '120.00')])

        with patch('portfolio.services.timezone.localdate', return_value=date(2026, 8, 4)):
            payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)

        live_point = payload['points'][-1]
        self.assertTrue(live_point['is_live'])
        self.assertEqual(live_point['cash'], '893.00')
        self.assertEqual(live_point['holdings_value'], '120.00')
        self.assertEqual(live_point['cost_basis'], '107.00')
        self.assertEqual(live_point['total_account_value'], '1013.00')

    def test_transactions_before_range_start_affect_initial_visible_state(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=aware_datetime(2026, 6, 1),
        )
        self.set_daily_prices(self.security_a, [(date(2026, 7, 1), '150.00')])

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)
        point = self.historical_point(payload, date(2026, 7, 1))

        self.assertEqual(point['cash'], '900.00')
        self.assertEqual(point['holdings_value'], '150.00')
        self.assertEqual(point['cost_basis'], '100.00')

    def test_missing_prices_return_partial_metadata(self):
        portfolio = self.create_portfolio(cash='1000.00')
        self.create_trade(
            portfolio,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=aware_datetime(2026, 7, 1),
        )

        payload = get_portfolio_performance(self.user_a, range_key='1M', force_refresh=True)

        self.assertTrue(payload['metadata']['is_partial'])
        self.assertGreater(payload['metadata']['missing_price_count'], 0)
        self.assertGreater(len(payload['metadata']['missing_prices']), 0)
        self.assertLess(Decimal(payload['metadata']['price_coverage']), Decimal('1'))

    def test_authenticated_user_only_receives_own_portfolio_performance(self):
        portfolio_a = self.create_portfolio(user=self.user_a, cash='100.00')
        portfolio_b = self.create_portfolio(user=self.user_b, cash='500.00')
        self.client.force_authenticate(self.user_a)

        response = self.client.get(reverse('portfolio-performance'), {'range': '1M'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['metadata']['portfolio_id'], portfolio_a.id)
        self.assertNotEqual(response.data['metadata']['portfolio_id'], portfolio_b.id)

    def test_existing_portfolio_initial_cash_backfill_is_estimated(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Backfill Portfolio',
            available_funds=Decimal('1000.00'),
        )
        TradeTransaction.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('3.00'),
            transaction_date=aware_datetime(2026, 7, 1),
        )
        TradeTransaction.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('150.0000'),
            fee=Decimal('2.00'),
            transaction_date=aware_datetime(2026, 7, 2),
        )

        migration = import_module('portfolio.migrations.0004_portfoliocashflow')

        class SchemaEditor:
            connection = connection

        migration.backfill_initial_cash_flows(django_apps, SchemaEditor())

        cash_flow = PortfolioCashFlow.objects.get(portfolio=portfolio, flow_type=PortfolioCashFlow.FlowType.INITIAL)
        self.assertEqual(cash_flow.amount, Decimal('1055.0000'))
        self.assertTrue(cash_flow.is_estimated)

    def test_new_portfolio_initial_cash_flow_is_recorded(self):
        user = get_user_model().objects.create_user(username='recorded_cash_user', password='pass')

        portfolio, created = get_or_create_primary_portfolio(
            user,
            defaults={
                'name': 'Recorded Portfolio',
                'available_funds': Decimal('1234.56'),
            },
        )

        self.assertTrue(created)
        cash_flow = PortfolioCashFlow.objects.get(portfolio=portfolio, flow_type=PortfolioCashFlow.FlowType.INITIAL)
        self.assertEqual(cash_flow.amount, Decimal('1234.5600'))
        self.assertFalse(cash_flow.is_estimated)

    def test_supported_and_invalid_range_parameters(self):
        self.create_portfolio(cash='1000.00')
        self.client.force_authenticate(self.user_a)

        for range_key in ['1M', '3M', '6M', '1Y']:
            with self.subTest(range_key=range_key):
                response = self.client.get(reverse('portfolio-performance'), {'range': range_key})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data['range'], range_key)

        response = self.client.get(reverse('portfolio-performance'), {'range': '2Y'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('range', response.data)
