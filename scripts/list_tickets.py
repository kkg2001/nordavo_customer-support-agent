from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent.helpdesk import (  # noqa: E402
    DEFAULT_HELPDESK_URL,
    HelpdeskClient,
    HelpdeskTicket,
    redact_payment_details,
)


def format_ticket(ticket: HelpdeskTicket) -> str:
    return (
        f"--- {ticket.id} ---\n"
        f"Plan: {ticket.customer_plan or 'not provided'}\n"
        f"Subject: {redact_payment_details(ticket.subject)}\n"
        f"{redact_payment_details(ticket.body)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="List helpdesk tickets without submitting decisions.")
    parser.add_argument(
        "--status",
        choices=("open", "all"),
        default="open",
        help="List only open tickets (default) or all practice tickets.",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    client = HelpdeskClient(
        api_key=os.getenv("HELPDESK_API_KEY", ""),
        candidate_email=os.getenv("CANDIDATE_EMAIL", ""),
        base_url=os.getenv("HELPDESK_URL", DEFAULT_HELPDESK_URL),
    )
    tickets = client.list_tickets(status=args.status)
    print(f"{len(tickets)} ticket(s) returned (status={args.status}).")
    for ticket in tickets:
        print()
        print(format_ticket(ticket))


if __name__ == "__main__":
    main()
