from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from market.models import Security

from .models import Watchlist, WatchlistItem


class WatchlistModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='watcher', password='pass')
        self.security = Security.objects.create(
            symbol='VOO',
            name='Vanguard S&P 500 ETF',
            asset_type=Security.AssetType.ETF,
            exchange='NYSE Arca',
            currency='USD',
        )

    def test_watchlist_can_be_created_and_has_readable_string(self):
        watchlist = Watchlist.objects.create(user=self.user, name=' Main Watchlist ')

        self.assertEqual(watchlist.name, 'Main Watchlist')
        self.assertEqual(str(watchlist), 'Main Watchlist (watcher)')

    def test_user_cannot_create_duplicate_watchlist_name(self):
        Watchlist.objects.create(user=self.user, name='Income')

        with self.assertRaises(IntegrityError), transaction.atomic():
            Watchlist.objects.create(user=self.user, name='Income')

    def test_watchlist_item_can_be_created_and_has_readable_string(self):
        watchlist = Watchlist.objects.create(user=self.user, name='Core ETFs')
        item = WatchlistItem.objects.create(watchlist=watchlist, security=self.security)

        self.assertEqual(str(item), 'Core ETFs - VOO')

    def test_security_cannot_be_added_twice_to_same_watchlist(self):
        watchlist = Watchlist.objects.create(user=self.user, name='Core ETFs')
        WatchlistItem.objects.create(watchlist=watchlist, security=self.security)

        with self.assertRaises(IntegrityError), transaction.atomic():
            WatchlistItem.objects.create(watchlist=watchlist, security=self.security)
