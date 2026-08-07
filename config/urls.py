"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from backtest.views import BacktestRunView
from market.views import (
    MarketSummaryView,
    SecurityDailyMarketDataView,
    SecurityLatestQuoteView,
    SecurityLatestQuotesView,
    SecurityViewSet,
)
from portfolio.views import (
    HoldingViewSet,
    PortfolioPerformanceView,
    PortfolioResetTestDataView,
    PortfolioSummaryView,
    PortfolioViewSet,
    TradeTransactionViewSet,
)
from watchlist.views import WatchlistAddSymbolView, WatchlistItemViewSet, WatchlistSummaryView, WatchlistViewSet

router = DefaultRouter()
router.register('securities', SecurityViewSet, basename='security')
router.register('portfolios', PortfolioViewSet, basename='portfolio')
router.register('holdings', HoldingViewSet, basename='holding')
router.register('transactions', TradeTransactionViewSet, basename='transaction')
router.register('watchlists', WatchlistViewSet, basename='watchlist')
router.register('watchlist-items', WatchlistItemViewSet, basename='watchlist-item')

urlpatterns = [
    path('api/auth/', include('accounts.urls')),
    path('api/backtests/run/', BacktestRunView.as_view(), name='backtest-run'),
    path('api/market-data/summary/', MarketSummaryView.as_view(), name='market-data-summary'),
    path('api/market-data/quote/', SecurityLatestQuoteView.as_view(), name='market-data-quote'),
    path('api/market-data/quotes/', SecurityLatestQuotesView.as_view(), name='market-data-quotes'),
    path('api/market-data/daily/', SecurityDailyMarketDataView.as_view(), name='market-data-daily'),
    path('api/portfolio/summary/', PortfolioSummaryView.as_view(), name='portfolio-summary'),
    path('api/portfolio/performance/', PortfolioPerformanceView.as_view(), name='portfolio-performance'),
    path('api/portfolio/reset-test-data/', PortfolioResetTestDataView.as_view(), name='portfolio-reset-test-data'),
    path('api/watchlist/summary/', WatchlistSummaryView.as_view(), name='watchlist-summary'),
    path('api/watchlist/add-symbol/', WatchlistAddSymbolView.as_view(), name='watchlist-add-symbol'),
    path('api/', include(router.urls)),
    path('', include('dashboard.urls')),
    path('admin/', admin.site.urls),
]
