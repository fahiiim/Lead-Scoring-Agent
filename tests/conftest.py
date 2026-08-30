from __future__ import annotations

from collections.abc import Callable

import pytest

from app.models.domain import Evidence, FactStatus, LeadFact


@pytest.fixture
def evidence_factory() -> Callable[..., Evidence]:
    def build(**overrides: object) -> Evidence:
        values: dict[str, object] = {
            "id": "ev_001",
            "source_url": "https://example.com/about",
            "source_type": "company_website",
            "provider": "test",
            "title": "About Example",
            "excerpt": "Jane Doe is CEO of Example Corp, a SaaS company with 500 employees.",
            "relevance": 0.9,
            "reliability": 0.9,
        }
        values.update(overrides)
        return Evidence.model_validate(values)

    return build


@pytest.fixture
def fact_factory() -> Callable[..., LeadFact]:
    def build(**overrides: object) -> LeadFact:
        values: dict[str, object] = {
            "field": "designation",
            "value": "CEO",
            "status": FactStatus.VERIFIED,
            "confidence": 0.95,
            "evidence_ids": ["ev_001"],
        }
        values.update(overrides)
        return LeadFact.model_validate(values)

    return build
