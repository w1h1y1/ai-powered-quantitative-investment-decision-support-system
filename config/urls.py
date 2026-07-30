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

from market.views import SecurityDailyMarketDataView, SecurityViewSet
from portfolio.views import HoldingViewSet, PortfolioSummaryView, PortfolioViewSet, TradeTransactionViewSet
from watchlist.views import WatchlistItemViewSet, WatchlistViewSet

router = DefaultRouter()
router.register('securities', SecurityViewSet, basename='security')
router.register('portfolios', PortfolioViewSet, basename='portfolio')
router.register('holdings', HoldingViewSet, basename='holding')
router.register('transactions', TradeTransactionViewSet, basename='transaction')
router.register('watchlists', WatchlistViewSet, basename='watchlist')
router.register('watchlist-items', WatchlistItemViewSet, basename='watchlist-item')

urlpatterns = [
    path('api/auth/', include('accounts.urls')),
    path('api/market-data/daily/', SecurityDailyMarketDataView.as_view(), name='market-data-daily'),
    path('api/portfolio/summary/', PortfolioSummaryView.as_view(), name='portfolio-summary'),
    path('api/', include(router.urls)),
    path('', include('dashboard.urls')),
    path('admin/', admin.site.urls),
]
