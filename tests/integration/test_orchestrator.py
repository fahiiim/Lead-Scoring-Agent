from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.domain import ResearchBundle, ResearchDocument
from app.research.base import ResearchBudget
from app.research.orchestrator import ResearchOrchestrator
from app.schemas.lead import LeadInput
from app.utils.cache import MemoryTTLCache


@dataclass
class FakeProvider:
    name: str
    documents: list[ResearchDocument]
    should_fail: bool = False
    calls: int = 0

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        del lead, budget
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("provider unavailable")
        return self.documents


def document(url: str, source_type: str = "company_website") -> ResearchDocument:
    return ResearchDocument(
        url=url,
        source_type=source_type,
        provider="fake",
        title="Example",
        content="Jane Doe is CEO of Example Corp, a SaaS company with 500 employees.",
        relevance=0.9,
        reliability=0.9,
    )


async def test_orchestrator_deduplicates_records_failures_and_caches() -> None:
    first = FakeProvider(
        "first",
        [
            document("https://example.com/about"),
            document("https://example.com/about#team"),
        ],
    )
    failed = FakeProvider("failed", [], should_fail=True)
    public = FakeProvider(
        "public",
        [document("https://en.wikipedia.org/wiki/Example", "public_encyclopedia")],
    )
    settings = Settings(
        _env_file=None,
        max_research_steps=3,
        max_research_sources=5,
    )
    cache = MemoryTTLCache[ResearchBundle](60)
    orchestrator = ResearchOrchestrator([first, failed, public], cache, settings)
    lead = LeadInput(name="Jane Doe", company="Example Corp", designation="CEO")

    initial = await orchestrator.research(lead)
    cached = await orchestrator.research(lead)

    assert len(initial.evidence) == 2
    assert initial.provider_failures == ["failed was unavailable."]
    assert cached.cache_hit is True
    assert first.calls == 1
    assert failed.calls == 1
    assert public.calls == 1


async def test_orchestrator_respects_source_limit() -> None:
    provider = FakeProvider(
        "many",
        [document(f"https://example.com/page-{index}") for index in range(5)],
    )
    settings = Settings(_env_file=None, max_research_sources=2, max_research_steps=1)
    orchestrator = ResearchOrchestrator(
        [provider],
        MemoryTTLCache[ResearchBundle](60),
        settings,
    )

    result = await orchestrator.research(LeadInput(name="Jane Doe", company="Example Corp"))

    assert len(result.evidence) == 2
