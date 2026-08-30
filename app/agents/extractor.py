from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.exceptions import ExtractionError
from app.models.domain import (
    Evidence,
    ExtractedFactsPayload,
    FactExtractionResult,
    FactStatus,
    LeadFact,
)
from app.schemas.lead import LeadInput


logger = logging.getLogger(__name__)

_TITLE_PATTERNS = (
    "founder",
    "owner",
    "chief executive officer",
    "ceo",
    "president",
    "chief operating officer",
    "coo",
    "chief financial officer",
    "cfo",
    "chief technology officer",
    "cto",
    "vice president",
    "vp",
    "head of",
    "director",
    "manager",
)
_SIZE_PATTERNS = (
    re.compile(r"(?:team of|over|about|approximately|more than)?\s*([\d,]+)\+?\s+employees", re.I),
    re.compile(r"([\d,]+)\+?\s+(?:people|team members|staff)", re.I),
)


class FactExtractor(Protocol):
    async def extract(
        self,
        lead: LeadInput,
        evidence: list[Evidence],
    ) -> FactExtractionResult: ...


class OpenAIFactExtractor:
    """Evidence-constrained structured extraction through LangChain."""

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for OpenAI extraction")
        self._chain = ChatOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_model,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            temperature=0,
        ).with_structured_output(ExtractedFactsPayload, method="json_schema")

    async def extract(
        self,
        lead: LeadInput,
        evidence: list[Evidence],
    ) -> FactExtractionResult:
        evidence_payload = [
            {
                "id": item.id,
                "url": str(item.source_url),
                "source_type": item.source_type,
                "title": item.title,
                "excerpt": item.excerpt,
                "reliability": item.reliability,
            }
            for item in evidence
        ]
        messages = [
            (
                "system",
                "You extract lead facts only from the supplied form and evidence. "
                "Never invent values. Use verified only when public evidence directly "
                "supports the value, probable for a credible but incomplete inference, "
                "unknown when not established, and conflicting when sources or form and "
                "sources disagree. Include only supplied evidence IDs. Important fields "
                "include designation, person_company, company_industry, "
                "company_employee_count, company_age_years, company_headquarters, "
                "products_services, target_customers, funding, revenue, public_company, "
                "company_activity, customer_references, market_presence, "
                "company_reputation, growth_signals, and business_relevance. "
                "Confidence measures evidence certainty, not lead quality.",
            ),
            (
                "human",
                json.dumps(
                    {
                        "lead_form": lead.model_dump(mode="json"),
                        "evidence": evidence_payload,
                    },
                    ensure_ascii=True,
                ),
            ),
        ]
        try:
            raw_result = await self._chain.ainvoke(messages)
            payload = (
                raw_result
                if isinstance(raw_result, ExtractedFactsPayload)
                else ExtractedFactsPayload.model_validate(raw_result)
            )
        except Exception as exc:
            logger.warning("OpenAI structured extraction failed", exc_info=exc)
            raise ExtractionError("Structured fact extraction failed") from exc
        valid_ids = {item.id for item in evidence}
        facts = [
            fact.model_copy(
                update={
                    "evidence_ids": [item for item in fact.evidence_ids if item in valid_ids]
                }
            )
            for fact in payload.facts
        ]
        return FactExtractionResult(facts=_deduplicate_facts(facts))


class RuleBasedFactExtractor:
    """Conservative offline extractor for development and graceful degradation."""

    async def extract(
        self,
        lead: LeadInput,
        evidence: list[Evidence],
    ) -> FactExtractionResult:
        facts = [
            self._designation_fact(lead, evidence),
            self._person_company_fact(lead, evidence),
            self._industry_fact(lead, evidence),
            self._employee_count_fact(evidence),
            self._signal_fact(
                "company_activity",
                evidence,
                strong_terms=("latest news", "careers", "we are hiring", "recently launched"),
                moderate_terms=("news", "blog", "products", "services"),
            ),
            self._signal_fact(
                "growth_signals",
                evidence,
                strong_terms=("raised", "funding round", "expansion", "acquisition", "rapid growth"),
                moderate_terms=("hiring", "growing", "growth", "new market"),
            ),
            self._reputation_fact(evidence),
            self._business_relevance_fact(lead, evidence),
            self._public_company_fact(evidence),
        ]
        expected = {
            "company_age_years",
            "company_headquarters",
            "products_services",
            "target_customers",
            "funding",
            "revenue",
            "customer_references",
            "market_presence",
        }
        facts.extend(_unknown_fact(field) for field in sorted(expected))
        return FactExtractionResult(
            facts=facts,
            warnings=["OpenAI extraction was unavailable; conservative local extraction was used."],
        )

    def _designation_fact(self, lead: LeadInput, evidence: list[Evidence]) -> LeadFact:
        if not lead.designation:
            return _unknown_fact("designation")
        title = lead.designation.casefold()
        supporting = [
            item.id
            for item in evidence
            if item.excerpt
            and title in item.excerpt.casefold()
            and (lead.name.casefold() in item.excerpt.casefold() or lead.company.casefold() in item.excerpt.casefold())
        ]
        conflicting_titles: set[str] = set()
        for item in evidence:
            text = (item.excerpt or "").casefold()
            if lead.name.casefold() not in text:
                continue
            conflicting_titles.update(
                candidate
                for candidate in _TITLE_PATTERNS
                if candidate in text and candidate not in title and title not in candidate
            )
            if f"former {title}" in text:
                conflicting_titles.add(f"former {lead.designation}")
        if conflicting_titles:
            return LeadFact(
                field="designation",
                value=lead.designation,
                status=FactStatus.CONFLICTING,
                confidence=0.45,
                evidence_ids=supporting,
                alternatives=sorted(conflicting_titles),
                rationale="Public evidence contains a different or former title.",
            )
        if supporting:
            return LeadFact(
                field="designation",
                value=lead.designation,
                status=FactStatus.VERIFIED,
                confidence=min(0.96, 0.72 + 0.08 * len(supporting)),
                evidence_ids=supporting,
                rationale="The submitted title appears with the person or company in public evidence.",
            )
        return LeadFact(
            field="designation",
            value=lead.designation,
            status=FactStatus.PROBABLE,
            confidence=0.4,
            rationale="The title is form-supplied and was not independently verified.",
        )

    def _person_company_fact(self, lead: LeadInput, evidence: list[Evidence]) -> LeadFact:
        supporting = [
            item.id
            for item in evidence
            if item.excerpt
            and lead.name.casefold() in item.excerpt.casefold()
            and lead.company.casefold() in item.excerpt.casefold()
        ]
        if supporting:
            return LeadFact(
                field="person_company",
                value=True,
                status=FactStatus.VERIFIED,
                confidence=min(0.95, 0.74 + 0.08 * len(supporting)),
                evidence_ids=supporting,
                rationale="The person and company co-occur in public evidence.",
            )
        return LeadFact(
            field="person_company",
            value=None,
            status=FactStatus.UNKNOWN,
            confidence=0.1,
            rationale="No public source linked the person to the company.",
        )

    def _industry_fact(self, lead: LeadInput, evidence: list[Evidence]) -> LeadFact:
        if not lead.industry:
            return _unknown_fact("company_industry")
        supporting = [
            item.id
            for item in evidence
            if item.excerpt and lead.industry.casefold() in item.excerpt.casefold()
        ]
        return LeadFact(
            field="company_industry",
            value=lead.industry,
            status=FactStatus.VERIFIED if supporting else FactStatus.PROBABLE,
            confidence=min(0.9, 0.7 + 0.05 * len(supporting)) if supporting else 0.4,
            evidence_ids=supporting,
            rationale=(
                "The submitted industry appears in public evidence."
                if supporting
                else "The industry is form-supplied and was not independently verified."
            ),
        )

    def _employee_count_fact(self, evidence: list[Evidence]) -> LeadFact:
        observations: list[tuple[int, str]] = []
        for item in evidence:
            text = item.excerpt or ""
            for pattern in _SIZE_PATTERNS:
                match = pattern.search(text)
                if match:
                    observations.append((int(match.group(1).replace(",", "")), item.id))
                    break
        if not observations:
            return _unknown_fact("company_employee_count")
        values = {item[0] for item in observations}
        evidence_ids = [item[1] for item in observations]
        if len(values) > 1 and max(values) > min(values) * 2:
            return LeadFact(
                field="company_employee_count",
                value=max(values),
                status=FactStatus.CONFLICTING,
                confidence=0.45,
                evidence_ids=evidence_ids,
                alternatives=[str(value) for value in sorted(values)],
                rationale="Public sources provide materially different employee counts.",
            )
        return LeadFact(
            field="company_employee_count",
            value=max(values),
            status=FactStatus.VERIFIED if len(values) > 1 else FactStatus.PROBABLE,
            confidence=0.78 if len(values) > 1 else 0.62,
            evidence_ids=evidence_ids,
            rationale="An employee count was extracted from public evidence.",
        )

    def _signal_fact(
        self,
        field: str,
        evidence: list[Evidence],
        *,
        strong_terms: tuple[str, ...],
        moderate_terms: tuple[str, ...],
    ) -> LeadFact:
        strong_ids = _matching_evidence(evidence, strong_terms)
        moderate_ids = _matching_evidence(evidence, moderate_terms)
        if strong_ids:
            return LeadFact(
                field=field,
                value="strong",
                status=FactStatus.PROBABLE,
                confidence=min(0.82, 0.6 + 0.05 * len(strong_ids)),
                evidence_ids=strong_ids,
                rationale="Multiple public activity indicators were observed.",
            )
        if moderate_ids:
            return LeadFact(
                field=field,
                value="moderate",
                status=FactStatus.PROBABLE,
                confidence=min(0.72, 0.5 + 0.04 * len(moderate_ids)),
                evidence_ids=moderate_ids,
                rationale="Some public activity indicators were observed.",
            )
        return _unknown_fact(field)

    def _reputation_fact(self, evidence: list[Evidence]) -> LeadFact:
        types = {item.source_type for item in evidence}
        public_ids = [
            item.id
            for item in evidence
            if item.source_type in {"government_filing", "public_encyclopedia"}
        ]
        if len(types) >= 3 or len(public_ids) >= 2:
            value, confidence = "strong", 0.78
        elif len(types) >= 2 or public_ids:
            value, confidence = "moderate", 0.65
        elif evidence:
            value, confidence = "limited", 0.5
        else:
            return _unknown_fact("company_reputation")
        return LeadFact(
            field="company_reputation",
            value=value,
            status=FactStatus.PROBABLE,
            confidence=confidence,
            evidence_ids=[item.id for item in evidence[:8]],
            rationale="Reputation is derived from source diversity and authoritative public presence.",
        )

    def _business_relevance_fact(self, lead: LeadInput, evidence: list[Evidence]) -> LeadFact:
        profile = lead.target_profile
        terms = tuple(profile.keywords) if profile else ()
        ids = _matching_evidence(evidence, tuple(item.casefold() for item in terms))
        if terms:
            return LeadFact(
                field="business_relevance",
                value="strong" if ids else "limited",
                status=FactStatus.PROBABLE if ids else FactStatus.UNKNOWN,
                confidence=0.7 if ids else 0.25,
                evidence_ids=ids,
                rationale=(
                    "Target profile keywords appear in public evidence."
                    if ids
                    else "No target profile keywords were established in public evidence."
                ),
            )
        if evidence:
            return LeadFact(
                field="business_relevance",
                value="moderate",
                status=FactStatus.PROBABLE,
                confidence=0.45,
                evidence_ids=[item.id for item in evidence[:3]],
                rationale="Public company information exists, but no target keywords were configured.",
            )
        return _unknown_fact("business_relevance")

    def _public_company_fact(self, evidence: list[Evidence]) -> LeadFact:
        ids = [item.id for item in evidence if item.source_type == "government_filing"]
        if not ids:
            return _unknown_fact("public_company")
        return LeadFact(
            field="public_company",
            value=True,
            status=FactStatus.VERIFIED,
            confidence=0.98,
            evidence_ids=ids,
            rationale="A matching SEC EDGAR registrant was found.",
        )


class FallbackFactExtractor:
    def __init__(self, primary: FactExtractor, fallback: FactExtractor) -> None:
        self._primary = primary
        self._fallback = fallback

    async def extract(
        self,
        lead: LeadInput,
        evidence: list[Evidence],
    ) -> FactExtractionResult:
        try:
            return await self._primary.extract(lead, evidence)
        except ExtractionError:
            result = await self._fallback.extract(lead, evidence)
            return result.model_copy(
                update={
                    "warnings": [
                        "OpenAI extraction failed; conservative local extraction was used.",
                        *result.warnings,
                    ]
                }
            )


def _unknown_fact(field: str) -> LeadFact:
    return LeadFact(
        field=field,
        value=None,
        status=FactStatus.UNKNOWN,
        confidence=0.0,
        rationale="Available evidence did not establish this fact.",
    )


def _matching_evidence(evidence: list[Evidence], terms: tuple[str, ...]) -> list[str]:
    return [
        item.id
        for item in evidence
        if item.excerpt and any(term in item.excerpt.casefold() for term in terms)
    ]


def _deduplicate_facts(facts: list[LeadFact]) -> list[LeadFact]:
    selected: dict[str, LeadFact] = {}
    for fact in facts:
        current = selected.get(fact.field)
        if current is None or fact.confidence > current.confidence:
            selected[fact.field] = fact
    return list(selected.values())
