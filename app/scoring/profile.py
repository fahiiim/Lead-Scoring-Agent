from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.schemas.lead import LeadInput


@dataclass(frozen=True, slots=True)
class ScoringProfile:
    weights: dict[str, int]
    hot_threshold: int
    warm_threshold: int
    target_industries: tuple[str, ...]
    target_min_employees: int | None
    target_max_employees: int | None


def build_scoring_profile(settings: Settings, lead: LeadInput) -> ScoringProfile:
    request_profile = lead.target_profile
    industries = (
        tuple(value.casefold() for value in request_profile.industries)
        if request_profile and request_profile.industries
        else settings.parsed_target_industries
    )
    return ScoringProfile(
        weights={
            "Decision Maker": settings.score_weight_decision_maker,
            "Company Size": settings.score_weight_company_size,
            "Industry Fit": settings.score_weight_industry_fit,
            "Company Reputation": settings.score_weight_company_reputation,
            "Growth Signals": settings.score_weight_growth_signals,
            "Business Relevance": settings.score_weight_business_relevance,
        },
        hot_threshold=settings.hot_score_threshold,
        warm_threshold=settings.warm_score_threshold,
        target_industries=industries,
        target_min_employees=(
            request_profile.min_employees
            if request_profile and request_profile.min_employees is not None
            else settings.target_min_employees
        ),
        target_max_employees=(
            request_profile.max_employees
            if request_profile and request_profile.max_employees is not None
            else settings.target_max_employees
        ),
    )
