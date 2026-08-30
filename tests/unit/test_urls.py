from __future__ import annotations

import pytest

from app.core.exceptions import UnsafeUrlError
from app.utils.urls import canonicalize_url, validate_public_url


def test_canonicalize_url_normalizes_case_port_and_fragment() -> None:
    assert canonicalize_url("HTTPS://Example.COM:443/about/#team") == "https://example.com/about"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "ftp://example.com/file",
        "https://user:password@example.com/",
        "https://example.com:8443/",
    ],
)
async def test_validate_public_url_blocks_unsafe_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url(url)


async def test_validate_public_url_accepts_global_literal() -> None:
    result = await validate_public_url("https://8.8.8.8/path")
    assert result == "https://8.8.8.8/path"
