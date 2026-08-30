from __future__ import annotations

import json
from urllib.parse import quote

from pydantic import HttpUrl

from app.core.config import Settings
from app.core.exceptions import ResearchError
from app.models.domain import ResearchDocument
from app.providers.website import SafeHttpFetcher
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput


class WikipediaPublicDataProvider:
    """Retrieve a bounded company summary from the public MediaWiki API."""

    name = "wikipedia"
    _api_root = "https://en.wikipedia.org/w/api.php"

    def __init__(self, fetcher: SafeHttpFetcher) -> None:
        self._fetcher = fetcher

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        del budget
        search_url = (
            f"{self._api_root}?action=query&list=search&format=json&utf8=1"
            f"&srlimit=3&srsearch={quote(lead.company)}"
        )
        try:
            page = await self._fetcher.fetch(
                search_url,
                allowed_content_types=("application/json", "text/json"),
            )
            payload = json.loads(page.body)
        except (ResearchError, json.JSONDecodeError) as exc:
            raise ResearchError("Wikipedia search request failed") from exc
        results = payload.get("query", {}).get("search", [])
        match = next(
            (
                item
                for item in results
                if lead.company.casefold() in str(item.get("title", "")).casefold()
                or str(item.get("title", "")).casefold() in lead.company.casefold()
            ),
            None,
        )
        if not match:
            return []
        title = str(match["title"])
        extract_url = (
            f"{self._api_root}?action=query&prop=extracts|info&inprop=url&format=json"
            f"&explaintext=1&exintro=1&redirects=1&titles={quote(title)}"
        )
        try:
            detail_page = await self._fetcher.fetch(
                extract_url,
                allowed_content_types=("application/json", "text/json"),
            )
            detail = json.loads(detail_page.body)
            pages = detail.get("query", {}).get("pages", {})
            record = next(iter(pages.values()))
            extract = str(record.get("extract", "")).strip()
            full_url = record.get("fullurl")
        except (ResearchError, json.JSONDecodeError, StopIteration) as exc:
            raise ResearchError("Wikipedia article request failed") from exc
        if not extract or not full_url:
            return []
        return [
            ResearchDocument(
                url=HttpUrl(full_url),
                source_type="public_encyclopedia",
                provider=self.name,
                title=title,
                content=extract[:100_000],
                relevance=0.75,
                reliability=0.72,
            )
        ]


class SecEdgarProvider:
    """Retrieve public filing metadata when a compliant SEC user agent is configured."""

    name = "sec_edgar"
    _tickers_url = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, fetcher: SafeHttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        del budget
        if not self._settings.sec_user_agent:
            return []
        try:
            tickers_page = await self._fetcher.fetch(
                self._tickers_url,
                allowed_content_types=("application/json", "text/plain"),
                headers={"User-Agent": self._settings.sec_user_agent},
            )
            records = json.loads(tickers_page.body).values()
            match = next(
                item
                for item in records
                if str(item.get("title", "")).casefold() == lead.company.casefold()
            )
            cik = str(match["cik_str"]).zfill(10)
            submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            submission_page = await self._fetcher.fetch(
                submissions_url,
                allowed_content_types=("application/json", "text/plain"),
                headers={"User-Agent": self._settings.sec_user_agent},
            )
            submission = json.loads(submission_page.body)
        except StopIteration:
            return []
        except (ResearchError, json.JSONDecodeError) as exc:
            raise ResearchError("SEC EDGAR research failed") from exc
        recent_forms = submission.get("filings", {}).get("recent", {}).get("form", [])[:10]
        content = (
            f"SEC registrant name: {submission.get('name', lead.company)}. "
            f"SIC description: {submission.get('sicDescription', 'unknown')}. "
            f"State of incorporation: {submission.get('stateOfIncorporation', 'unknown')}. "
            f"Recent filing forms: {', '.join(recent_forms) if recent_forms else 'unknown'}."
        )
        return [
            ResearchDocument(
                url=HttpUrl(f"https://www.sec.gov/edgar/browse/?CIK={cik}"),
                source_type="government_filing",
                provider=self.name,
                title=f"SEC EDGAR record for {lead.company}",
                content=content,
                relevance=0.9,
                reliability=0.98,
            )
        ]
