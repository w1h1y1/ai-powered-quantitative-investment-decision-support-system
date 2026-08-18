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

from agent.views import (
    AgentAnalysisView,
    AgentContextView,
    InvestmentAgentView,
    UnifiedAgentContextView,
)
from backtest.views import BacktestRunView, StrategyEvaluationView
from market.views import (
    MarketRegimeView,
    MarketSummaryView,
    SecurityDailyMarketDataView,
    SecurityLatestQuoteView,
    SecurityLatestQuotesView,
    SecurityViewSet,
    StrategySelectionView,
)
from portfolio.views import (
    PortfolioFundingView,
    HoldingViewSet,
    PortfolioPerformanceView,
    PortfolioResetTestDataView,
    PortfolioSummaryView,
    PortfolioViewSet,
    TradeTransactionViewSet,
)
from prediction.views import PredictionGenerateView
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
    path('api/agent-context/', AgentContextView.as_view(), name='agent-context'),
    path('api/agent/context/', UnifiedAgentContextView.as_view(), name='unified-agent-context'),
    path('api/agent/analyze/', AgentAnalysisView.as_view(), name='agent-analyze'),
    path('api/investment-agent/', InvestmentAgentView.as_view(), name='investment-agent'),
    path('api/backtests/run/', BacktestRunView.as_view(), name='backtest-run'),
    path('api/strategy-evaluation/', StrategyEvaluationView.as_view(), name='strategy-evaluation'),
    path('api/predictions/generate/', PredictionGenerateView.as_view(), name='prediction-generate'),
    path('api/market-regime/', MarketRegimeView.as_view(), name='market-regime'),
    path('api/strategy-selection/', StrategySelectionView.as_view(), name='strategy-selection'),
    path('api/market-data/summary/', MarketSummaryView.as_view(), name='market-data-summary'),
    path('api/market-data/quote/', SecurityLatestQuoteView.as_view(), name='market-data-quote'),
    path('api/market-data/quotes/', SecurityLatestQuotesView.as_view(), name='market-data-quotes'),
    path('api/market-data/daily/', SecurityDailyMarketDataView.as_view(), name='market-data-daily'),
    path('api/portfolio/summary/', PortfolioSummaryView.as_view(), name='portfolio-summary'),
    path('api/portfolio/performance/', PortfolioPerformanceView.as_view(), name='portfolio-performance'),
    path('api/portfolio/funding/', PortfolioFundingView.as_view(), name='portfolio-funding'),
    path('api/portfolio/reset-test-data/', PortfolioResetTestDataView.as_view(), name='portfolio-reset-test-data'),
    path('api/watchlist/summary/', WatchlistSummaryView.as_view(), name='watchlist-summary'),
    path('api/watchlist/add-symbol/', WatchlistAddSymbolView.as_view(), name='watchlist-add-symbol'),
    path('api/', include(router.urls)),
    path('', include('dashboard.urls')),
    path('admin/', admin.site.urls),
]
