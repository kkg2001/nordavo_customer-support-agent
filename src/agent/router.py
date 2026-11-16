"""Deterministic routing. The model proposes; these rules decide. Pure functions, no LLM -> unit-testable."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from .schemas import Category, Priority, Route, Triage

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))

# Never auto-reply on these, regardless of model confidence. Cheaper to over-escalate than to send a wrong reply.
RISKY = re.compile(
    r"\b(refund|charge ?back|double[- ]charged|overcharg\w*|lawyer|legal|sue|gdpr|data breach|security|"
    r"hack\w*|cancel\w*|unacceptable|furious|ignore (all |your )?(previous )?instructions)\b",
    re.I,
)


@dataclass
class Decision:
    route: Route
    reason: str


def decide(triage: Triage | None, ticket_text: str, error: str | None = None) -> Decision:
    if triage is None:
        return Decision(Route.HUMAN_REVIEW, f"agent failed to produce valid output: {error}")
    if triage.needs_human:
        return Decision(Route.HUMAN_REVIEW, f"model flagged for human: {triage.human_reason or 'unspecified'}")
    if triage.confidence < CONFIDENCE_THRESHOLD:
        return Decision(Route.HUMAN_REVIEW, f"low confidence ({triage.confidence:.2f} < {CONFIDENCE_THRESHOLD})")
    m = RISKY.search(ticket_text)
    if m:
        return Decision(Route.HUMAN_REVIEW, f"risky keyword in ticket: '{m.group(0)}'")
    if triage.category == Category.other:
        return Decision(Route.HUMAN_REVIEW, "category 'other' is not safe to handle automatically")
    if triage.category == Category.billing:
        return Decision(Route.HUMAN_REVIEW, "billing issues always need a human")
    if triage.priority == Priority.urgent:
        return Decision(Route.HUMAN_REVIEW, "urgent priority goes straight to a human")
    if triage.category == Category.question and triage.is_simple_question:
        return Decision(Route.AUTO_REPLY_DRAFT, "confident, simple question: reply drafted for human approval")
    return Decision(Route.TEAM_QUEUE, f"confident {triage.category.value}; needs team action")
