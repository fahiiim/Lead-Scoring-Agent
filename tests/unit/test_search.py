from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import ResearchError
from app.providers.search import DisabledSearchProvider, SearxngSearchProvider
from app.providers.website import SafeHttpFetcher
from app.utils.urls import canonicalize_url


async def allow_url(url: str) -> str:
    return canonicalize_url(url)


async def test_searxng_provider_parses_mocked_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {
                    "results": [
                        {
                            "url": "https://example.com/about",
                            "title": "Example Corp",
                            "content": "Example Corp builds SaaS products.",
                            "score": 0.8,
                        }
                    ]
                }
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SafeHttpFetcher(
        Settings(_env_file=None),
        client=client,
        url_validator=allow_url,
    )
    provider = SearxngSearchProvider("https://search.example.com", fetcher)

    results = await provider.search("Example Corp", 2)

    assert len(results) == 1
    assert results[0].relevance == 0.8
    await client.aclose()


async def test_disabled_search_provider_reports_configuration() -> None:
    with pytest.raises(ResearchError, match="no provider is configured"):
        await DisabledSearchProvider().search("Example Corp", 3)
