from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Lead Scoring Agent"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    require_llm: bool = False

    database_url: str | None = None
    database_auto_create: bool = False

    search_provider: str = "none"
    search_api_key: SecretStr | None = None
    sec_user_agent: str | None = None

    max_research_steps: int = Field(default=3, ge=1, le=10)
    max_research_sources: int = Field(default=12, ge=1, le=50)
    max_research_pages: int = Field(default=6, ge=1, le=20)
    research_timeout_seconds: float = Field(default=45.0, gt=1, le=180)
    max_evidence_excerpt_chars: int = Field(default=1_500, ge=200, le=5_000)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    request_retry_limit: int = Field(default=2, ge=0, le=5)
    max_response_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    max_request_bytes: int = Field(default=100_000, ge=1_024, le=2_000_000)
    website_rate_limit_seconds: float = Field(default=0.25, ge=0, le=10)
    cache_ttl_seconds: int = Field(default=21_600, ge=60, le=604_800)
    outbound_user_agent: str = "LeadScoringAgent/1.0 (+public-research)"

    hot_score_threshold: int = Field(default=80, ge=1, le=100)
    warm_score_threshold: int = Field(default=50, ge=0, le=99)
    score_weight_decision_maker: int = Field(default=30, ge=0, le=100)
    score_weight_company_size: int = Field(default=20, ge=0, le=100)
    score_weight_industry_fit: int = Field(default=20, ge=0, le=100)
    score_weight_company_reputation: int = Field(default=10, ge=0, le=100)
    score_weight_growth_signals: int = Field(default=10, ge=0, le=100)
    score_weight_business_relevance: int = Field(default=10, ge=0, le=100)
    target_industries: str = ""
    target_min_employees: int | None = Field(default=None, ge=1)
    target_max_employees: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_scoring_configuration(self) -> Settings:
        weights = (
            self.score_weight_decision_maker,
            self.score_weight_company_size,
            self.score_weight_industry_fit,
            self.score_weight_company_reputation,
            self.score_weight_growth_signals,
            self.score_weight_business_relevance,
        )
        if sum(weights) != 100:
            raise ValueError("Scoring weights must total 100")
        if self.warm_score_threshold >= self.hot_score_threshold:
            raise ValueError("WARM_SCORE_THRESHOLD must be lower than HOT_SCORE_THRESHOLD")
        if (
            self.target_min_employees is not None
            and self.target_max_employees is not None
            and self.target_min_employees > self.target_max_employees
        ):
            raise ValueError("TARGET_MIN_EMPLOYEES cannot exceed TARGET_MAX_EMPLOYEES")
        return self

    @property
    def parsed_target_industries(self) -> tuple[str, ...]:
        return tuple(
            item.strip().casefold()
            for item in self.target_industries.split(",")
            if item.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
