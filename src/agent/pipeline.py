from __future__ import annotations
import csv
import time
from pathlib import Path
from .cost import cost_usd
from .llm import DEFAULT_MODEL, Usage, call_structured
from .logger import JsonlLogger
from .router import decide
from .schemas import Reply, Route, Ticket, Triage

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
TRIAGE_PROMPT = (PROMPTS / "triage_v1.md").read_text()
REPLY_PROMPT = (PROMPTS / "reply_v1.md").read_text()
PROMPT_VERSION = "triage_v1/reply_v1"


def load_tickets(path: str | Path) -> list[Ticket]:
    """Tolerant loader: finds id/subject/body-like columns case-insensitively."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    def pick(row, *names):
        low = {(k or "").lower().strip(): v for k, v in row.items()}
        for n in names:
            if low.get(n):
                return low[n]
        return ""

    return [
        Ticket(id=str(pick(r, "id", "ticket_id", "ticket id") or i + 1),
               subject=pick(r, "subject", "title"),
               body=pick(r, "body", "description", "message", "text"))
        for i, r in enumerate(rows)
    ]


def process_ticket(ticket: Ticket, logger: JsonlLogger | None = None, model: str = DEFAULT_MODEL) -> dict:
    t0 = time.time()
    usage = Usage()
    triage: Triage | None = None
    reply: Reply | None = None
    error: str | None = None
    user = f"<ticket>\n{ticket.text}\n</ticket>"
    try:
        triage, u = call_structured(TRIAGE_PROMPT, user, Triage, model)
        usage += u
    except Exception as e:  # never crash the batch; escalate instead
        error = f"{type(e).__name__}: {e}"

    decision = decide(triage, ticket.text, error)
    if decision.route == Route.AUTO_REPLY_DRAFT:
        try:
            reply, u = call_structured(REPLY_PROMPT, user, Reply, model)
            usage += u
        except Exception as e:
            error = f"reply drafting failed: {e}"
            decision = decide(None, ticket.text, error)

    result = {
        "ticket_id": ticket.id,
        "category": triage.category.value if triage else None,
        "priority": triage.priority.value if triage else None,
        "priority_reason": triage.priority_reason if triage else None,
        "confidence": triage.confidence if triage else None,
        "route": decision.route.value,
        "route_reason": decision.reason,
        "draft_reply": reply.draft_reply if reply else None,
        "reply_assumptions": reply.assumptions if reply else None,
        "model": model, "prompt_version": PROMPT_VERSION,
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cost_usd": round(cost_usd(model, usage), 6),
        "latency_s": round(time.time() - t0, 2),
        "error": error,
    }
    if logger:
        logger.log(result)
    return result


def run_batch(tickets: list[Ticket], logger: JsonlLogger | None = None, model: str = DEFAULT_MODEL) -> list[dict]:
    return [process_ticket(t, logger, model) for t in tickets]
