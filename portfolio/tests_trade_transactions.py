from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from .models import Holding, Portfolio, TradeTransaction


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
        )
        self.portfolio_b = Portfolio.objects.create(
            user=self.user_b,
            name='User B Portfolio',
            available_funds=Decimal('5000.00'),
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

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

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
        self.assertEqual(response.data['portfolio'], self.portfolio_a.id)
        self.assertEqual(response.data['security']['symbol'], 'MSFT')
        holding = Holding.objects.get(portfolio=self.portfolio_a, security=self.security_a)
        self.assertEqual(holding.quantity, Decimal('1.000000'))
        self.assertEqual(holding.average_cost, Decimal('400.0000'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9600.00'))

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
        self.assertEqual([item['id'] for item in user_a_response.data], [user_a_transaction.id])
        self.assertEqual(user_b_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in user_b_response.data], [self.transaction_b.id])

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
        self.assertEqual(holding.average_cost, Decimal('400.9091'))
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('9588.00'))

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
        self.portfolio_a.refresh_from_db()
        self.assertEqual(self.portfolio_a.available_funds, Decimal('10821.00'))

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
