from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import json

from pydantic import BaseModel, Field, HttpUrl, ValidationError

from app.core.exceptions import ResearchError
from app.models.domain import ResearchDocument
from app.providers.website import SafeHttpFetcher
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


class SearxngSearchProvider:
    """Search through a user-configured SearXNG instance using its JSON API."""

    name = "searxng"

    def __init__(
        self,
        base_url: str,
        fetcher: SafeHttpFetcher,
        api_key: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._fetcher = fetcher
        self._api_key = api_key

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        url = f"{self._base_url}/search?q={quote(query)}&format=json"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        try:
            response = await self._fetcher.fetch(
                url,
                allowed_content_types=("application/json", "text/json"),
                headers=headers,
            )
            payload = json.loads(response.body)
        except (ResearchError, json.JSONDecodeError):
            return []
        results: list[SearchResult] = []
        for item in payload.get("results", [])[:limit]:
            try:
                results.append(
                    SearchResult(
                        url=item.get("url"),
                        title=item.get("title"),
                        snippet=item.get("content"),
                        relevance=float(item.get("score", 0.5) or 0.5),
                    )
                )
            except (TypeError, ValueError, ValidationError):
                continue
        return results


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
