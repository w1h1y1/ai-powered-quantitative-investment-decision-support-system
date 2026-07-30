from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from market.models import Security

from .models import Watchlist, WatchlistItem


class WatchlistApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='watch_api_user_a', password='pass')
        self.user_b = User.objects.create_user(username='watch_api_user_b', password='pass')
        self.security_a = Security.objects.create(
            symbol='AAPL',
            name='Apple Inc.',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )
        self.security_b = Security.objects.create(
            symbol='MSFT',
            name='Microsoft Corporation',
            asset_type=Security.AssetType.STOCK,
            exchange='NASDAQ',
            currency='USD',
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_list_creates_default_watchlist_for_authenticated_user(self):
        self.authenticate_as(self.user_a)

        response = self.client.get(reverse('watchlist-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Watchlist.objects.filter(user=self.user_a).count(), 1)
        watchlist = Watchlist.objects.get(user=self.user_a)
        self.assertEqual(watchlist.name, 'My Watchlist')
        self.assertEqual(response.data[0]['id'], watchlist.id)
        self.assertEqual(response.data[0]['items'], [])

    def test_watchlist_item_list_can_be_filtered_to_current_users_watchlist(self):
        watchlist_a = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        item_a = WatchlistItem.objects.create(watchlist=watchlist_a, security=self.security_a)
        WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        self.authenticate_as(self.user_a)

        own_response = self.client.get(reverse('watchlist-item-list'), {'watchlist': watchlist_a.id})
        other_response = self.client.get(reverse('watchlist-item-list'), {'watchlist': watchlist_b.id})

        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in own_response.data], [item_a.id])
        self.assertEqual(other_response.status_code, status.HTTP_200_OK)
        self.assertEqual(other_response.data, [])

    def test_duplicate_security_in_same_watchlist_returns_validation_error(self):
        watchlist = Watchlist.objects.create(user=self.user_a, name='User A Watchlist')
        WatchlistItem.objects.create(watchlist=watchlist, security=self.security_a)
        self.authenticate_as(self.user_a)

        response = self.client.post(
            reverse('watchlist-item-list'),
            {
                'watchlist': watchlist.id,
                'security_id': self.security_a.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('security_id', response.data)
        self.assertEqual(
            response.data['security_id'][0],
            'This security is already in this watchlist.',
        )
        self.assertEqual(WatchlistItem.objects.filter(watchlist=watchlist).count(), 1)

    def test_user_cannot_delete_another_users_watchlist_item(self):
        watchlist_b = Watchlist.objects.create(user=self.user_b, name='User B Watchlist')
        item_b = WatchlistItem.objects.create(watchlist=watchlist_b, security=self.security_b)
        self.authenticate_as(self.user_a)

        response = self.client.delete(reverse('watchlist-item-detail', args=[item_b.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WatchlistItem.objects.filter(id=item_b.id).exists())
