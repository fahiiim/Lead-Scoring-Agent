from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.models.domain import Evidence, FactStatus, LeadFact


def test_fact_preserves_conflicting_values() -> None:
    fact = LeadFact(
        field="designation",
        value="CEO",
        status=FactStatus.CONFLICTING,
        confidence=0.45,
        evidence_ids=["ev_1", "ev_2", "ev_1"],
        alternatives=["Former CEO", "Chair", "Chair"],
    )

    assert fact.status is FactStatus.CONFLICTING
    assert fact.evidence_ids == ["ev_1", "ev_2"]
    assert fact.alternatives == ["Former CEO", "Chair"]


def test_evidence_rejects_invalid_relevance(
    evidence_factory: Callable[..., Evidence],
) -> None:
    with pytest.raises(ValidationError):
        evidence_factory(relevance=1.5)
