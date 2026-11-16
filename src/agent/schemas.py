from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Category(str, Enum):
    bug = "bug"
    billing = "billing"
    feature_request = "feature_request"
    question = "question"
    other = "other"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class Route(str, Enum):
    AUTO_REPLY_DRAFT = "auto_reply_draft"  # confident, simple question, draft attached
    TEAM_QUEUE = "team_queue"              # confident classification, needs human work (bug, feature...)
    HUMAN_REVIEW = "human_review"          # unsure or risky: a human decides, agent does not guess


class Triage(BaseModel):
    category: Category
    priority: Priority
    priority_reason: str = Field(description="One short sentence justifying the priority.")
    confidence: float = Field(ge=0, le=1, description="Confidence in category AND priority, 0-1.")
    is_simple_question: bool = Field(
        description="True only if answerable from the ticket text alone with general product-agnostic info."
    )
    needs_human: bool = Field(description="True if ambiguous, emotionally charged, risky, or you are unsure.")
    human_reason: Optional[str] = Field(default=None, description="Why a human is needed, if needs_human.")


class Reply(BaseModel):
    draft_reply: str
    assumptions: list[str] = Field(default_factory=list, description="Anything the draft assumes that a human should verify.")


class Ticket(BaseModel):
    id: str
    subject: str = ""
    body: str = ""

    @property
    def text(self) -> str:
        return f"Subject: {self.subject}\n\n{self.body}".strip()
