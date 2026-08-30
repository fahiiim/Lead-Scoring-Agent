from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.domain import ResearchBundle, ResearchDocument
from app.schemas.lead import LeadInput


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_sources: int
    max_pages: int
    max_steps: int


class ResearchProvider(Protocol):
    name: str

    async def research(
        self,
        lead: LeadInput,
        budget: ResearchBudget,
    ) -> list[ResearchDocument]: ...


class LeadResearcher(Protocol):
    async def research(self, lead: LeadInput) -> ResearchBundle: ...
