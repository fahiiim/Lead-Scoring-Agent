from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.public_data import (
    WikidataPublicDataProvider,
    WikipediaPublicDataProvider,
)
from app.providers.website import SafeHttpFetcher
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput
from app.utils.urls import canonicalize_url


async def allow_url(url: str) -> str:
    return canonicalize_url(url)


async def test_wikimedia_providers_return_company_and_person_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params
        payload: dict[str, Any]
        if request.url.host == "en.wikipedia.org" and query.get("list") == "search":
            payload = {"query": {"search": [{"title": "BKash"}]}}
        elif request.url.host == "en.wikipedia.org":
            payload = {
                "query": {
                    "pages": {
                        "1": {
                            "title": "BKash",
                            "extract": "bKash is a mobile financial service in Bangladesh.",
                            "fullurl": "https://en.wikipedia.org/wiki/BKash",
                        }
                    }
                }
            }
        else:
            search = query.get("search", "")
            if search.casefold() == "bkash":
                records = [
                    {
                        "id": "Q16346003",
                        "label": "bKash",
                        "description": "Mobile FinTech in Bangladesh",
                    }
                ]
            elif search.casefold() == "kamal quadir":
                records = [
                    {
                        "id": "Q6355506",
                        "label": "Kamal Quadir",
                        "description": "Chief Executive Officer - bKash Limited",
                    }
                ]
            else:
                records = []
            payload = {"search": records}
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(
        Settings(_env_file=None),
        client=client,
        url_validator=allow_url,
    )
    lead = LeadInput(name="Kamal Quadir", company="bKash Limited")
    budget = ResearchBudget(max_sources=5, max_pages=2, max_steps=5)

    wikipedia = await WikipediaPublicDataProvider(fetcher).research(lead, budget)
    wikidata = await WikidataPublicDataProvider(fetcher).research(lead, budget)

    assert len(wikipedia) == 1
    assert len(wikidata) == 2
    assert {item.provider for item in wikidata} == {"wikidata"}
    assert "Chief Executive Officer" in wikidata[1].content
    await client.aclose()
