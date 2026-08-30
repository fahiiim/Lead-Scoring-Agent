from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from app.core.exceptions import ResearchError
from app.models.domain import ResearchDocument
from app.providers.website import SafeHttpFetcher
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput

_COMPANY_PROPERTIES = {
    "P31": "instance of",
    "P17": "country",
    "P112": "founded by",
    "P127": "owned by",
    "P159": "headquarters",
    "P169": "chief executive officer",
    "P355": "subsidiary",
    "P452": "industry",
    "P571": "inception",
    "P749": "parent organization",
    "P856": "official website",
    "P1128": "employees",
    "P2139": "revenue",
}
_PERSON_PROPERTIES = {
    "P39": "position held",
    "P106": "occupation",
    "P108": "employer",
}
_TEMPORAL_QUALIFIERS = {
    "P580": "start time",
    "P582": "end time",
    "P585": "point in time",
}


class WikidataPublicDataProvider:
    """Discover Wikidata entities, then retrieve them through the Wikibase REST API."""

    name = "wikidata"
    _search_api_root = "https://www.wikidata.org/w/api.php"
    _rest_api_root = "https://www.wikidata.org/w/rest.php/wikibase/v1"

    def __init__(self, fetcher: SafeHttpFetcher) -> None:
        self._fetcher = fetcher

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        company_query = _strip_company_suffix(lead.company)
        queries = list(dict.fromkeys([company_query, lead.company, lead.name]))
        records: list[_WikidataRecord] = []
        seen_entities: set[str] = set()
        for query in queries[: budget.max_steps]:
            if len(records) >= budget.max_sources:
                break
            hit = await self._search(query)
            if hit is None or hit.id in seen_entities:
                continue
            item = await self._get_item(hit.id)
            seen_entities.add(hit.id)
            records.append(
                _WikidataRecord(
                    subject="person" if query.casefold() == lead.name.casefold() else "company",
                    query=query,
                    hit=hit,
                    item=item,
                )
            )

        entity_names = {
            record.item.id: _localized_text(record.item.labels, record.hit.label)
            for record in records
        }
        return [
            _wikidata_document(record, entity_names) for record in records[: budget.max_sources]
        ]

    async def _search(self, query: str) -> _WikidataSearchHit | None:
        search_url = (
            f"{self._search_api_root}?action=wbsearchentities&format=json&language=en"
            f"&type=item&limit=5&maxlag=5&search={quote(query)}"
        )
        try:
            page = await self._fetcher.fetch(
                search_url,
                allowed_content_types=("application/json", "text/json"),
            )
            payload = _WikidataSearchResponse.model_validate(json.loads(page.body))
        except (ResearchError, json.JSONDecodeError, ValidationError) as exc:
            raise ResearchError("Wikidata search request failed") from exc

        return _select_search_hit(payload.search, query)

    async def _get_item(self, item_id: str) -> _WikidataItem:
        item_url = f"{self._rest_api_root}/entities/items/{item_id}"
        try:
            page = await self._fetcher.fetch(
                item_url,
                allowed_content_types=("application/json", "text/json"),
            )
            item = _WikidataItem.model_validate(json.loads(page.body))
        except (ResearchError, json.JSONDecodeError, ValidationError) as exc:
            raise ResearchError("Wikidata REST item request failed") from exc
        if item.id != item_id:
            raise ResearchError("Wikidata REST item response did not match the requested entity")
        return item


class _WikidataSearchHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    label: str = Field(min_length=1)
    description: str | None = None


class _WikidataSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    search: list[_WikidataSearchHit] = Field(default_factory=list)


class _WikidataStatementValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    content: Any = None


class _WikidataStatementProperty(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^P[1-9][0-9]*$")


class _WikidataQualifier(BaseModel):
    model_config = ConfigDict(extra="ignore")

    property: _WikidataStatementProperty
    value: _WikidataStatementValue


class _WikidataStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rank: str = "normal"
    value: _WikidataStatementValue
    qualifiers: list[_WikidataQualifier] = Field(default_factory=list)


class _WikidataItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    type: str
    labels: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    statements: dict[str, list[_WikidataStatement]] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _WikidataRecord:
    subject: str
    query: str
    hit: _WikidataSearchHit
    item: _WikidataItem


def _wikidata_document(
    record: _WikidataRecord,
    entity_names: dict[str, str],
) -> ResearchDocument:
    label = _localized_text(record.item.labels, record.hit.label)
    description = _localized_text(
        record.item.descriptions,
        record.hit.description or "unknown",
    )
    facts = _summarize_wikidata_statements(
        record.item.statements,
        record.subject,
        entity_names,
    )
    aliases = record.item.aliases.get("en", [])[:5]
    content_parts = [
        f"Wikidata {record.subject} label: {label}.",
        f"Description: {description}.",
        f"Entity ID: {record.item.id}.",
    ]
    if aliases:
        content_parts.append(f"Aliases: {', '.join(aliases)}.")
    if facts:
        content_parts.append(f"Business-relevant statements: {'; '.join(facts)}.")
    content_parts.append(f"Matched research query: {record.query}.")

    return ResearchDocument(
        url=HttpUrl(
            f"https://www.wikidata.org/w/rest.php/wikibase/v1/entities/items/{record.item.id}"
        ),
        source_type="public_knowledge_graph_rest_api",
        provider="wikidata",
        title=f"Wikidata entry for {label}",
        content=" ".join(content_parts),
        relevance=0.85 if record.subject == "person" else 0.8,
        reliability=0.86,
    )


def _summarize_wikidata_statements(
    statements: dict[str, list[_WikidataStatement]],
    subject: str,
    entity_names: dict[str, str],
) -> list[str]:
    property_names = _PERSON_PROPERTIES if subject == "person" else _COMPANY_PROPERTIES
    facts: list[str] = []
    for property_id, property_name in property_names.items():
        values = [
            rendered
            for statement in statements.get(property_id, [])
            if statement.rank != "deprecated" and statement.value.type == "value"
            if (rendered := _render_wikidata_statement(statement, entity_names))
        ]
        if values:
            facts.append(f"{property_name}: {', '.join(dict.fromkeys(values[:5]))}")
    return facts


def _render_wikidata_statement(
    statement: _WikidataStatement,
    entity_names: dict[str, str],
) -> str | None:
    rendered = _render_wikidata_value(statement.value.content, entity_names)
    if not rendered:
        return None
    qualifiers: list[str] = []
    for qualifier in statement.qualifiers:
        qualifier_name = _TEMPORAL_QUALIFIERS.get(qualifier.property.id)
        if qualifier_name is None or qualifier.value.type != "value":
            continue
        qualifier_value = _render_wikidata_value(qualifier.value.content, entity_names)
        if qualifier_value:
            qualifiers.append(f"{qualifier_name}: {qualifier_value}")
    if qualifiers:
        return f"{rendered} ({'; '.join(qualifiers)})"
    return rendered


def _render_wikidata_value(value: Any, entity_names: dict[str, str]) -> str | None:
    if isinstance(value, str):
        if re.fullmatch(r"Q[1-9][0-9]*", value):
            label = entity_names.get(value)
            return f"{label} ({value})" if label else value
        return value[:500]
    if not isinstance(value, dict):
        return str(value)[:500] if isinstance(value, (int, float, bool)) else None

    time_value = value.get("time")
    if isinstance(time_value, str):
        return _format_wikidata_time(time_value)
    amount = value.get("amount")
    if isinstance(amount, str):
        return amount.removeprefix("+")
    text = value.get("text")
    if isinstance(text, str):
        return text[:500]
    return None


def _format_wikidata_time(value: str) -> str:
    match = re.match(r"^\+?(-?[0-9]+)-([0-9]{2})-([0-9]{2})T", value)
    if not match:
        return value[:100]
    year, month, day = match.groups()
    if month == "00":
        return year
    if day == "00":
        return f"{year}-{month}"
    return f"{year}-{month}-{day}"


def _select_search_hit(
    hits: list[_WikidataSearchHit],
    query: str,
) -> _WikidataSearchHit | None:
    if not hits:
        return None
    query_name = _normalize_entity_name(query)
    ranked = sorted(
        hits,
        key=lambda hit: _entity_name_match_score(query_name, _normalize_entity_name(hit.label)),
        reverse=True,
    )
    best = ranked[0]
    if _entity_name_match_score(query_name, _normalize_entity_name(best.label)) < 0.5:
        return None
    return best


def _entity_name_match_score(query: str, label: str) -> float:
    if not query or not label:
        return 0.0
    if query == label:
        return 1.0
    if query in label or label in query:
        return 0.85
    query_tokens = set(query.split())
    label_tokens = set(label.split())
    return len(query_tokens & label_tokens) / max(len(query_tokens), len(label_tokens))


def _normalize_entity_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _localized_text(values: dict[str, str], fallback: str) -> str:
    return values.get("en") or next(iter(values.values()), fallback)


def _strip_company_suffix(company: str) -> str:
    suffix_pattern = r"\s+(?:limited|ltd\.?|inc\.?|incorporated|corp\.?|corporation|llc)$"
    normalized = re.sub(suffix_pattern, "", company, flags=re.IGNORECASE).strip()
    return normalized or company
