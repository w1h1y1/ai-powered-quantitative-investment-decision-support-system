from datetime import date, datetime, time, timedelta
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security
from market.services import MarketDataRateLimited
from watchlist.models import WatchlistItem

from .models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction
from .services import get_or_create_primary_portfolio, undo_trade_transaction_for_user


class TradeTransactionApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='trade_user_a', password='pass')
        self.user_b = User.objects.create_user(username='trade_user_b', password='pass')
        self.security_a = Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.security_b = Security.objects.create(
            symbol='SPY',
            name='SPDR S&P 500 ETF Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NYSEARCA',
            currency='USD',
        )
        self.security_c = Security.objects.create(
            symbol='QQQ',
            name='Invesco QQQ Trust',
            asset_type=Security.AssetType.ETF,
            exchange='NASDAQ',
            currency='USD',
        )
        self.portfolio_a = Portfolio.objects.create(
            user=self.user_a,
            name='User A Portfolio',
            available_funds=Decimal('10000.00'),
            initial_balance=Decimal('10000.00'),
        )
        self.portfolio_b = Portfolio.objects.create(
            user=self.user_b,
            name='User B Portfolio',
            available_funds=Decimal('5000.00'),
            initial_balance=Decimal('5000.00'),
        )
        self.transaction_b = TradeTransaction.objects.create(
            portfolio=self.portfolio_b,
            security=self.security_b,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('500.0000'),
            fee=Decimal('1.00'),
            transaction_date=timezone.now(),
            notes='User B buy',
        )
        self.quote_patch = patch('portfolio.services.get_security_latest_quotes', return_value=())
        self.quote_patch.start()
        self.addCleanup(self.quote_patch.stop)

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def aware_datetime_on(self, value_date, hour=12):
        return timezone.make_aware(
            datetime.combine(value_date, time(hour, 0, 0)),
            timezone.get_current_timezone(),
        )

    def create_trade_for_date(self, portfolio=None, security=None, value_date=None, **overrides):
        trade_date = value_date or timezone.localdate()
        payload = {
            'portfolio': portfolio or self.portfolio_a,
            'security': security or self.security_a,
            'transaction_type': TradeTransaction.TransactionType.BUY,
            'quantity': Decimal('1.000000'),
            'price': Decimal('100.0000'),
            'fee': Decimal('0.00'),
            'transaction_date': self.aware_datetime_on(trade_date),
        }
        payload.update(overrides)
        return TradeTransaction.objects.create(**payload)

    def transaction_result_ids(self, response):
        return [item['id'] for item in response.data['results']]

    def base_payload(self, **overrides):
        payload = {
            'portfolio': self.portfolio_a.id,
            'security_id': self.security_a.id,
            'transaction_type': TradeTransaction.TransactionType.BUY,
            'quantity': '1.000000',
            'price': '400.0000',
            'fee': '0.00',
            'transaction_date': timezone.now().isoformat(),
            'notes': 'Trade note',
        }
        payload.update(overrides)
        return payload

    def remote_buy_payload(self, **overrides):
        payload = self.base_payload(
            security_id=None,
            symbol='AMD',
            name='Advanced Micro Devices Inc.',
            exchange='NASDAQ',
            mic_code='XNAS',
            instrument_type='Common Stock',
            country='United States',
            currency='USD',
            search_query='Advanced Micro Devices',
        )
        payload.pop('security_id', None)
        payload.update(overrides)
        return payload

    def verified_amd_search_item(self):
        return {
            'id': None,
            'symbol': 'AMD',
            'name': 'Advanced Micro Devices Inc.',
            'exchange': 'NASDAQ',
            'mic_code': 'XNAS',
            'instrument_type': 'Common Stock',
            'country': 'United States',
            'currency': 'USD',
            'is_local': False,
        }

    def test_unauthenticated_user_cannot_access_transaction_endpoint(self):
        response = self.client.get(reverse('transaction-list'))

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_user_a_can_create_own_buy_transaction(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(reverse('transaction-list'), self.base_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.portfolio, self.portfolio_a)
        self.assertEqual(transaction_record.security, self.security_a)
        self.assertEqual(transaction_record.transaction_type, TradeTransaction.TransactionType.BUY)
        self.assertEqual(transaction_record.fee, Decimal('0.00'))
        self.assertEqual(transaction_record.realized_profit_loss, Decimal('0.0000'))
        self.assertEqual(response.data['realized_profit_loss'], '0.0000')
        self.assertEqual(response.data['portfolio'], self.portfolio_a.id)
        self.assertEqual(response.data['security']['symbol'], 'MSFT')
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.assertEqual(holding.average_cost, Decimal('400.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9600.00'))

    def test_user_a_can_buy_remote_search_result_without_watchlist_item(self):
        self.authenticate_as(self.user_a)

        with patch('portfolio.views.get_verified_search_item', return_value=self.verified_amd_search_item()) as verify_mock:
            response = self.client.post(reverse('transaction-list'), self.remote_buy_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        security = Security.objects.get(symbol='AMD', mic_code='XNAS')
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.security, security)
        self.assertEqual(response.data['security']['symbol'], 'AMD')
        self.assertEqual(Holding.objects.get(portfolio=self.portfolio_a, security=security).quantity, Decimal('1.000000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9600.00'))
        self.assertFalse(WatchlistItem.objects.filter(watchlist__user=self.user_a, security=security).exists())
        verify_mock.assert_called_once()

    def test_remote_buy_reuses_existing_security_by_symbol_and_mic_code(self):
        existing_security = Security.objects.create(
            symbol='AMD',
            name='Advanced Micro Devices',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            mic_code='XNAS',
            currency='USD',
        )
        self.authenticate_as(self.user_a)

        with patch('portfolio.views.get_verified_search_item', return_value=self.verified_amd_search_item()):
            response = self.client.post(reverse('transaction-list'), self.remote_buy_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Security.objects.filter(symbol='AMD', mic_code='XNAS').count(), 1)
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.security, existing_security)

    def test_remote_buy_rolls_back_security_when_trade_fails(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('10.00')
        self.portfolio_a.save(update_fields=['available_funds'])
        original_transaction_count = TradeTransaction.objects.count()

        with patch('portfolio.views.get_verified_search_item', return_value=self.verified_amd_search_item()):
            response = self.client.post(reverse('transaction-list'), self.remote_buy_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('remaining_liquidity', response.data)
        self.assertFalse(Security.objects.filter(symbol='AMD', mic_code='XNAS').exists())
        self.assertEqual(TradeTransaction.objects.count(), original_transaction_count)

    def test_remote_buy_preserves_market_data_rate_limit_status(self):
        self.authenticate_as(self.user_a)

        with patch(
            'portfolio.views.get_verified_search_item',
            side_effect=MarketDataRateLimited('Market data provider rate limit reached. Please try again later.'),
        ):
            response = self.client.post(reverse('transaction-list'), self.remote_buy_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('Market data provider rate limit reached', response.data['detail'])
        self.assertFalse(Security.objects.filter(symbol='AMD').exists())

    def test_user_a_can_create_own_sell_transaction(self):
        self.authenticate_as(self.user_a)
        holding = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('3.000000'),
            average_cost=Decimal('390.0000'),
        )

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='2.000000',
                price='410.5000',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['transaction_type'], TradeTransaction.TransactionType.SELL)
        self.assertEqual(response.data['realized_profit_loss'], '41.0000')
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.realized_profit_loss, Decimal('41.0000'))
        holding.refresh_from_db()
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.assertEqual(holding.average_cost, Decimal('390.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10821.00'))

    def test_user_a_can_create_own_dividend_transaction(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.DIVIDEND,
                quantity=None,
                price=None,
                cash_amount='25.5000',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['transaction_type'], TradeTransaction.TransactionType.DIVIDEND)
        self.assertEqual(response.data['cash_amount'], '25.5000')

    def test_buy_without_quantity_fails(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity=None),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity', response.data)

    def test_buy_without_price_fails(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(price=None),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('price', response.data)

    def test_dividend_without_cash_amount_fails(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.DIVIDEND,
                quantity=None,
                price=None,
                cash_amount=None,
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cash_amount', response.data)

    def test_negative_quantity_price_cash_amount_or_fee_fails(self):
        self.authenticate_as(self.user_a)
        invalid_payloads = {
            'quantity': self.base_payload(quantity='-1.000000'),
            'price': self.base_payload(price='-1.0000'),
            'cash_amount': self.base_payload(
                transaction_type=TradeTransaction.TransactionType.DIVIDEND,
                quantity=None,
                price=None,
                cash_amount='-1.0000',
            ),
            'fee': self.base_payload(fee='-1.00'),
        }

        for field_name, payload in invalid_payloads.items():
            with self.subTest(field_name=field_name):
                response = self.client.post(reverse('transaction-list'), payload, format='json')

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field_name, response.data)

    def test_users_can_only_list_their_own_trade_transactions(self):
        user_a_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('400.0000'),
            transaction_date=timezone.now(),
        )

        self.authenticate_as(self.user_a)
        user_a_response = self.client.get(reverse('transaction-list'))

        self.authenticate_as(self.user_b)
        user_b_response = self.client.get(reverse('transaction-list'))

        self.assertEqual(user_a_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.transaction_result_ids(user_a_response), [user_a_transaction.id])
        self.assertEqual(user_b_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.transaction_result_ids(user_b_response), [self.transaction_b.id])

    def test_transaction_list_defaults_to_today_records(self):
        today = timezone.localdate()
        yesterday_transaction = self.create_trade_for_date(value_date=today - timedelta(days=1))
        today_transaction = self.create_trade_for_date(value_date=today)
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(self.transaction_result_ids(response), [today_transaction.id])
        self.assertFalse(any(item['id'] == yesterday_transaction.id for item in response.data['results']))

    def test_transaction_list_last_seven_days_range_includes_today_and_previous_six_days(self):
        today = timezone.localdate()
        start_date = today - timedelta(days=6)
        inside_start = self.create_trade_for_date(value_date=start_date)
        inside_today = self.create_trade_for_date(value_date=today)
        self.create_trade_for_date(value_date=start_date - timedelta(days=1))
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'), {
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(self.transaction_result_ids(response), [inside_today.id, inside_start.id])

    def test_transaction_list_year_to_date_range_starts_on_january_first(self):
        today = timezone.localdate()
        start_date = date(today.year, 1, 1)
        jan_first_transaction = self.create_trade_for_date(value_date=start_date)
        today_transaction = self.create_trade_for_date(value_date=today)
        self.create_trade_for_date(value_date=date(today.year - 1, 12, 31))
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'), {
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(self.transaction_result_ids(response), [today_transaction.id, jan_first_transaction.id])

    def test_transaction_list_quarter_date_boundaries(self):
        current_year = timezone.localdate().year
        quarter_ranges = {
            'Q1': (date(current_year, 1, 1), date(current_year, 3, 31)),
            'Q2': (date(current_year, 4, 1), date(current_year, 6, 30)),
            'Q3': (date(current_year, 7, 1), date(current_year, 9, 30)),
            'Q4': (date(current_year, 10, 1), date(current_year, 12, 31)),
        }
        expected_ids = {}
        for quarter, (start_date, end_date) in quarter_ranges.items():
            start_transaction = self.create_trade_for_date(value_date=start_date)
            end_transaction = self.create_trade_for_date(value_date=end_date)
            expected_ids[quarter] = [end_transaction.id, start_transaction.id]

        self.authenticate_as(self.user_a)

        for quarter, (start_date, end_date) in quarter_ranges.items():
            with self.subTest(quarter=quarter):
                response = self.client.get(reverse('transaction-list'), {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                })

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self.transaction_result_ids(response), expected_ids[quarter])

    def test_transaction_list_quarter_filter_uses_selected_year(self):
        prior_year = timezone.localdate().year - 1
        current_year = timezone.localdate().year
        prior_year_transaction = self.create_trade_for_date(value_date=date(prior_year, 2, 15))
        self.create_trade_for_date(value_date=date(current_year, 2, 15))
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'), {
            'start_date': date(prior_year, 1, 1).isoformat(),
            'end_date': date(prior_year, 3, 31).isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(self.transaction_result_ids(response), [prior_year_transaction.id])

    def test_transaction_list_pagination_returns_count_links_and_results(self):
        today = timezone.localdate()
        for index in range(12):
            self.create_trade_for_date(value_date=today, price=Decimal('100.0000') + Decimal(index))
        self.authenticate_as(self.user_a)

        first_page = self.client.get(reverse('transaction-list'), {
            'start_date': today.isoformat(),
            'end_date': today.isoformat(),
            'page_size': '10',
            'page': '1',
        })
        second_page = self.client.get(reverse('transaction-list'), {
            'start_date': today.isoformat(),
            'end_date': today.isoformat(),
            'page_size': '10',
            'page': '2',
        })

        self.assertEqual(first_page.status_code, status.HTTP_200_OK)
        self.assertEqual(first_page.data['count'], 12)
        self.assertIsNotNone(first_page.data['next'])
        self.assertIsNone(first_page.data['previous'])
        self.assertEqual(len(first_page.data['results']), 10)
        self.assertEqual(second_page.status_code, status.HTTP_200_OK)
        self.assertEqual(second_page.data['count'], 12)
        self.assertIsNone(second_page.data['next'])
        self.assertIsNotNone(second_page.data['previous'])
        self.assertEqual(len(second_page.data['results']), 2)

    def test_transaction_list_invalid_date_returns_400(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'), {'start_date': '2026-99-99'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_date', response.data)

    def test_transaction_list_start_date_after_end_date_returns_400(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('transaction-list'), {
            'start_date': '2026-08-05',
            'end_date': '2026-08-04',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_date', response.data)

    @override_settings(DEBUG=False)
    def test_ordinary_user_cannot_use_test_undo_or_reset_in_production(self):
        self.authenticate_as(self.user_a)
        trade_transaction = self.create_trade_for_date()

        undo_response = self.client.post(reverse('transaction-undo', args=[trade_transaction.id]))
        reset_response = self.client.post(reverse('portfolio-reset-test-data'))

        self.assertEqual(undo_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reset_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(TradeTransaction.objects.filter(id=trade_transaction.id).exists())

    @override_settings(DEBUG=False)
    def test_staff_user_can_reset_test_portfolio_in_production_mode(self):
        User = get_user_model()
        staff_user = User.objects.create_user(username='trade_staff_user', password='pass', is_staff=True)
        staff_portfolio = Portfolio.objects.create(
            user=staff_user,
            name='Staff Portfolio',
            available_funds=Decimal('1000.00'),
            initial_balance=Decimal('1000.00'),
        )
        self.create_trade_for_date(portfolio=staff_portfolio, security=self.security_a)
        Holding.objects.create(
            portfolio=staff_portfolio,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('100.0000'),
        )
        staff_portfolio.available_funds = Decimal('900.00')
        staff_portfolio.save(update_fields=['available_funds'])
        self.authenticate_as(staff_user)

        response = self.client.post(reverse('portfolio-reset-test-data'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(TradeTransaction.objects.filter(portfolio=staff_portfolio).exists())
        self.assertFalse(Holding.objects.filter(portfolio=staff_portfolio).exists())
        staff_portfolio.refresh_from_db()
        self.assertEqual(staff_portfolio.available_funds, Decimal('1000.00'))

    def test_user_a_cannot_read_update_or_delete_user_b_transaction(self):
        self.authenticate_as(self.user_a)

        detail_response = self.client.get(reverse('transaction-detail', args=[self.transaction_b.id]))
        patch_response = self.client.patch(
            reverse('transaction-detail', args=[self.transaction_b.id]),
            {'notes': 'Compromised'},
            format='json',
        )
        delete_response = self.client.delete(reverse('transaction-detail', args=[self.transaction_b.id]))

        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.transaction_b.refresh_from_db()
        self.assertEqual(self.transaction_b.notes, 'User B buy')

    def test_user_can_patch_only_notes_on_own_transaction(self):
        self.authenticate_as(self.user_a)
        transaction_record = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('400.0000'),
            fee=Decimal('1.50'),
            transaction_date=timezone.now(),
            notes='Original note',
        )

        response = self.client.patch(
            reverse('transaction-detail', args=[transaction_record.id]),
            {'notes': 'Updated note only'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['notes'], 'Updated note only')
        transaction_record.refresh_from_db()
        self.assertEqual(transaction_record.notes, 'Updated note only')
        self.assertEqual(transaction_record.portfolio, self.portfolio_a)
        self.assertEqual(transaction_record.security, self.security_a)
        self.assertEqual(transaction_record.transaction_type, TradeTransaction.TransactionType.BUY)
        self.assertEqual(transaction_record.quantity, Decimal('1.000000'))
        self.assertEqual(transaction_record.price, Decimal('400.0000'))
        self.assertEqual(transaction_record.fee, Decimal('1.50'))

    def test_user_cannot_delete_own_completed_transaction(self):
        self.authenticate_as(self.user_a)
        transaction_record = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('400.0000'),
            transaction_date=timezone.now(),
        )

        response = self.client.delete(reverse('transaction-detail', args=[transaction_record.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(TradeTransaction.objects.filter(id=transaction_record.id).exists())

    def test_user_a_cannot_create_transaction_with_user_b_portfolio_id(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(portfolio=self.portfolio_b.id, security_id=self.security_c.id),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('portfolio', response.data)
        self.portfolio_b.refresh_from_db()
        self.assertEqual(self.portfolio_b.available_funds, Decimal('5000.00'))
        self.assertFalse(
            TradeTransaction.objects.filter(portfolio=self.portfolio_b, security=self.security_c).exists()
        )

    def test_user_a_cannot_patch_transaction_to_user_b_portfolio(self):
        self.authenticate_as(self.user_a)
        transaction_record = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('400.0000'),
            transaction_date=timezone.now(),
        )

        response = self.client.patch(
            reverse('transaction-detail', args=[transaction_record.id]),
            {'portfolio': self.portfolio_b.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transaction_record.refresh_from_db()
        self.assertEqual(transaction_record.portfolio, self.portfolio_a)

    def test_buy_transaction_recalculates_weighted_average_cost_for_existing_holding(self):
        self.authenticate_as(self.user_a)
        holding = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('10.000000'),
            average_cost=Decimal('400.0000'),
        )

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='410.0000', fee='2.00'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        holding.refresh_from_db()
        self.assertEqual(holding.quantity, Decimal('11.000000'))
        self.assertEqual(holding.average_cost, Decimal('401.0909'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9588.00'))

    def test_two_buy_transactions_calculate_fee_adjusted_weighted_average_cost(self):
        self.authenticate_as(self.user_a)

        first_response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='100.0000', fee='5.00'),
            format='json',
        )
        second_response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='200.0000', fee='1.00'),
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('2.000000'))
        self.assertEqual(holding.average_cost, Decimal('153.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9694.00'))

    def test_sell_transaction_deletes_holding_when_quantity_reaches_zero(self):
        self.authenticate_as(self.user_a)
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('390.0000'),
        )

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='2.000000',
                price='410.5000',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_a, security=self.security_a).exists())
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.realized_profit_loss, Decimal('41.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10821.00'))
        summary_response = self.client.get(reverse('portfolio-summary'))
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data['total_cost'], '0.00')
        self.assertEqual(summary_response.data['unrealized_profit_loss'], '0.00')
        self.assertEqual(summary_response.data['realized_profit_loss'], '41.00')
        self.assertEqual(summary_response.data['total_profit_loss'], '41.00')

    def test_sell_without_holding_fails_and_rolls_back_transaction(self):
        self.authenticate_as(self.user_a)
        original_count = TradeTransaction.objects.count()
        original_funds = self.portfolio_a.available_funds

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='1.000000',
                price='410.5000',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity', response.data)
        self.assertEqual(TradeTransaction.objects.count(), original_count)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, original_funds)

    def test_sell_more_than_existing_holding_fails_and_preserves_holding(self):
        self.authenticate_as(self.user_a)
        holding = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('390.0000'),
        )
        original_count = TradeTransaction.objects.count()
        original_funds = self.portfolio_a.available_funds

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='2.000000',
                price='410.5000',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity', response.data)
        self.assertEqual(TradeTransaction.objects.count(), original_count)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, original_funds)
        holding.refresh_from_db()
        self.assertEqual(holding.quantity, Decimal('1.000000'))

    def test_buy_deducts_quantity_price_and_fee_from_available_funds(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='2.000000', price='100.0000', fee='3.50'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.average_cost, Decimal('101.7500'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9796.50'))
        summary_response = self.client.get(reverse('portfolio-summary'))
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data['remaining_liquidity'], '9796.50')

    def test_sell_adds_net_proceeds_to_available_funds(self):
        self.authenticate_as(self.user_a)
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('5.000000'),
            average_cost=Decimal('80.0000'),
        )

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='2.000000',
                price='100.0000',
                fee='5.00',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        transaction_record = TradeTransaction.objects.get(id=response.data['id'])
        self.assertEqual(transaction_record.realized_profit_loss, Decimal('35.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10195.00'))

    def test_sell_fee_equal_to_gross_proceeds_is_allowed_with_zero_net_proceeds(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('4300.00')
        self.portfolio_a.save(update_fields=['available_funds'])
        holding = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('32.000000'),
            average_cost=Decimal('80.0000'),
        )
        original_count = TradeTransaction.objects.count()

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='1.000000',
                price='100.0000',
                fee='100.00',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TradeTransaction.objects.count(), original_count + 1)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('4300.00'))
        holding.refresh_from_db()
        self.assertEqual(holding.quantity, Decimal('31.000000'))
        self.assertEqual(holding.average_cost, Decimal('80.0000'))

    def test_buy_is_allowed_when_available_funds_equal_total_cost(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('401.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='400.0000', fee='1.00'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('0.00'))

    def test_buy_with_insufficient_available_funds_rolls_back_all_changes(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('399.99')
        self.portfolio_a.save(update_fields=['available_funds'])
        original_count = TradeTransaction.objects.count()

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='400.0000', fee='0.00'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('remaining_liquidity', response.data)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('399.99'))
        self.assertEqual(TradeTransaction.objects.count(), original_count)
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_a, security=self.security_a).exists())

    def test_sell_fee_greater_than_sell_amount_is_rejected(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('4300.00')
        self.portfolio_a.save(update_fields=['available_funds'])
        holding = Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('32.000000'),
            average_cost=Decimal('80.0000'),
        )
        original_count = TradeTransaction.objects.count()
        original_funds = self.portfolio_a.available_funds
        original_quantity = holding.quantity
        original_average_cost = holding.average_cost

        response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(
                transaction_type=TradeTransaction.TransactionType.SELL,
                quantity='1.000000',
                price='100.0000',
                fee='101.00',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('fee', response.data)
        self.assertEqual(response.data['fee'][0], 'Fee cannot exceed the gross proceeds of the sale.')
        self.assertEqual(TradeTransaction.objects.count(), original_count)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, original_funds)
        holding.refresh_from_db()
        self.assertEqual(holding.quantity, original_quantity)
        self.assertEqual(holding.average_cost, original_average_cost)

    def test_repeated_buy_requests_cannot_reuse_spent_liquidity(self):
        self.authenticate_as(self.user_a)
        self.portfolio_a.available_funds = Decimal('500.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        first_response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='300.0000', fee='0.00'),
            format='json',
        )
        second_response = self.client.post(
            reverse('transaction-list'),
            self.base_payload(quantity='1.000000', price='300.0000', fee='0.00'),
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('200.00'))
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.assertEqual(TradeTransaction.objects.filter(portfolio=self.portfolio_a, security=self.security_a).count(), 1)

    @override_settings(DEBUG=True)
    def test_user_can_undo_own_latest_buy_transaction(self):
        self.authenticate_as(self.user_a)
        trade_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('3.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('100.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9797.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('transaction-undo', args=[trade_transaction.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'undone')
        self.assertFalse(TradeTransaction.objects.filter(id=trade_transaction.id).exists())
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_a, security=self.security_a).exists())
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10000.00'))
        self.assertEqual(response.data['remaining_liquidity'], '10000.00')

    @override_settings(DEBUG=True)
    def test_user_can_undo_own_latest_sell_transaction(self):
        self.authenticate_as(self.user_a)
        buy_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('3.000000'),
            price=Decimal('80.0000'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )
        sell_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('5.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('80.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9955.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('transaction-undo', args=[sell_transaction.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(TradeTransaction.objects.filter(id=buy_transaction.id).exists())
        self.assertFalse(TradeTransaction.objects.filter(id=sell_transaction.id).exists())
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('3.000000'))
        self.assertEqual(holding.average_cost, Decimal('80.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9760.00'))

    @override_settings(DEBUG=True)
    def test_cannot_undo_non_latest_transaction(self):
        self.authenticate_as(self.user_a)
        older_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )
        latest_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('110.0000'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('105.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9790.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('transaction-undo', args=[older_transaction.id]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Only the latest transaction can be undone.')
        self.assertTrue(TradeTransaction.objects.filter(id=older_transaction.id).exists())
        self.assertTrue(TradeTransaction.objects.filter(id=latest_transaction.id).exists())
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9790.00'))

    @override_settings(DEBUG=True)
    def test_user_cannot_undo_other_users_transaction(self):
        self.authenticate_as(self.user_a)

        response = self.client.post(reverse('transaction-undo', args=[self.transaction_b.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(TradeTransaction.objects.filter(id=self.transaction_b.id).exists())

    def test_unauthenticated_user_cannot_undo_transaction(self):
        transaction_record = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=timezone.now(),
        )

        response = self.client.post(reverse('transaction-undo', args=[transaction_record.id]))

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        self.assertTrue(TradeTransaction.objects.filter(id=transaction_record.id).exists())

    @override_settings(DEBUG=True)
    def test_buy_undo_restores_previous_holding_average_cost(self):
        self.authenticate_as(self.user_a)
        first_buy = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )
        latest_buy = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('200.0000'),
            fee=Decimal('0.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('150.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9700.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('transaction-undo', args=[latest_buy.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(TradeTransaction.objects.filter(id=first_buy.id).exists())
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.assertEqual(holding.average_cost, Decimal('100.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9900.00'))

    @override_settings(DEBUG=True)
    def test_sell_undo_fails_when_remaining_liquidity_is_insufficient(self):
        self.authenticate_as(self.user_a)
        TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('80.0000'),
            transaction_date=timezone.now(),
        )
        sell_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('5.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('80.0000'),
        )
        self.portfolio_a.available_funds = Decimal('10.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('transaction-undo', args=[sell_transaction.id]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Insufficient remaining liquidity to undo this sell transaction.')
        self.assertTrue(TradeTransaction.objects.filter(id=sell_transaction.id).exists())
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10.00'))

    @override_settings(DEBUG=True)
    def test_reset_test_portfolio_only_clears_current_user_data(self):
        self.authenticate_as(self.user_a)
        TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=timezone.now(),
        )
        TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('120.0000'),
            realized_profit_loss=Decimal('20.0000'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('100.0000'),
        )
        Holding.objects.create(
            portfolio=self.portfolio_b,
            security=self.security_b,
            quantity=Decimal('2.000000'),
            average_cost=Decimal('500.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9900.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('portfolio-reset-test-data'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'reset')
        self.assertFalse(TradeTransaction.objects.filter(portfolio=self.portfolio_a).exists())
        self.assertFalse(Holding.objects.filter(portfolio=self.portfolio_a).exists())
        self.assertTrue(TradeTransaction.objects.filter(portfolio=self.portfolio_b).exists())
        self.assertTrue(Holding.objects.filter(portfolio=self.portfolio_b).exists())
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10000.00'))

    @override_settings(DEBUG=True)
    def test_reset_test_portfolio_returns_empty_transactions_and_holdings(self):
        self.authenticate_as(self.user_a)
        TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('100.0000'),
        )
        PortfolioCashFlow.objects.create(
            portfolio=self.portfolio_a,
            flow_type=PortfolioCashFlow.FlowType.DEPOSIT,
            amount=Decimal('50.0000'),
            effective_date=timezone.now(),
        )
        self.portfolio_a.available_funds = Decimal('9900.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        response = self.client.post(reverse('portfolio-reset-test-data'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['transactions'], [])
        self.assertEqual(response.data['holdings'], [])
        self.assertEqual(response.data['remaining_liquidity'], '10000.00')
        self.assertEqual(response.data['total_account_value'], '10000.00')
        self.assertEqual(response.data['cost_basis'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['realized_profit_loss'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['unrealized_profit_loss'], '0.00')
        self.assertEqual(response.data['portfolio_summary']['total_profit_loss'], '0.00')
        self.assertFalse(
            PortfolioCashFlow.objects.filter(
                portfolio=self.portfolio_a,
                flow_type=PortfolioCashFlow.FlowType.DEPOSIT,
            ).exists()
        )

    def test_undo_rollback_preserves_database_when_holding_update_fails(self):
        trade_transaction = TradeTransaction.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('1.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('2.00'),
            transaction_date=timezone.now(),
        )
        Holding.objects.create(
            portfolio=self.portfolio_a,
            security=self.security_a,
            quantity=Decimal('1.000000'),
            average_cost=Decimal('100.0000'),
        )
        self.portfolio_a.available_funds = Decimal('9898.00')
        self.portfolio_a.save(update_fields=['available_funds'])

        with patch(
            'portfolio.services.set_holding_from_reconstructed_position',
            side_effect=RuntimeError('forced failure'),
        ):
            with self.assertRaises(RuntimeError):
                undo_trade_transaction_for_user(self.user_a, trade_transaction.id)

        self.assertTrue(TradeTransaction.objects.filter(id=trade_transaction.id).exists())
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9898.00'))

    def test_existing_portfolio_initial_balance_backfill_uses_initial_cash_flow(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Initial Cash Flow Portfolio',
            available_funds=Decimal('500.00'),
        )
        PortfolioCashFlow.objects.create(
            portfolio=portfolio,
            flow_type=PortfolioCashFlow.FlowType.INITIAL,
            amount=Decimal('1234.5678'),
            effective_date=timezone.now(),
            is_estimated=True,
        )
        migration = import_module('portfolio.migrations.0005_portfolio_initial_balance')

        class SchemaEditor:
            connection = connection

        migration.backfill_initial_balance(django_apps, SchemaEditor())

        portfolio.refresh_from_db()
        self.assertEqual(portfolio.initial_balance, Decimal('1234.57'))

    def test_existing_portfolio_initial_balance_backfill_infers_from_transactions(self):
        portfolio = Portfolio.objects.create(
            user=self.user_a,
            name='Inferred Initial Balance Portfolio',
            available_funds=Decimal('1000.00'),
        )
        TradeTransaction.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.BUY,
            quantity=Decimal('2.000000'),
            price=Decimal('100.0000'),
            fee=Decimal('3.00'),
            transaction_date=timezone.now(),
        )
        TradeTransaction.objects.create(
            portfolio=portfolio,
            security=self.security_a,
            transaction_type=TradeTransaction.TransactionType.SELL,
            quantity=Decimal('1.000000'),
            price=Decimal('150.0000'),
            fee=Decimal('2.00'),
            transaction_date=timezone.now(),
        )
        migration = import_module('portfolio.migrations.0005_portfolio_initial_balance')

        class SchemaEditor:
            connection = connection

        migration.backfill_initial_balance(django_apps, SchemaEditor())

        portfolio.refresh_from_db()
        self.assertEqual(portfolio.initial_balance, Decimal('1055.00'))

    def test_new_portfolio_records_initial_balance(self):
        User = get_user_model()
        user = User.objects.create_user(username='initial_balance_user', password='pass')

        portfolio, created = get_or_create_primary_portfolio(
            user,
            defaults={
                'name': 'Initial Balance Portfolio',
                'available_funds': Decimal('4321.09'),
            },
        )

        self.assertTrue(created)
        self.assertEqual(portfolio.initial_balance, Decimal('4321.09'))
        cash_flow = PortfolioCashFlow.objects.get(portfolio=portfolio, flow_type=PortfolioCashFlow.FlowType.INITIAL)
        self.assertEqual(cash_flow.amount, Decimal('4321.0900'))
        self.assertFalse(cash_flow.is_estimated)
