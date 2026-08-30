from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import PersistenceError
from app.db.models import (
    EvidenceRecord,
    LeadFactRecord,
    LeadRecord,
    ResearchSessionRecord,
    ScoreResultRecord,
)
from app.schemas.lead import LeadInput, LeadScoreResponse


class LeadRepository(Protocol):
    async def save(self, lead: LeadInput, result: LeadScoreResponse) -> None: ...

    async def get(self, lead_id: str) -> LeadScoreResponse | None: ...


class InMemoryLeadRepository:
    def __init__(self) -> None:
        self._records: dict[str, LeadScoreResponse] = {}
        self._lock = asyncio.Lock()

    async def save(self, lead: LeadInput, result: LeadScoreResponse) -> None:
        del lead
        async with self._lock:
            self._records[result.lead_id] = result.model_copy(deep=True)

    async def get(self, lead_id: str) -> LeadScoreResponse | None:
        async with self._lock:
            result = self._records.get(lead_id)
            return result.model_copy(deep=True) if result else None


class SqlAlchemyLeadRepository:
    """PostgreSQL-ready repository that stores reproducible score artifacts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def save(self, lead: LeadInput, result: LeadScoreResponse) -> None:
        session_id = f"rs_{uuid4().hex}"
        try:
            async with self._session_factory.begin() as session:
                session.add(
                    LeadRecord(
                        id=result.lead_id,
                        input_json=lead.model_dump(mode="json"),
                        created_at=result.created_at,
                    )
                )
                session.add(
                    ResearchSessionRecord(
                        id=session_id,
                        lead_id=result.lead_id,
                        source_count=len(result.sources),
                        warnings_json=result.research_warnings,
                        created_at=result.created_at,
                    )
                )
                session.add_all(
                    [
                        EvidenceRecord(
                            research_session_id=session_id,
                            evidence_id=item.id,
                            source_url=str(item.source_url),
                            source_type=item.source_type,
                            provider=item.provider,
                            title=item.title,
                            excerpt=item.excerpt,
                            relevance=item.relevance,
                            reliability=item.reliability,
                            content_digest=item.content_digest,
                            created_at=item.retrieved_at,
                        )
                        for item in result.sources
                    ]
                )
                session.add_all(
                    [
                        LeadFactRecord(
                            research_session_id=session_id,
                            field=item.field,
                            value_json=item.value,
                            status=item.status.value,
                            confidence=item.confidence,
                            evidence_ids_json=item.evidence_ids,
                            alternatives_json=item.alternatives,
                            rationale=item.rationale,
                        )
                        for item in result.facts
                    ]
                )
                session.add(
                    ScoreResultRecord(
                        lead_id=result.lead_id,
                        score=result.score,
                        classification=result.classification.value,
                        research_confidence=result.research_confidence,
                        scoring_confidence=result.scoring_confidence,
                        result_json=result.model_dump(mode="json"),
                        created_at=result.created_at,
                    )
                )
        except SQLAlchemyError as exc:
            raise PersistenceError("Lead result could not be stored") from exc

    async def get(self, lead_id: str) -> LeadScoreResponse | None:
        try:
            async with self._session_factory() as session:
                statement = select(ScoreResultRecord.result_json).where(
                    ScoreResultRecord.lead_id == lead_id
                )
                payload = await session.scalar(statement)
        except SQLAlchemyError as exc:
            raise PersistenceError("Lead result could not be retrieved") from exc
        return LeadScoreResponse.model_validate(payload) if payload else None
