from __future__ import annotations

from typing import Any


class ApplicationError(Exception):
    """Known failure that can be safely represented to an API client."""

    status_code = 500
    code = "application_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LeadNotFoundError(ApplicationError):
    status_code = 404
    code = "lead_not_found"


class ResearchError(ApplicationError):
    status_code = 502
    code = "research_error"


class ExtractionError(ApplicationError):
    status_code = 502
    code = "extraction_error"


class PersistenceError(ApplicationError):
    status_code = 503
    code = "persistence_error"


class UnsafeUrlError(ApplicationError):
    status_code = 400
    code = "unsafe_url"
