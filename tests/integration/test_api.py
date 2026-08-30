from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import FastAPI

from app.api.dependencies import ApplicationContainer
from app.core.config import Settings
from app.main import create_app
from app.models.domain import (
    Evidence,
    FactExtractionResult,
    FactStatus,
    LeadFact,
    ResearchBundle,
)
from app.providers.website import SafeHttpFetcher
from app.repositories.leads import InMemoryLeadRepository
from app.schemas.lead import LeadInput
from app.scoring.engine import ScoringEngine
from app.services.lead_service import LeadScoringService


class FakeOrchestrator:
    def __init__(self, evidence: Evidence) -> None:
        self._evidence = evidence

    async def research(self, lead: LeadInput) -> ResearchBundle:
        del lead
        return ResearchBundle(evidence=[self._evidence])


class StaticExtractor:
    async def extract(
        self,
        lead: LeadInput,
        evidence: list[Evidence],
    ) -> FactExtractionResult:
        del lead
        evidence_ids = [item.id for item in evidence]
        facts = [
            LeadFact(
                field="designation",
                value="CEO",
                status=FactStatus.VERIFIED,
                confidence=0.95,
                evidence_ids=evidence_ids,
            ),
            LeadFact(
                field="company_employee_count",
                value=500,
                status=FactStatus.VERIFIED,
                confidence=0.85,
                evidence_ids=evidence_ids,
            ),
            LeadFact(
                field="company_industry",
                value="SaaS",
                status=FactStatus.VERIFIED,
                confidence=0.9,
                evidence_ids=evidence_ids,
            ),
            LeadFact(
                field="company_reputation",
                value="strong",
                status=FactStatus.PROBABLE,
                confidence=0.75,
                evidence_ids=evidence_ids,
            ),
            LeadFact(
                field="growth_signals",
                value="moderate",
                status=FactStatus.PROBABLE,
                confidence=0.7,
                evidence_ids=evidence_ids,
            ),
            LeadFact(
                field="business_relevance",
                value="strong",
                status=FactStatus.PROBABLE,
                confidence=0.8,
                evidence_ids=evidence_ids,
            ),
        ]
        return FactExtractionResult(facts=facts)


def build_test_app(
    evidence_factory: Callable[..., Evidence],
    *,
    max_request_bytes: int = 100_000,
) -> FastAPI:
    settings = Settings(
        _env_file=None,
        max_request_bytes=max_request_bytes,
        target_industries="SaaS",
    )

    async def factory(runtime_settings: Settings) -> ApplicationContainer:
        repository = InMemoryLeadRepository()
        fetcher = SafeHttpFetcher(runtime_settings)
        service = LeadScoringService(
            FakeOrchestrator(evidence_factory()),
            StaticExtractor(),
            ScoringEngine(),
            repository,
            runtime_settings,
        )
        return ApplicationContainer(service, fetcher, repository)

    return create_app(settings, factory)


async def test_score_and_retrieve_lead(
    evidence_factory: Callable[..., Evidence],
) -> None:
    application = build_test_app(evidence_factory)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            scored = await client.post(
                "/api/v1/leads/score",
                json={
                    "name": "Jane Doe",
                    "company": "Example Corp",
                    "designation": "CEO",
                    "industry": "SaaS",
                },
            )
            payload = scored.json()
            retrieved = await client.get(f"/api/v1/leads/{payload['lead_id']}")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert scored.status_code == 201
    assert 0 <= payload["score"] <= 100
    assert payload["classification"] in {"HOT", "WARM", "COLD"}
    assert retrieved.status_code == 200
    assert retrieved.json() == payload


async def test_validation_and_not_found_responses(
    evidence_factory: Callable[..., Evidence],
) -> None:
    application = build_test_app(evidence_factory)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            invalid = await client.post("/api/v1/leads/score", json={"name": "Jane Doe"})
            missing = await client.get("/api/v1/leads/lead_0123456789abcdef0123456789abcdef")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "lead_not_found"


async def test_request_size_limit(evidence_factory: Callable[..., Evidence]) -> None:
    application = build_test_app(evidence_factory, max_request_bytes=1_024)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/leads/score",
                content="x" * 1_025,
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
