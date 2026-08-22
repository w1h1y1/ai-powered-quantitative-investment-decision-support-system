from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from backtest.services import (
    BacktestDataError,
    BacktestInsufficientHistoryError,
    BacktestMarketDataRateLimited,
    BacktestMarketDataUnavailable,
)
from backtest.strategy_evaluation_service import StrategyEvaluationContractError
from market.regime_service import (
    MarketRegimeDataRateLimited,
    MarketRegimeDataUnavailable,
)
from market.services import MarketDataRateLimited, MarketDataUnavailable

from .agent_context_service import build_agent_context
from .agent_analysis_service import run_agent_analysis
from .analysis_persistence import (
    get_latest_successful_analysis,
    save_successful_analysis,
)
from .investment_agent_service import run_investment_agent
from .serializers import AgentContextQuerySerializer
from .unified_context_service import build_unified_agent_context


class AgentContextView(APIView):
    """Return the deterministic Agent Context for one security.

    This endpoint is intentionally separate from the future Investment Agent
    analysis endpoint: it exposes only the structured evidence an LLM layer
    will later consume, without any LLM call.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AgentContextQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = build_agent_context(serializer.resolved_security)
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except StrategyEvaluationContractError as exc:
            return Response({'detail': str(exc)}, status=400)
        except (MarketRegimeDataRateLimited, BacktestMarketDataRateLimited) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=429)
        except (MarketRegimeDataUnavailable, BacktestMarketDataUnavailable) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(payload)


class InvestmentAgentView(APIView):
    """Return deterministic Agent Context plus a structured LLM explanation.

    The request only submits a symbol.  The server builds the Agent Context,
    constructs the LLM payload, calls the configured provider, validates the
    structured analysis schema, and falls back to a deterministic summary when
    the LLM layer fails.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AgentContextQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = run_investment_agent(serializer.resolved_security)
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except StrategyEvaluationContractError as exc:
            return Response({'detail': str(exc)}, status=400)
        except (MarketRegimeDataRateLimited, BacktestMarketDataRateLimited) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=429)
        except (MarketRegimeDataUnavailable, BacktestMarketDataUnavailable) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(payload)


class UnifiedAgentContextView(APIView):
    """Return the unified deterministic context for the future Agent layer."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = AgentContextQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            payload = build_unified_agent_context(
                serializer.resolved_security,
                request.user,
            )
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except StrategyEvaluationContractError as exc:
            return Response({'detail': str(exc)}, status=400)
        except (MarketRegimeDataRateLimited, BacktestMarketDataRateLimited) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=429)
        except (MarketRegimeDataUnavailable, BacktestMarketDataUnavailable) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        return Response(payload)


class AgentAnalysisView(APIView):
    """POST symbol -> quantitative preliminary view -> DeepSeek final synthesis."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AgentContextQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = run_agent_analysis(
                serializer.resolved_security,
                request.user,
            )
        except BacktestInsufficientHistoryError as exc:
            return Response({'detail': str(exc), **exc.details}, status=400)
        except BacktestDataError as exc:
            return Response({'detail': str(exc)}, status=400)
        except StrategyEvaluationContractError as exc:
            return Response({'detail': str(exc)}, status=400)
        except (MarketRegimeDataRateLimited, BacktestMarketDataRateLimited) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=429)
        except (MarketRegimeDataUnavailable, BacktestMarketDataUnavailable) as exc:
            details = getattr(exc, 'details', {})
            return Response({'detail': str(exc), **details}, status=503)
        except MarketDataRateLimited as exc:
            return Response({'detail': str(exc)}, status=429)
        except MarketDataUnavailable as exc:
            return Response({'detail': str(exc)}, status=503)

        if payload.get('analysis_status') == 'success' and payload.get('analysis'):
            analysis_record = save_successful_analysis(
                user=request.user,
                security=serializer.resolved_security,
                symbol=payload.get('symbol'),
                as_of_date=payload.get('metadata', {}).get('as_of_date'),
                context_version=payload.get('context_version'),
                analysis_version=payload.get('metadata', {}).get('analysis_version'),
                provider=payload.get('metadata', {}).get('provider'),
                model=payload.get('metadata', {}).get('model'),
                analysis=payload.get('analysis'),
            )
            payload['generated_at'] = analysis_record.generated_at.isoformat()

        return Response(payload)


class AgentAnalysisLatestView(APIView):
    """Return the latest successful analysis for the current user + symbol."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = AgentContextQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        security = serializer.resolved_security
        analysis_record = get_latest_successful_analysis(request.user, security)

        if analysis_record is None:
            return Response({
                'available': False,
                'symbol': security.symbol,
                'analysis': None,
            })

        return Response({
            'available': True,
            'symbol': analysis_record.symbol,
            'generated_at': analysis_record.generated_at.isoformat(),
            'as_of_date': (
                analysis_record.as_of_date.isoformat()
                if analysis_record.as_of_date
                else None
            ),
            'context_version': analysis_record.context_version,
            'analysis_version': analysis_record.analysis_version,
            'provider': analysis_record.provider,
            'model': analysis_record.model,
            'analysis': analysis_record.analysis,
        })
