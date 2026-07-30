from django.contrib import admin

from .models import Watchlist, WatchlistItem


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'user__username', 'user__email']
    ordering = ['-created_at']


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ['watchlist', 'security', 'added_at']
    list_filter = ['added_at']
    search_fields = [
        'watchlist__name',
        'watchlist__user__username',
        'watchlist__user__email',
        'security__symbol',
        'security__name',
    ]
    ordering = ['-added_at']
