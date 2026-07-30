from django.db import transaction

from .models import Watchlist


DEFAULT_WATCHLIST_NAME = 'My Watchlist'


def get_primary_watchlist(user):
    if not user or not user.is_authenticated:
        return None

    return (
        Watchlist.objects
        .filter(user=user)
        .order_by('created_at', 'id')
        .first()
    )


def get_or_create_primary_watchlist(user, defaults=None):
    defaults = defaults or {}

    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        watchlist = get_primary_watchlist(user)
        if watchlist:
            return watchlist, False

        create_defaults = {
            'name': defaults.get('name') or DEFAULT_WATCHLIST_NAME,
        }
        return Watchlist.objects.create(user=user, **create_defaults), True
