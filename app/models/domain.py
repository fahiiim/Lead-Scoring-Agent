from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class FactStatus(StrEnum):
    VERIFIED = "verified"
    PROBABLE = "probable"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class LeadClassification(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


type FactValue = str | int | float | bool | list[str] | None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    source_url: HttpUrl
    source_type: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=300)
    excerpt: str | None = Field(default=None, max_length=5_000)
    relevance: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_digest: str | None = Field(default=None, max_length=64)


class LeadFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=100)
    value: FactValue = None
    status: FactStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    alternatives: list[str] = Field(default_factory=list, max_length=10)
    rationale: str | None = Field(default=None, max_length=500)

    @field_validator("evidence_ids", "alternatives")
    @classmethod
    def remove_duplicates(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class ResearchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    source_type: str
    provider: str
    title: str | None = None
    content: str = Field(max_length=100_000)
    relevance: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)


class ResearchBundle(BaseModel):
    documents: list[ResearchDocument] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    provider_failures: list[str] = Field(default_factory=list)
    cache_hit: bool = False


class FactorScore(BaseModel):
    name: str
    score: Annotated[float, Field(ge=0)]
    max_score: Annotated[int, Field(ge=0)]
    reason: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence_ids: list[str] = Field(default_factory=list)


class ScoringOutcome(BaseModel):
    score: int = Field(ge=0, le=100)
    classification: LeadClassification
    scoring_confidence: float = Field(ge=0, le=1)
    summary: str
    factors: list[FactorScore]


class ExtractedFactsPayload(BaseModel):
    """Schema used for structured LLM output."""

    facts: list[LeadFact] = Field(default_factory=list, max_length=40)


class FactExtractionResult(BaseModel):
    facts: list[LeadFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
