from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.models.domain import Evidence, FactorScore, LeadClassification, LeadFact

_WHITESPACE = re.compile(r"\s+")


class TargetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industries: list[str] = Field(default_factory=list, max_length=25)
    relevant_titles: list[str] = Field(default_factory=list, max_length=25)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    min_employees: int | None = Field(default=None, ge=1)
    max_employees: int | None = Field(default=None, ge=1)

    @field_validator("industries", "relevant_titles", "keywords")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        cleaned = [_WHITESPACE.sub(" ", value).strip() for value in values if value.strip()]
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def validate_employee_range(self) -> TargetProfile:
        if (
            self.min_employees is not None
            and self.max_employees is not None
            and self.min_employees > self.max_employees
        ):
            raise ValueError("min_employees cannot exceed max_employees")
        return self


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    website: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=150)
    additional_fields: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        max_length=25,
    )
    target_profile: TargetProfile | None = None

    @field_validator("name", "company", "designation", "industry")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _WHITESPACE.sub(" ", value).strip() if value is not None else None

    @field_validator("website", mode="before")
    @classmethod
    def normalize_website(cls, value: object) -> object:
        if isinstance(value, str) and value and "://" not in value:
            return f"https://{value}"
        return value


class LeadScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str
    score: int = Field(ge=0, le=100)
    classification: LeadClassification
    research_confidence: float = Field(ge=0, le=1)
    scoring_confidence: float = Field(ge=0, le=1)
    summary: str
    factors: list[FactorScore]
    facts: list[LeadFact]
    sources: list[Evidence]
    research_warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
