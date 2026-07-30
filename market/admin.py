from django.contrib import admin

from .models import Security, SecurityDailyPrice


@admin.register(Security)
class SecurityAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'asset_type', 'exchange', 'currency', 'is_active']
    list_filter = ['asset_type', 'exchange', 'currency', 'is_active']
    search_fields = ['symbol', 'name', 'exchange']
    ordering = ['symbol']


@admin.register(SecurityDailyPrice)
class SecurityDailyPriceAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'security',
        'date',
        'open',
        'high',
        'low',
        'close',
        'volume',
        'source',
    ]
    list_filter = ['security', 'source']
    search_fields = ['security__symbol']
    ordering = ['-date']
    date_hierarchy = 'date'
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
