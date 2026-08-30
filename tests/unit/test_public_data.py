from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.public_data import WikipediaPublicDataProvider
from app.providers.website import SafeHttpFetcher
from app.providers.wikidata import WikidataPublicDataProvider
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
        elif request.url.path == "/w/api.php":
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
        elif request.url.path.endswith("/Q16346003"):
            payload = {
                "id": "Q16346003",
                "type": "item",
                "labels": {"en": "bKash"},
                "descriptions": {"en": "Mobile FinTech in Bangladesh"},
                "aliases": {"en": ["bKash Limited"]},
                "statements": {
                    "P169": [_statement("P169", "wikibase-item", "Q6355506")],
                    "P571": [
                        _statement(
                            "P571",
                            "time",
                            {
                                "time": "+2010-00-00T00:00:00Z",
                                "precision": 9,
                                "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
                            },
                        )
                    ],
                    "P856": [_statement("P856", "url", "https://www.bkash.com/")],
                    "P1128": [
                        _statement(
                            "P1128",
                            "quantity",
                            {"amount": "+10000", "unit": "1"},
                            qualifiers=[
                                _qualifier(
                                    "P585",
                                    "time",
                                    {
                                        "time": "+2024-00-00T00:00:00Z",
                                        "precision": 9,
                                        "calendarmodel": (
                                            "http://www.wikidata.org/entity/Q1985727"
                                        ),
                                    },
                                )
                            ],
                        )
                    ],
                },
            }
        elif request.url.path.endswith("/Q6355506"):
            payload = {
                "id": "Q6355506",
                "type": "item",
                "labels": {"en": "Kamal Quadir"},
                "descriptions": {"en": "Chief Executive Officer - bKash Limited"},
                "aliases": {},
                "statements": {"P108": [_statement("P108", "wikibase-item", "Q16346003")]},
            }
        else:
            return httpx.Response(404, headers={"content-type": "application/json"})
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
    assert {item.source_type for item in wikidata} == {"public_knowledge_graph_rest_api"}
    assert "/w/rest.php/wikibase/v1/entities/items/" in str(wikidata[0].url)
    assert "chief executive officer: Kamal Quadir (Q6355506)" in wikidata[0].content
    assert "inception: 2010" in wikidata[0].content
    assert "official website: https://www.bkash.com/" in wikidata[0].content
    assert "employees: 10000 (point in time: 2024)" in wikidata[0].content
    assert "Chief Executive Officer" in wikidata[1].content
    assert "employer: bKash (Q16346003)" in wikidata[1].content
    await client.aclose()


def _statement(
    property_id: str,
    data_type: str,
    content: Any,
    *,
    qualifiers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"statement-{property_id}",
        "rank": "normal",
        "qualifiers": qualifiers or [],
        "references": [],
        "property": {"id": property_id, "data_type": data_type},
        "value": {"type": "value", "content": content},
    }


def _qualifier(property_id: str, data_type: str, content: Any) -> dict[str, Any]:
    return {
        "property": {"id": property_id, "data_type": data_type},
        "value": {"type": "value", "content": content},
    }
