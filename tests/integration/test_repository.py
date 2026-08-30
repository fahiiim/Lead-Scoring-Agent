from __future__ import annotations

from datetime import datetime, timezone

from app.db.base import Database
from app.models.domain import LeadClassification
from app.repositories.leads import SqlAlchemyLeadRepository
from app.schemas.lead import LeadInput, LeadScoreResponse


async def test_sqlalchemy_repository_round_trip(
    evidence_factory: object,
    fact_factory: object,
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
        facts=[fact_factory()],  # type: ignore[operator]
        sources=[evidence_factory()],  # type: ignore[operator]
        created_at=datetime.now(timezone.utc),
    )

    await repository.save(lead, result)
    stored = await repository.get(result.lead_id)

    assert stored == result
    await database.close()
