from __future__ import annotations

from collections.abc import Callable

from app.models.domain import FactStatus, LeadClassification, LeadFact
from app.schemas.lead import LeadInput, TargetProfile
from app.scoring.engine import ScoringEngine
from app.scoring.profile import ScoringProfile


def profile() -> ScoringProfile:
    return ScoringProfile(
        weights={
            "Decision Maker": 30,
            "Company Size": 20,
            "Industry Fit": 20,
            "Company Reputation": 10,
            "Growth Signals": 10,
            "Business Relevance": 10,
        },
        hot_threshold=80,
        warm_threshold=50,
        target_industries=("saas",),
        target_min_employees=50,
        target_max_employees=1_000,
    )


def complete_facts(factory: Callable[..., LeadFact]) -> list[LeadFact]:
    return [
        factory(field="designation", value="CEO"),
        factory(field="company_employee_count", value=500),
        factory(field="company_industry", value="B2B SaaS"),
        factory(field="company_reputation", value="strong"),
        factory(field="growth_signals", value="strong"),
        factory(field="business_relevance", value="strong"),
    ]


def test_full_fit_scores_100_and_hot(fact_factory: Callable[..., LeadFact]) -> None:
    lead = LeadInput(
        name="Jane Doe",
        company="Example Corp",
        designation="CEO",
        industry="SaaS",
    )
    outcome = ScoringEngine().score(lead, complete_facts(fact_factory), profile())

    assert outcome.score == 100
    assert outcome.classification is LeadClassification.HOT
    assert sum(factor.max_score for factor in outcome.factors) == 100
    assert all(factor.evidence_ids == ["ev_001"] for factor in outcome.factors)


def test_conflicting_title_reduces_decision_maker_score(
    fact_factory: Callable[..., LeadFact],
) -> None:
    facts = complete_facts(fact_factory)
    facts[0] = fact_factory(
        field="designation",
        value="CEO",
        status=FactStatus.CONFLICTING,
        confidence=0.4,
        alternatives=["Former CEO"],
    )
    lead = LeadInput(name="Jane Doe", company="Example Corp", designation="CEO")

    outcome = ScoringEngine().score(lead, facts, profile())
    decision_factor = next(item for item in outcome.factors if item.name == "Decision Maker")

    assert decision_factor.score == 15
    assert decision_factor.confidence == 0.4


def test_company_size_and_industry_target_mismatch_score_zero(
    fact_factory: Callable[..., LeadFact],
) -> None:
    facts = [
        fact_factory(field="company_employee_count", value=5),
        fact_factory(field="company_industry", value="Retail"),
    ]
    lead = LeadInput(name="Jane Doe", company="Small Shop")

    outcome = ScoringEngine().score(lead, facts, profile())
    factor_map = {factor.name: factor for factor in outcome.factors}

    assert factor_map["Company Size"].score == 3
    assert factor_map["Industry Fit"].score == 0


def test_classification_uses_configured_thresholds() -> None:
    custom = profile()
    custom = ScoringProfile(
        weights=custom.weights,
        hot_threshold=90,
        warm_threshold=40,
        target_industries=custom.target_industries,
        target_min_employees=custom.target_min_employees,
        target_max_employees=custom.target_max_employees,
    )

    assert ScoringEngine.classify(90, custom) is LeadClassification.HOT
    assert ScoringEngine.classify(40, custom) is LeadClassification.WARM
    assert ScoringEngine.classify(39, custom) is LeadClassification.COLD


def test_relevant_title_profile_affects_authority(fact_factory: Callable[..., LeadFact]) -> None:
    lead = LeadInput(
        name="Jane Doe",
        company="Example Corp",
        designation="CEO",
        target_profile=TargetProfile(relevant_titles=["Procurement Director"]),
    )
    outcome = ScoringEngine().score(lead, [fact_factory()], profile())
    decision = next(item for item in outcome.factors if item.name == "Decision Maker")

    assert decision.score == 19.5
