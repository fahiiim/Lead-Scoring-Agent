from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from app.agents.extractor import FactExtractor
from app.core.config import Settings
from app.core.exceptions import LeadNotFoundError
from app.models.domain import Evidence, FactStatus, LeadFact
from app.repositories.leads import LeadRepository
from app.research.base import LeadResearcher
from app.schemas.lead import LeadInput, LeadScoreResponse
from app.scoring.engine import ScoringEngine
from app.scoring.profile import build_scoring_profile

logger = logging.getLogger(__name__)


class LeadScoringService:
    def __init__(
        self,
        orchestrator: LeadResearcher,
        extractor: FactExtractor,
        scoring_engine: ScoringEngine,
        repository: LeadRepository,
        settings: Settings,
    ) -> None:
        self._orchestrator = orchestrator
        self._extractor = extractor
        self._scoring_engine = scoring_engine
        self._repository = repository
        self._settings = settings

    async def score_lead(self, lead: LeadInput) -> LeadScoreResponse:
        lead_id = f"lead_{uuid4().hex}"
        logger.info("Lead research started", extra={"lead_id": lead_id})
        started = monotonic()
        bundle = await self._orchestrator.research(lead)
        extraction = await self._extractor.extract(lead, bundle.evidence)

        scoring_started = monotonic()
        profile = build_scoring_profile(self._settings, lead)
        outcome = self._scoring_engine.score(lead, extraction.facts, profile)
        scoring_duration = round((monotonic() - scoring_started) * 1_000)
        research_confidence = calculate_research_confidence(
            bundle.evidence,
            extraction.facts,
        )
        warnings = list(dict.fromkeys([*bundle.provider_failures, *extraction.warnings]))
        response = LeadScoreResponse(
            lead_id=lead_id,
            score=outcome.score,
            classification=outcome.classification,
            research_confidence=research_confidence,
            scoring_confidence=outcome.scoring_confidence,
            summary=outcome.summary,
            factors=outcome.factors,
            facts=extraction.facts,
            sources=bundle.evidence,
            research_warnings=warnings,
            created_at=datetime.now(UTC),
        )
        await self._repository.save(lead, response)
        logger.info(
            "Lead scoring completed",
            extra={
                "lead_id": lead_id,
                "source_count": len(bundle.evidence),
                "research_duration_ms": round((monotonic() - started) * 1_000),
                "scoring_duration_ms": scoring_duration,
                "score": response.score,
                "classification": response.classification.value,
                "research_cache_hit": bundle.cache_hit,
            },
        )
        return response

    async def get_lead(self, lead_id: str) -> LeadScoreResponse:
        result = await self._repository.get(lead_id)
        if result is None:
            raise LeadNotFoundError("Lead result was not found")
        return result


def calculate_research_confidence(
    evidence: list[Evidence],
    facts: list[LeadFact],
) -> float:
    if not evidence:
        return 0.0
    source_types = {item.source_type for item in evidence}
    diversity = min(1.0, len(source_types) / 3)
    reliability = sum(item.reliability for item in evidence) / len(evidence)
    important_fields = {
        "designation",
        "person_company",
        "company_industry",
        "company_employee_count",
        "company_reputation",
        "business_relevance",
    }
    established = [
        fact
        for fact in facts
        if fact.field in important_fields
        and fact.status not in {FactStatus.UNKNOWN, FactStatus.CONFLICTING}
        and fact.evidence_ids
    ]
    coverage = len({fact.field for fact in established}) / len(important_fields)
    fact_confidence = (
        sum(fact.confidence for fact in established) / len(established) if established else 0.0
    )
    confidence = 0.25 * diversity + 0.25 * reliability + 0.25 * coverage + 0.25 * fact_confidence
    return round(min(1.0, confidence), 3)
