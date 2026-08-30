from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.core.config import Settings
from app.core.exceptions import ResearchError
from app.models.domain import ResearchDocument
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput
from app.utils.cache import Cache
from app.utils.urls import UrlValidator, canonicalize_url, validate_public_url


_USEFUL_SEGMENTS = (
    "about",
    "about-us",
    "company",
    "team",
    "leadership",
    "products",
    "services",
    "customers",
    "clients",
    "news",
    "blog",
    "careers",
)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    content_type: str
    body: bytes


class SafeHttpFetcher:
    """Bounded HTTP client with redirect checks and public-network validation."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        url_validator: UrlValidator = validate_public_url,
        page_cache: Cache[FetchedPage] | None = None,
    ) -> None:
        self._settings = settings
        self._validator = url_validator
        self._owns_client = client is None
        self._page_cache = page_cache
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.outbound_user_agent},
            follow_redirects=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        allowed_content_types: tuple[str, ...] = ("text/html", "text/plain"),
        headers: dict[str, str] | None = None,
    ) -> FetchedPage:
        current_url = await self._validator(url)
        cache_key = f"page:{current_url}"
        if self._page_cache is not None:
            cached = await self._page_cache.get(cache_key)
            if cached is not None:
                return cached
        redirects = 0
        while True:
            response = await self._request_with_retries(current_url, headers=headers)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                await response.aclose()
                if not location or redirects >= 3:
                    raise ResearchError("Outbound request exceeded safe redirect limits")
                current_url = await self._validator(urljoin(current_url, location))
                redirects += 1
                continue
            if response.status_code >= 400:
                status_code = response.status_code
                await response.aclose()
                raise ResearchError(
                    "Public page returned an unsuccessful response",
                    details={"status_code": status_code},
                )

            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if not any(content_type.casefold().startswith(item) for item in allowed_content_types):
                await response.aclose()
                raise ResearchError("Public page returned an unsupported content type")
            body = await self._read_bounded(response)
            result = FetchedPage(url=current_url, content_type=content_type, body=body)
            if self._page_cache is not None:
                await self._page_cache.set(cache_key, result)
            return result

    async def _request_with_retries(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._settings.request_retry_limit + 1):
            try:
                request = self._client.build_request("GET", url, headers=headers)
                response = await self._client.send(request, stream=True)
                if response.status_code < 500 or attempt == self._settings.request_retry_limit:
                    return response
                await response.aclose()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == self._settings.request_retry_limit:
                    break
            await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
        raise ResearchError("Public page request failed") from last_error

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length and int(declared_length) > self._settings.max_response_bytes:
            await response.aclose()
            raise ResearchError("Public page exceeded the response size limit")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._settings.max_response_bytes:
                await response.aclose()
                raise ResearchError("Public page exceeded the response size limit")
            chunks.append(chunk)
        await response.aclose()
        return b"".join(chunks)


class WebsiteResearchProvider:
    name = "official_website"

    def __init__(self, fetcher: SafeHttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]:
        if lead.website is None:
            return []
        root_url = canonicalize_url(str(lead.website))
        robots = await self._load_robots(root_url)
        documents: list[ResearchDocument] = []
        seen: set[str] = set()
        pending = [root_url]

        while pending and len(documents) < min(budget.max_pages, budget.max_sources):
            url = pending.pop(0)
            canonical = canonicalize_url(url)
            if canonical in seen or not robots.can_fetch(self._settings.outbound_user_agent, canonical):
                continue
            seen.add(canonical)
            if documents and self._settings.website_rate_limit_seconds:
                await asyncio.sleep(self._settings.website_rate_limit_seconds)
            try:
                page = await self._fetcher.fetch(canonical)
            except (ResearchError, httpx.HTTPError):
                continue
            if not page.content_type.startswith("text/html"):
                continue
            title, text, links = _extract_html(page.body, page.url)
            if not text:
                continue
            documents.append(
                ResearchDocument(
                    url=page.url,
                    source_type="company_website",
                    provider=self.name,
                    title=title,
                    content=text[:100_000],
                    relevance=1.0 if not documents else 0.85,
                    reliability=0.9,
                )
            )
            if len(documents) == 1:
                pending.extend(
                    link for link in _rank_useful_links(links, root_url) if link not in seen
                )
                if len(pending) < budget.max_pages:
                    pending.extend(
                        urljoin(root_url, segment) for segment in _USEFUL_SEGMENTS
                    )
        return documents

    async def _load_robots(self, root_url: str) -> RobotFileParser:
        parts = urlsplit(root_url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            page = await self._fetcher.fetch(
                robots_url,
                allowed_content_types=("text/plain", "text/html"),
            )
            parser.parse(page.body.decode("utf-8", errors="replace").splitlines())
        except (ResearchError, httpx.HTTPError):
            parser.parse([])
        return parser


def _extract_html(body: bytes, base_url: str) -> tuple[str | None, str, list[str]]:
    soup = BeautifulSoup(body, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "template"]):
        element.decompose()
    title = _SPACE.sub(" ", soup.title.get_text(" ", strip=True)) if soup.title else None
    links = [urljoin(base_url, anchor.get("href", "")) for anchor in soup.find_all("a")]
    text = _SPACE.sub(" ", soup.get_text(" ", strip=True)).strip()
    return title, text, links


def _rank_useful_links(links: Iterable[str], root_url: str) -> list[str]:
    root = urlsplit(root_url)
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for link in links:
        try:
            canonical = canonicalize_url(link)
            parts = urlsplit(canonical)
        except ValueError:
            continue
        if parts.hostname != root.hostname or canonical in seen:
            continue
        seen.add(canonical)
        path = parts.path.casefold()
        score = next(
            (len(_USEFUL_SEGMENTS) - index for index, item in enumerate(_USEFUL_SEGMENTS) if item in path),
            0,
        )
        if score:
            ranked.append((score, canonical))
    return [url for _, url in sorted(ranked, reverse=True)]
