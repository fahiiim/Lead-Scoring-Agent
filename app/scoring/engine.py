from __future__ import annotations

from collections.abc import Callable

from app.models.domain import (
    FactorScore,
    FactStatus,
    LeadClassification,
    LeadFact,
    ScoringOutcome,
)
from app.schemas.lead import LeadInput
from app.scoring.profile import ScoringProfile


class ScoringEngine:
    """Calculate lead quality with deterministic, configuration-driven rules."""

    def score(
        self,
        lead: LeadInput,
        facts: list[LeadFact],
        profile: ScoringProfile,
    ) -> ScoringOutcome:
        fact_map = {fact.field: fact for fact in facts}
        calculators: dict[str, Callable[[], tuple[float, str, float, list[str]]]] = {
            "Decision Maker": lambda: self._decision_maker(lead, fact_map),
            "Company Size": lambda: self._company_size(fact_map, profile),
            "Industry Fit": lambda: self._industry_fit(fact_map, profile),
            "Company Reputation": lambda: self._ordinal_signal(
                fact_map.get("company_reputation"),
                "reputation",
                {"strong": 1.0, "moderate": 0.7, "limited": 0.3},
            ),
            "Growth Signals": lambda: self._ordinal_signal(
                fact_map.get("growth_signals"),
                "growth evidence",
                {"strong": 1.0, "moderate": 0.65, "limited": 0.25},
            ),
            "Business Relevance": lambda: self._business_relevance(lead, fact_map),
        }
        factors: list[FactorScore] = []
        for name, weight in profile.weights.items():
            ratio, reason, confidence, evidence_ids = calculators[name]()
            factors.append(
                FactorScore(
                    name=name,
                    score=round(max(0.0, min(1.0, ratio)) * weight, 2),
                    max_score=weight,
                    reason=reason,
                    confidence=round(max(0.0, min(1.0, confidence)), 3),
                    evidence_ids=evidence_ids,
                )
            )
        total = max(0, min(100, round(sum(item.score for item in factors))))
        classification = self.classify(total, profile)
        confidence = round(
            sum(item.confidence * item.max_score for item in factors) / 100,
            3,
        )
        strongest = max(
            factors, key=lambda item: item.score / item.max_score if item.max_score else 0
        )
        summary = (
            f"{classification.value} lead with the strongest contribution from "
            f"{strongest.name.lower()}. The score is deterministic and evidence confidence "
            f"is reported separately."
        )
        return ScoringOutcome(
            score=total,
            classification=classification,
            scoring_confidence=confidence,
            summary=summary,
            factors=factors,
        )

    @staticmethod
    def classify(score: int, profile: ScoringProfile) -> LeadClassification:
        if score >= profile.hot_threshold:
            return LeadClassification.HOT
        if score >= profile.warm_threshold:
            return LeadClassification.WARM
        return LeadClassification.COLD

    def _decision_maker(
        self,
        lead: LeadInput,
        facts: dict[str, LeadFact],
    ) -> tuple[float, str, float, list[str]]:
        fact = facts.get("designation")
        if fact is None or not isinstance(fact.value, str):
            return 0.0, "The current role could not be established.", 0.0, []
        title = fact.value.casefold()
        if any(
            term in title for term in ("founder", "owner", "chief executive", "ceo", "president")
        ):
            ratio, level = 1.0, "top executive"
        elif any(term in title for term in ("chief ", "cfo", "cto", "coo", "cmo", "cio")):
            ratio, level = 0.9, "C-level executive"
        elif any(term in title for term in ("vice president", "vp", "head of", "director")):
            ratio, level = 0.75, "senior leader"
        elif "manager" in title:
            ratio, level = 0.5, "manager"
        elif any(term in title for term in ("senior", "lead", "principal")):
            ratio, level = 0.25, "senior individual contributor"
        else:
            ratio, level = 0.1, "role with unclear purchasing authority"

        company_size = facts.get("company_employee_count")
        if (
            ratio >= 0.9
            and company_size
            and isinstance(company_size.value, int)
            and company_size.value <= 2
        ):
            ratio *= 0.65
            level = f"{level} at a very small company"
        if lead.target_profile and lead.target_profile.relevant_titles:
            relevant = any(item.casefold() in title for item in lead.target_profile.relevant_titles)
            if not relevant:
                ratio *= 0.65
                level = f"{level} outside the configured title profile"
        ratio *= _status_multiplier(fact.status)
        return (
            ratio,
            f"The role is assessed as {level}; verification status is {fact.status.value}.",
            fact.confidence,
            fact.evidence_ids,
        )

    def _company_size(
        self,
        facts: dict[str, LeadFact],
        profile: ScoringProfile,
    ) -> tuple[float, str, float, list[str]]:
        fact = facts.get("company_employee_count")
        if fact is None or not isinstance(fact.value, int):
            return 0.0, "Company size is unknown.", 0.0, []
        count = fact.value
        if profile.target_min_employees is not None or profile.target_max_employees is not None:
            lower = profile.target_min_employees or 1
            upper = profile.target_max_employees or 10**12
            if lower <= count <= upper:
                ratio = 1.0
                fit = "inside the configured range"
            elif count < lower:
                ratio = max(0.15, count / lower)
                fit = "below the configured range"
            else:
                ratio = max(0.4, upper / count)
                fit = "above the configured range"
        elif count >= 1_000:
            ratio, fit = 0.9, "enterprise scale"
        elif count >= 200:
            ratio, fit = 1.0, "large mid-market scale"
        elif count >= 50:
            ratio, fit = 0.85, "mid-market scale"
        elif count >= 10:
            ratio, fit = 0.6, "small business scale"
        elif count >= 3:
            ratio, fit = 0.3, "very small business scale"
        else:
            ratio, fit = 0.15, "micro-business scale"
        ratio *= _status_multiplier(fact.status)
        return (
            ratio,
            f"Public evidence indicates approximately {count} employees, {fit}.",
            fact.confidence,
            fact.evidence_ids,
        )

    def _industry_fit(
        self,
        facts: dict[str, LeadFact],
        profile: ScoringProfile,
    ) -> tuple[float, str, float, list[str]]:
        fact = facts.get("company_industry")
        if fact is None or not isinstance(fact.value, str):
            return 0.0, "Company industry is unknown.", 0.0, []
        industry = fact.value.casefold()
        if not profile.target_industries:
            ratio, reason = (
                0.6,
                "No target industries are configured, so known industry fit is neutral.",
            )
        else:
            matches = any(
                target in industry or industry in target for target in profile.target_industries
            )
            ratio = 1.0 if matches else 0.0
            reason = (
                "The company industry matches the configured target profile."
                if matches
                else "The company industry does not match the configured target profile."
            )
        ratio *= _status_multiplier(fact.status)
        return ratio, reason, fact.confidence, fact.evidence_ids

    def _business_relevance(
        self,
        lead: LeadInput,
        facts: dict[str, LeadFact],
    ) -> tuple[float, str, float, list[str]]:
        fact = facts.get("business_relevance")
        if fact is not None and isinstance(fact.value, str):
            ratios = {"strong": 1.0, "moderate": 0.65, "limited": 0.25}
            ratio = ratios.get(fact.value.casefold(), 0.0) * _status_multiplier(fact.status)
            return (
                ratio,
                f"Business relevance is {fact.value.casefold()} based on available context.",
                fact.confidence,
                fact.evidence_ids,
            )
        title_fact = facts.get("designation")
        if (
            lead.target_profile
            and lead.target_profile.relevant_titles
            and title_fact
            and isinstance(title_fact.value, str)
        ):
            matches = any(
                item.casefold() in title_fact.value.casefold()
                for item in lead.target_profile.relevant_titles
            )
            return (
                0.8 if matches else 0.2,
                "Role relevance was derived from the configured target titles.",
                title_fact.confidence,
                title_fact.evidence_ids,
            )
        return 0.0, "Business relevance could not be established.", 0.0, []

    @staticmethod
    def _ordinal_signal(
        fact: LeadFact | None,
        label: str,
        ratios: dict[str, float],
    ) -> tuple[float, str, float, list[str]]:
        if fact is None or not isinstance(fact.value, str):
            return 0.0, f"Available evidence did not establish {label}.", 0.0, []
        normalized = fact.value.casefold()
        ratio = ratios.get(normalized, 0.0) * _status_multiplier(fact.status)
        return (
            ratio,
            f"Evidence indicates {normalized} {label}.",
            fact.confidence,
            fact.evidence_ids,
        )


def _status_multiplier(status: FactStatus) -> float:
    return {
        FactStatus.VERIFIED: 1.0,
        FactStatus.PROBABLE: 0.9,
        FactStatus.CONFLICTING: 0.5,
        FactStatus.UNKNOWN: 0.0,
    }[status]
