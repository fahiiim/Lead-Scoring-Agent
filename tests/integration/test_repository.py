from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.db.base import Database
from app.models.domain import Evidence, LeadClassification, LeadFact
from app.repositories.leads import SqlAlchemyLeadRepository
from app.schemas.lead import LeadInput, LeadScoreResponse


async def test_sqlalchemy_repository_round_trip(
    evidence_factory: Callable[..., Evidence],
    fact_factory: Callable[..., LeadFact],
) -> None:
    database = Database("sqlite:///:memory:")
    await database.create_schema()
    repository = SqlAlchemyLeadRepository(database.session_factory, database.engine)
    lead = LeadInput(name="Jane Doe", company="Example Corp", designation="CEO")
    result = LeadScoreResponse(
        lead_id="lead_0123456789abcdef0123456789abcdef",
        score=85,
        classification=LeadClassification.HOT,
        research_confidence=0.8,
        scoring_confidence=0.9,
        summary="Qualified lead.",
        factors=[],
        facts=[fact_factory()],
        sources=[evidence_factory()],
        created_at=datetime.now(UTC),
    )

    await repository.save(lead, result)
    stored = await repository.get(result.lead_id)

    assert stored == result
    await database.close()
