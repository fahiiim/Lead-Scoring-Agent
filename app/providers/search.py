from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, HttpUrl

from app.models.domain import ResearchDocument
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput


class SearchResult(BaseModel):
    url: HttpUrl
    title: str | None = None
    snippet: str | None = None
    relevance: float = Field(default=0.5, ge=0, le=1)


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


class DisabledSearchProvider:
    """Explicit no-search implementation used when no search API is configured."""

    name = "disabled"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return []


class SearchResearchProvider:
    """Adapter that turns provider search snippets into bounded evidence documents."""

    name = "search"

    def __init__(self, search_provider: SearchProvider) -> None:
        self._search_provider = search_provider

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        queries = [
            f'"{lead.company}" company',
            f'"{lead.name}" "{lead.company}"',
        ][: budget.max_steps]
        results: list[SearchResult] = []
        for query in queries:
            remaining = budget.max_sources - len(results)
            if remaining <= 0:
                break
            results.extend(await self._search_provider.search(query, remaining))

        documents: list[ResearchDocument] = []
        seen: set[str] = set()
        for result in results:
            url = str(result.url)
            if url in seen or not result.snippet:
                continue
            seen.add(url)
            documents.append(
                ResearchDocument(
                    url=result.url,
                    source_type="search_result",
                    provider=self._search_provider.name,
                    title=result.title,
                    content=result.snippet,
                    relevance=result.relevance,
                    reliability=0.55,
                )
            )
        return documents[: budget.max_sources]
