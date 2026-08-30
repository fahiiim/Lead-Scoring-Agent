from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.core.exceptions import UnsafeUrlError


UrlValidator = Callable[[str], Awaitable[str]]

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.casefold()
    hostname = (parts.hostname or "").casefold().rstrip(".")
    port = parts.port
    netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


async def validate_public_url(url: str) -> str:
    """Validate an outbound URL and reject non-public network destinations."""
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme.casefold() == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("URL contains an invalid port") from exc

    _validate_url_parts(parts, port)
    hostname = parts.hostname or ""
    addresses = await _resolve_addresses(hostname, port)
    if not addresses:
        raise UnsafeUrlError("URL hostname could not be resolved")
    for address in addresses:
        if not address.is_global:
            raise UnsafeUrlError("URL resolves to a non-public network address")
    return canonicalize_url(url)


def _validate_url_parts(parts: SplitResult, port: int) -> None:
    scheme = parts.scheme.casefold()
    hostname = (parts.hostname or "").casefold().rstrip(".")
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only HTTP and HTTPS URLs are allowed")
    if not hostname:
        raise UnsafeUrlError("URL must include a hostname")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URLs containing credentials are not allowed")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith((".local", ".internal")):
        raise UnsafeUrlError("Internal hostnames are not allowed")
    if port not in _ALLOWED_PORTS:
        raise UnsafeUrlError("Only standard HTTP and HTTPS ports are allowed")


async def _resolve_addresses(hostname: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(hostname)
        return {literal}
    except ValueError:
        pass

    def resolve() -> list[tuple[object, ...]]:
        return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)

    try:
        records = await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise UnsafeUrlError("URL hostname could not be resolved") from exc
    return {ipaddress.ip_address(record[4][0]) for record in records}
