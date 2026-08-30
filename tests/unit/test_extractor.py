from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.extractor import OpenAIFactExtractor
from app.agents.rule_based import RuleBasedFactExtractor
from app.core.config import Settings
from app.models.domain import Evidence, ExtractedFactsPayload, FactStatus, LeadFact
from app.schemas.lead import LeadInput


async def test_rule_extractor_does_not_verify_unsubstantiated_title() -> None:
    result = await RuleBasedFactExtractor().extract(
        LeadInput(name="Jane Doe", company="Example Corp", designation="CEO"),
        [],
    )
    title = next(item for item in result.facts if item.field == "designation")

    assert title.status is FactStatus.PROBABLE
    assert title.confidence < 0.5
    assert title.evidence_ids == []


async def test_rule_extractor_detects_form_title_conflict(
    evidence_factory: Callable[..., Evidence],
) -> None:
    evidence = evidence_factory(excerpt="Jane Doe is the former CEO and current Chair.")
    result = await RuleBasedFactExtractor().extract(
        LeadInput(name="Jane Doe", company="Example Corp", designation="CEO"),
        [evidence],
    )
    title = next(item for item in result.facts if item.field == "designation")

    assert title.status is FactStatus.CONFLICTING
    assert "former CEO" in title.alternatives


async def test_openai_extractor_uses_structured_output_and_filters_unknown_ids(
    monkeypatch: Any,
    evidence_factory: Callable[..., Evidence],
) -> None:
    class FakeChain:
        async def ainvoke(self, messages: object) -> ExtractedFactsPayload:
            del messages
            return ExtractedFactsPayload(
                facts=[
                    LeadFact(
                        field="designation",
                        value="CEO",
                        status=FactStatus.VERIFIED,
                        confidence=0.9,
                        evidence_ids=["ev_001", "invented"],
                    ),
                    LeadFact(
                        field="revenue",
                        value=1_000_000,
                        status=FactStatus.VERIFIED,
                        confidence=0.99,
                        evidence_ids=["invented"],
                    ),
                ]
            )

    class FakeChat:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def with_structured_output(self, schema: object, method: str) -> FakeChain:
            del schema, method
            return FakeChain()

    monkeypatch.setattr("app.agents.extractor.ChatOpenAI", FakeChat)
    extractor = OpenAIFactExtractor(Settings(_env_file=None, openai_api_key="test-key"))
    result = await extractor.extract(
        LeadInput(name="Jane Doe", company="Example Corp", designation="CEO"),
        [evidence_factory()],
    )

    assert result.facts[0].evidence_ids == ["ev_001"]
    assert result.facts[1].status is FactStatus.PROBABLE
    assert result.facts[1].confidence == 0.4
    assert result.facts[1].evidence_ids == []
