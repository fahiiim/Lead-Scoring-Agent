from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.dependencies import get_lead_service
from app.schemas.lead import HealthResponse, LeadInput, LeadScoreResponse
from app.services.lead_service import LeadScoringService

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Service health check",
)
async def health() -> HealthResponse:
    from app import __version__

    return HealthResponse(status="ok", version=__version__)


@router.post(
    "/api/v1/leads/score",
    response_model=LeadScoreResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["leads"],
    summary="Research and score a lead",
)
async def score_lead(
    lead: LeadInput,
    service: Annotated[LeadScoringService, Depends(get_lead_service)],
) -> LeadScoreResponse:
    return await service.score_lead(lead)


@router.get(
    "/api/v1/leads/{lead_id}",
    response_model=LeadScoreResponse,
    tags=["leads"],
    summary="Retrieve a scored lead",
)
async def get_lead(
    lead_id: Annotated[str, Path(pattern=r"^lead_[a-f0-9]{32}$")],
    service: Annotated[LeadScoringService, Depends(get_lead_service)],
) -> LeadScoreResponse:
    return await service.get_lead(lead_id)
