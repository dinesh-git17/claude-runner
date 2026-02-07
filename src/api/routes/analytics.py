"""Analytics REST API endpoint."""

from fastapi import APIRouter

from api.content.repositories.analytics import compute_analytics
from api.content.schemas import AnalyticsSummary

router = APIRouter(tags=["analytics"])


@router.get(
    "/analytics",
    response_model=AnalyticsSummary,
    summary="Get analytics summary",
    description="Returns aggregated analytics across thoughts, dreams, and sessions.",
)
async def get_analytics() -> AnalyticsSummary:
    """Get complete analytics summary.

    Returns:
        AnalyticsSummary with all aggregated metrics.
    """
    return compute_analytics()
