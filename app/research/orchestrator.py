from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from time import monotonic

from app.core.config import Settings
from app.core.exceptions import ApplicationError
from app.models.domain import Evidence, ResearchBundle, ResearchDocument
from app.research.base import ResearchBudget, ResearchProvider
from app.schemas.lead import LeadInput
from app.utils.cache import Cache
from app.utils.urls import canonicalize_url

logger = logging.getLogger(__name__)
_SPACE = re.compile(r"\s+")


class ResearchOrchestrator:
    """Run a bounded provider workflow and convert documents into evidence."""

    def __init__(
        self,
        providers: list[ResearchProvider],
        cache: Cache[ResearchBundle],
        settings: Settings,
    ) -> None:
        self._providers = providers
        self._cache = cache
        self._settings = settings

    async def research(self, lead: LeadInput) -> ResearchBundle:
        cache_key = self._cache_key(lead)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})

        budget = ResearchBudget(
            max_sources=self._settings.max_research_sources,
            max_pages=self._settings.max_research_pages,
            max_steps=self._settings.max_research_steps,
        )
        documents: list[ResearchDocument] = []
        failures = _configuration_warnings(self._settings)
        seen_urls: set[str] = set()
        started = monotonic()

        try:
            async with asyncio.timeout(self._settings.research_timeout_seconds):
                for provider in self._providers[: budget.max_steps]:
                    if len(documents) >= budget.max_sources or _has_sufficient_evidence(documents):
                        break
                    try:
                        provider_documents = await provider.research(lead, budget)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Research provider failed",
                            extra={"provider": provider.name, "error_type": type(exc).__name__},
                        )
                        if isinstance(exc, ApplicationError):
                            failures.append(f"{provider.name}: {exc.message}")
                        else:
                            failures.append(f"{provider.name} was unavailable.")
                        continue
                    for document in provider_documents:
                        canonical = canonicalize_url(str(document.url))
                        if canonical in seen_urls:
                            continue
                        seen_urls.add(canonical)
                        documents.append(document)
                        if len(documents) >= budget.max_sources:
                            break
        except TimeoutError:
            failures.append("Research stopped at the configured time limit.")

        evidence = [self._to_evidence(document, lead) for document in documents]
        bundle = ResearchBundle(
            documents=documents,
            evidence=evidence,
            provider_failures=failures,
        )
        await self._cache.set(cache_key, bundle, self._settings.cache_ttl_seconds)
        logger.info(
            "Research completed",
            extra={
                "source_count": len(evidence),
                "provider_failure_count": len(failures),
                "duration_ms": round((monotonic() - started) * 1_000),
            },
        )
        return bundle

    def _to_evidence(self, document: ResearchDocument, lead: LeadInput) -> Evidence:
        normalized = _SPACE.sub(" ", document.content).strip()
        excerpt = _select_excerpt(
            normalized,
            terms=(lead.name, lead.company, lead.designation or "", lead.industry or ""),
            limit=self._settings.max_evidence_excerpt_chars,
        )
        content_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        evidence_digest = hashlib.sha256(
            f"{canonicalize_url(str(document.url))}\n{normalized}".encode()
        ).hexdigest()
        return Evidence(
            id=f"ev_{evidence_digest[:16]}",
            source_url=document.url,
            source_type=document.source_type,
            provider=document.provider,
            title=document.title,
            excerpt=excerpt,
            relevance=document.relevance,
            reliability=document.reliability,
            content_digest=content_digest,
        )

    @staticmethod
    def _cache_key(lead: LeadInput) -> str:
        identity = {
            "name": lead.name.casefold(),
            "company": lead.company.casefold(),
            "website": str(lead.website) if lead.website else None,
            "designation": lead.designation.casefold() if lead.designation else None,
            "industry": lead.industry.casefold() if lead.industry else None,
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
        return f"research:{digest}"


def _select_excerpt(text: str, terms: tuple[str, ...], limit: int) -> str | None:
    if not text:
        return None
    lowered_terms = tuple(term.casefold() for term in terms if term)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    relevant = [
        sentence
        for sentence in sentences
        if any(term in sentence.casefold() for term in lowered_terms)
    ]
    selected = " ".join(relevant[:8]) if relevant else text
    return selected[:limit].strip()


def _has_sufficient_evidence(documents: list[ResearchDocument]) -> bool:
    source_types = {document.source_type for document in documents}
    has_official = "company_website" in source_types
    has_public = bool(source_types & {"public_encyclopedia", "government_filing"})
    return len(documents) >= 5 and has_official and has_public


def _configuration_warnings(settings: Settings) -> list[str]:
    if settings.search_provider.casefold() in {"", "none", "disabled"}:
        return ["search: General web search is disabled because no provider is configured"]
    return []
