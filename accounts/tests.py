from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from portfolio.models import Portfolio
from watchlist.models import Watchlist


class AuthApiTests(APITestCase):
    def setUp(self):
        self.User = get_user_model()

    def register_payload(self, **overrides):
        payload = {
            'username': 'user_a',
            'email': 'user_a@example.com',
            'password': 'StrongPassword123',
            'password_confirm': 'StrongPassword123',
        }
        payload.update(overrides)
        return payload

    def test_register_creates_regular_user_without_password_in_response(self):
        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('password', response.data)
        user = self.User.objects.get(username='user_a')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_usable_password())
        self.assertNotEqual(user.password, 'StrongPassword123')
        self.assertEqual(Portfolio.objects.filter(user=user).count(), 1)
        self.assertEqual(Portfolio.objects.get(user=user).name, 'My Portfolio')
        self.assertEqual(Watchlist.objects.filter(user=user).count(), 1)
        self.assertEqual(Watchlist.objects.get(user=user).name, 'My Watchlist')

    def test_duplicate_username_registration_fails(self):
        self.User.objects.create_user(username='user_a', password='StrongPassword123')

        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', response.data)
        self.assertEqual(response.data['username'][0], 'This username already exists.')

    def test_duplicate_email_registration_fails(self):
        self.User.objects.create_user(
            username='existing_user',
            email='user_a@example.com',
            password='StrongPassword123',
        )

        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(username='user_b'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
        self.assertEqual(response.data['email'][0], 'This email is already registered.')

    def test_password_mismatch_registration_fails(self):
        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(password_confirm='DifferentPassword123'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password_confirm', response.data)
        self.assertEqual(response.data['password_confirm'][0], 'Passwords do not match.')

    def test_weak_password_registration_fails(self):
        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(password='short', password_confirm='short'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_register_payload_cannot_create_staff_or_superuser(self):
        response = self.client.post(
            reverse('auth-register'),
            self.register_payload(is_staff=True, is_superuser=True),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = self.User.objects.get(username='user_a')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_login_with_valid_credentials_returns_current_user(self):
        user = self.User.objects.create_user(
            username='user_a',
            email='user_a@example.com',
            password='StrongPassword123',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'username': 'user_a', 'password': 'StrongPassword123'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'user_a')
        self.assertEqual(response.data['email'], 'user_a@example.com')
        self.assertIs(response.data['is_authenticated'], True)
        self.assertIn('sessionid', response.client.cookies)
        self.assertEqual(Portfolio.objects.filter(user=user).count(), 1)
        self.assertEqual(Watchlist.objects.filter(user=user).count(), 1)

    def test_repeated_login_does_not_create_duplicate_portfolio(self):
        user = self.User.objects.create_user(username='user_a', password='StrongPassword123')

        first_response = self.client.post(
            reverse('auth-login'),
            {'username': 'user_a', 'password': 'StrongPassword123'},
            format='json',
        )
        second_response = self.client.post(
            reverse('auth-login'),
            {'username': 'user_a', 'password': 'StrongPassword123'},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(Portfolio.objects.filter(user=user).count(), 1)
        self.assertEqual(Watchlist.objects.filter(user=user).count(), 1)

    def test_two_registered_users_receive_different_internal_portfolios(self):
        first_response = self.client.post(
            reverse('auth-register'),
            self.register_payload(username='user_a', email='user_a@example.com'),
            format='json',
        )
        second_response = self.client.post(
            reverse('auth-register'),
            self.register_payload(username='user_b', email='user_b@example.com'),
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        user_a = self.User.objects.get(username='user_a')
        user_b = self.User.objects.get(username='user_b')
        portfolio_a = Portfolio.objects.get(user=user_a)
        portfolio_b = Portfolio.objects.get(user=user_b)
        self.assertNotEqual(portfolio_a.id, portfolio_b.id)

    def test_login_with_invalid_password_fails(self):
        self.User.objects.create_user(username='user_a', password='StrongPassword123')

        response = self.client.post(
            reverse('auth-login'),
            {'username': 'user_a', 'password': 'WrongPassword123'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('sessionid', response.client.cookies)

    def test_me_requires_login_and_returns_current_user(self):
        user = self.User.objects.create_user(
            username='user_a',
            email='user_a@example.com',
            password='StrongPassword123',
        )

        anonymous_response = self.client.get(reverse('auth-me'))
        self.assertIn(
            anonymous_response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

        self.client.login(username='user_a', password='StrongPassword123')
        response = self.client.get(reverse('auth-me'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], user.id)
        self.assertEqual(response.data['username'], 'user_a')
        self.assertEqual(response.data['email'], 'user_a@example.com')
        self.assertIs(response.data['is_authenticated'], True)
        self.assertNotIn('password', response.data)
        self.assertNotIn('is_superuser', response.data)
        self.assertNotIn('groups', response.data)

    def test_logged_in_user_can_access_only_their_own_portfolios(self):
        user_a = self.User.objects.create_user(username='user_a', password='StrongPassword123')
        user_b = self.User.objects.create_user(username='user_b', password='StrongPassword123')
        portfolio_a = Portfolio.objects.create(
            user=user_a,
            name='User A Portfolio',
            available_funds=Decimal('1000.00'),
        )
        portfolio_b = Portfolio.objects.create(
            user=user_b,
            name='User B Portfolio',
            available_funds=Decimal('1000.00'),
        )

        self.client.login(username='user_a', password='StrongPassword123')
        list_response = self.client.get(reverse('portfolio-list'))
        detail_response = self.client.get(reverse('portfolio-detail', args=[portfolio_b.id]))

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in list_response.data], [portfolio_a.id])
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_logout_invalidates_session(self):
        self.User.objects.create_user(username='user_a', password='StrongPassword123')
        self.client.login(username='user_a', password='StrongPassword123')

        me_before_logout = self.client.get(reverse('auth-me'))
        logout_response = self.client.post(reverse('auth-logout'))
        me_after_logout = self.client.get(reverse('auth-me'))
        portfolio_after_logout = self.client.get(reverse('portfolio-list'))

        self.assertEqual(me_before_logout.status_code, status.HTTP_200_OK)
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
        self.assertIn(
            me_after_logout.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            portfolio_after_logout.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_csrf_endpoint_sets_cookie(self):
        response = self.client.get(reverse('auth-csrf'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('csrftoken', response.client.cookies)


class AdminLoginTests(TestCase):
    def test_admin_login_still_works_for_superuser(self):
        User = get_user_model()
        User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='StrongPassword123',
        )
        client = Client()

        self.assertTrue(client.login(username='admin', password='StrongPassword123'))
        response = client.get('/admin/')

        self.assertEqual(response.status_code, 200)
