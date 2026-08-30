from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import ResearchError
from app.providers.website import SafeHttpFetcher, WebsiteResearchProvider
from app.research.base import ResearchBudget
from app.schemas.lead import LeadInput
from app.utils.urls import canonicalize_url


async def allow_url(url: str) -> str:
    return canonicalize_url(url)


async def test_website_provider_selectively_fetches_discovered_page() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="User-agent: *\nDisallow:",
            )
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<html><title>Example</title><a href="/about">About</a></html>',
            )
        if request.url.path == "/about":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html><h1>About</h1><p>Example Corp has 500 employees.</p></html>",
            )
        return httpx.Response(404, headers={"content-type": "text/html"})

    settings = Settings(
        _env_file=None,
        website_rate_limit_seconds=0,
        max_research_pages=2,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(settings, client=client, url_validator=allow_url)
    provider = WebsiteResearchProvider(fetcher, settings)

    documents = await provider.research(
        LeadInput(name="Jane Doe", company="Example Corp", website="example.com"),
        ResearchBudget(max_sources=4, max_pages=2, max_steps=2),
    )

    assert [str(item.url) for item in documents] == [
        "https://example.com/",
        "https://example.com/about",
    ]
    assert requested_paths == ["/robots.txt", "/", "/about"]
    await client.aclose()


async def test_fetcher_rejects_oversized_mocked_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 10_001,
        )

    settings = Settings(_env_file=None, max_response_bytes=10_000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(settings, client=client, url_validator=allow_url)

    with pytest.raises(ResearchError, match="response size limit"):
        await fetcher.fetch("https://example.com/")
    await client.aclose()


async def test_website_provider_uses_corporate_email_domain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><p>Example Corp public company page.</p></html>",
        )

    settings = Settings(_env_file=None, website_rate_limit_seconds=0)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(settings, client=client, url_validator=allow_url)
    provider = WebsiteResearchProvider(fetcher, settings)

    documents = await provider.research(
        LeadInput(name="Jane Doe", company="Example Corp", email="jane@example.com"),
        ResearchBudget(max_sources=1, max_pages=1, max_steps=1),
    )

    assert len(documents) == 1
    assert str(documents[0].url) == "https://example.com/"
    await client.aclose()


async def test_website_provider_reports_blocked_root_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"content-type": "text/html"},
            text="Forbidden",
        )

    settings = Settings(_env_file=None, request_retry_limit=0)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(settings, client=client, url_validator=allow_url)
    provider = WebsiteResearchProvider(fetcher, settings)

    with pytest.raises(ResearchError, match="did not return a usable page"):
        await provider.research(
            LeadInput(name="Jane Doe", company="Example Corp", website="example.com"),
            ResearchBudget(max_sources=2, max_pages=2, max_steps=2),
        )
    await client.aclose()
