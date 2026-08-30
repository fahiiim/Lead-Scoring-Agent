from __future__ import annotations

import json
import logging
from typing import Protocol

from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.exceptions import ExtractionError
from app.models.domain import (
    Evidence,
    ExtractedFactsPayload,
    FactExtractionResult,
    LeadFact,
)
from app.schemas.lead import LeadInput

logger = logging.getLogger(__name__)


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
        messages = [
            ("system", _EXTRACTION_INSTRUCTIONS),
            (
                "human",
                json.dumps(
                    {
                        "lead_form": lead.model_dump(mode="json"),
                        "evidence": [_evidence_payload(item) for item in evidence],
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
                update={"evidence_ids": [item for item in fact.evidence_ids if item in valid_ids]}
            )
            for fact in payload.facts
        ]
        return FactExtractionResult(facts=_deduplicate_facts(facts))


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
            warning = "OpenAI extraction failed; conservative local extraction was used."
            return result.model_copy(
                update={"warnings": list(dict.fromkeys([warning, *result.warnings]))}
            )


def _evidence_payload(item: Evidence) -> dict[str, object]:
    return {
        "id": item.id,
        "url": str(item.source_url),
        "source_type": item.source_type,
        "title": item.title,
        "excerpt": item.excerpt,
        "reliability": item.reliability,
    }


def _deduplicate_facts(facts: list[LeadFact]) -> list[LeadFact]:
    selected: dict[str, LeadFact] = {}
    for fact in facts:
        current = selected.get(fact.field)
        if current is None or fact.confidence > current.confidence:
            selected[fact.field] = fact
    return list(selected.values())


_EXTRACTION_INSTRUCTIONS = (
    "You extract lead facts only from the supplied form and evidence. Never invent "
    "values. Use verified only when public evidence directly supports the value, "
    "probable for a credible but incomplete inference, unknown when not established, "
    "and conflicting when sources or form and sources disagree. Include only supplied "
    "evidence IDs. Important fields include designation, person_company, "
    "company_industry, company_employee_count, company_age_years, company_headquarters, "
    "products_services, target_customers, funding, revenue, public_company, "
    "company_activity, customer_references, market_presence, company_reputation, "
    "growth_signals, and business_relevance. Confidence measures evidence certainty, "
    "not lead quality."
)
