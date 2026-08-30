from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from fastapi import Request

from app.agents.extractor import (
    FactExtractor,
    FallbackFactExtractor,
    OpenAIFactExtractor,
)
from app.agents.rule_based import RuleBasedFactExtractor
from app.core.config import Settings
from app.db.base import Database
from app.models.domain import ResearchBundle
from app.providers.public_data import SecEdgarProvider, WikipediaPublicDataProvider
from app.providers.search import (
    DisabledSearchProvider,
    SearchResearchProvider,
    SearxngSearchProvider,
)
from app.providers.website import FetchedPage, SafeHttpFetcher, WebsiteResearchProvider
from app.providers.wikidata import WikidataPublicDataProvider
from app.repositories.leads import (
    InMemoryLeadRepository,
    LeadRepository,
    SqlAlchemyLeadRepository,
)
from app.research.base import ResearchProvider
from app.research.orchestrator import ResearchOrchestrator
from app.scoring.engine import ScoringEngine
from app.services.lead_service import LeadScoringService
from app.utils.cache import MemoryTTLCache

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContainer:
    service: LeadScoringService
    fetcher: SafeHttpFetcher
    repository: LeadRepository
    database: Database | None = None

    async def close(self) -> None:
        await self.fetcher.close()
        if self.database is not None:
            await self.database.close()


async def build_container(settings: Settings) -> ApplicationContainer:
    page_cache = MemoryTTLCache[FetchedPage](
        settings.cache_ttl_seconds,
        max_entries=500,
    )
    research_cache = MemoryTTLCache[ResearchBundle](
        settings.cache_ttl_seconds,
        max_entries=500,
    )
    fetcher = SafeHttpFetcher(settings, page_cache=page_cache)
    search_provider = _build_search_provider(settings, fetcher)
    providers: list[ResearchProvider] = [
        WebsiteResearchProvider(fetcher, settings),
        WikipediaPublicDataProvider(fetcher),
        WikidataPublicDataProvider(fetcher),
    ]
    if not isinstance(search_provider, DisabledSearchProvider):
        providers.append(SearchResearchProvider(search_provider))
    if settings.sec_user_agent:
        providers.append(SecEdgarProvider(fetcher, settings))
    orchestrator = ResearchOrchestrator(providers, research_cache, settings)
    extractor = _build_extractor(settings)

    database: Database | None = None
    repository: LeadRepository
    if settings.database_url:
        database = Database(settings.database_url)
        if settings.database_auto_create:
            await database.create_schema()
        repository = SqlAlchemyLeadRepository(
            database.session_factory,
        )
    else:
        repository = InMemoryLeadRepository()

    service = LeadScoringService(
        orchestrator,
        extractor,
        ScoringEngine(),
        repository,
        settings,
    )
    return ApplicationContainer(
        service=service,
        fetcher=fetcher,
        repository=repository,
        database=database,
    )


def get_lead_service(request: Request) -> LeadScoringService:
    container = cast(ApplicationContainer, request.app.state.container)
    return container.service


def _build_extractor(settings: Settings) -> FactExtractor:
    fallback = RuleBasedFactExtractor()
    if settings.openai_api_key is None:
        if settings.require_llm:
            raise RuntimeError("OPENAI_API_KEY is required when REQUIRE_LLM is true")
        return fallback
    primary = OpenAIFactExtractor(settings)
    return primary if settings.require_llm else FallbackFactExtractor(primary, fallback)


def _build_search_provider(
    settings: Settings,
    fetcher: SafeHttpFetcher,
) -> DisabledSearchProvider | SearxngSearchProvider:
    provider_name = settings.search_provider.casefold()
    if provider_name in {"", "none", "disabled"}:
        return DisabledSearchProvider()
    if provider_name == "searxng" and settings.search_base_url is not None:
        api_key = (
            settings.search_api_key.get_secret_value()
            if settings.search_api_key is not None
            else None
        )
        return SearxngSearchProvider(
            str(settings.search_base_url),
            fetcher,
            api_key,
        )
    logger.warning("Unknown or incomplete search provider configuration; search disabled")
    return DisabledSearchProvider()
