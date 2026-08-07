from django.contrib import admin

from .models import Holding, Portfolio, PortfolioCashFlow, TradeTransaction


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'available_funds', 'base_currency', 'created_at']
    list_filter = ['base_currency', 'created_at']
    search_fields = ['name', 'description', 'user__username', 'user__email']
    ordering = ['-created_at']


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'security', 'quantity', 'average_cost', 'updated_at']
    list_filter = ['updated_at']
    search_fields = [
        'portfolio__name',
        'portfolio__user__username',
        'portfolio__user__email',
        'security__symbol',
        'security__name',
    ]


@admin.register(PortfolioCashFlow)
class PortfolioCashFlowAdmin(admin.ModelAdmin):
    list_display = ['portfolio', 'flow_type', 'amount', 'effective_date', 'is_estimated', 'created_at']
    list_filter = ['flow_type', 'is_estimated', 'effective_date']
    search_fields = [
        'portfolio__name',
        'portfolio__user__username',
        'portfolio__user__email',
        'note',
    ]
    ordering = ['-effective_date', '-created_at']


@admin.register(TradeTransaction)
class TradeTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'portfolio',
        'security',
        'transaction_type',
        'quantity',
        'price',
        'cash_amount',
        'fee',
        'realized_profit_loss',
        'transaction_date',
    ]
    list_filter = ['transaction_type', 'portfolio', 'security', 'transaction_date']
    search_fields = [
        'portfolio__name',
        'portfolio__user__username',
        'portfolio__user__email',
        'security__symbol',
        'security__name',
        'notes',
    ]
    ordering = ['-transaction_date', '-created_at']
