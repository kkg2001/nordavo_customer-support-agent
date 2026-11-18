from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv

from .helpdesk import (
    DEFAULT_HELPDESK_URL,
    HelpdeskAgent,
    HelpdeskClient,
    evaluate_examples,
    redact_payment_details,
)
from .llm import DEFAULT_MODEL
from .logger import JsonlLogger

API_ENDPOINTS = [
    {
        "method": "GET",
        "path": "/status",
        "description": "Show your mode and the number of open and handled tickets.",
    },
    {
        "method": "GET",
        "path": "/examples",
        "description": "Return labelled example tickets for evaluation.",
    },
    {
        "method": "GET",
        "path": "/tickets?limit=10&cursor=<id>&status=open",
        "description": "List tickets with pagination; status can be open or all.",
    },
    {
        "method": "GET",
        "path": "/tickets/{id}",
        "description": "Return one ticket and its handling details, if handled.",
    },
    {
        "method": "POST",
        "path": "/tickets/{id}/reply",
        "description": "Send a reply to the customer.",
    },
    {
        "method": "POST",
        "path": "/tickets/{id}/handoff",
        "description": "Hand the ticket to the human support team.",
    },
    {
        "method": "POST",
        "path": "/tickets/{id}/close",
        "description": "Close the ticket without action, for spam or empty tickets.",
    },
    {
        "method": "POST",
        "path": "/practice/reset",
        "description": "Re-open all practice tickets so the run can be repeated.",
    },
]


def format_ticket_result(result: dict) -> str:
    fields = {
        "language": result.get("language") or "unavailable",
        "category": result.get("category") or "unavailable",
        "priority": result.get("priority") or "unavailable",
        "priority_reason": result.get("priority_reason") or "unavailable",
        "action": result.get("action") or "unavailable",
        "triage_status": result.get("triage_status") or "unknown",
        "submitted_action": result.get("submitted_action") or "-",
        "submission_status": result.get("submission_status") or "unknown",
    }
    rendered = []
    for key, value in fields.items():
        if key == "priority_reason":
            value = json.dumps(value, ensure_ascii=False)
        rendered.append(f"{key}={value}")
    line = f"[{result.get('ticket_id', 'unknown')}] " + " ".join(rendered)
    if result.get("error"):
        line += f" error={result['error']}"
    return line


def redact_display_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_payment_details(value)
    if isinstance(value, list):
        return [redact_display_data(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_display_data(item) for key, item in value.items()}
    return value


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the Roosterly helpdesk agent.")
    parser.add_argument(
        "--out",
        help="Override the default log path (dry run: logs/helpdesk_run.jsonl; submit: logs/submitted_run.jsonl).",
    )
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Post decisions to the helpdesk; otherwise only write a local dry-run log.",
    )
    reset_options = parser.add_mutually_exclusive_group()
    reset_options.add_argument(
        "--reset",
        action="store_true",
        help="Re-open all practice tickets before running (requires --submit).",
    )
    reset_options.add_argument(
        "--reset-only",
        action="store_true",
        help="Re-open all practice tickets without running the agent or submitting actions.",
    )
    parser.add_argument(
        "--eval-examples",
        action="store_true",
        help="Evaluate against the API's labelled examples without submitting decisions.",
    )
    inspection = parser.add_mutually_exclusive_group()
    inspection.add_argument(
        "--api-status",
        action="store_true",
        help="Fetch and display API status (read-only).",
    )
    inspection.add_argument(
        "--ticket-id",
        help="Fetch and display one ticket and its handling details (read-only).",
    )
    inspection.add_argument(
        "--show-examples",
        action="store_true",
        help="Fetch and display the API's labelled evaluation examples (read-only).",
    )
    args = parser.parse_args()
    if args.reset and not args.submit:
        parser.error("--reset requires --submit.")
    if args.reset_only and (
        args.submit
        or args.eval_examples
        or args.limit is not None
        or args.api_status
        or args.ticket_id
        or args.show_examples
    ):
        parser.error(
            "--reset-only cannot be combined with submission, run, eval, or inspection options."
        )
    if (args.api_status or args.ticket_id or args.show_examples) and (
        args.submit
        or args.reset
        or args.reset_only
        or args.eval_examples
        or args.limit is not None
    ):
        parser.error("API inspection options cannot be combined with run or eval options.")

    try:
        client = HelpdeskClient(
            api_key=os.getenv("HELPDESK_API_KEY", ""),
            candidate_email=os.getenv("CANDIDATE_EMAIL", ""),
            base_url=os.getenv("HELPDESK_URL", DEFAULT_HELPDESK_URL),
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        if args.reset_only:
            client.reset_practice()
            print("Practice tickets reset.")
            return
        if args.api_status:
            status = client.get_status()
            print(
                json.dumps(
                    {
                        "status": redact_display_data(status),
                        "endpoints": API_ENDPOINTS,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        if args.ticket_id:
            response = client.get_ticket(args.ticket_id)
            print(json.dumps(redact_display_data(response), indent=2, ensure_ascii=False))
            return
        if args.show_examples:
            examples = client.get_examples()
            print(
                json.dumps(redact_display_data(examples), indent=2, ensure_ascii=False)
            )
            return

        model = args.model or os.getenv("TICKET_AGENT_MODEL", DEFAULT_MODEL)
        out_path = args.out or (
            "logs/submitted_run.jsonl" if args.submit else "logs/helpdesk_run.jsonl"
        )
        agent = HelpdeskAgent(client, JsonlLogger(out_path), model)
        if args.eval_examples:
            print("Fetching labelled examples from GET /examples...", flush=True)
            examples = client.get_examples()
            print(
                f"Evaluating {len(examples)} labelled examples with model {model}.",
                flush=True,
            )
            result = evaluate_examples(
                agent,
                examples,
                on_progress=lambda index, total, example_id: print(
                    f"Evaluating example {index}/{total}: {example_id}",
                    flush=True,
                ),
            )
            print(json.dumps(result, indent=2), flush=True)
            return
        if args.reset:
            client.reset_practice()
            print("Practice tickets reset.")
        results = agent.run(
            limit=args.limit,
            submit=args.submit,
            on_result=lambda result: print(format_ticket_result(result), flush=True),
        )
    except Exception as exc:
        print(f"Helpdesk run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    routes: dict[str, int] = {}
    for result in results:
        action = result["submitted_action"] or result["action"]
        routes[action] = routes.get(action, 0) + 1
    ticket_costs = [result["cost_usd"] for result in results]
    total_cost = (
        sum(ticket_costs)
        if all(cost is not None for cost in ticket_costs)
        else None
    )
    count = len(results)
    print(
        json.dumps(
            {
                "tickets": count,
                "actions": routes,
                "total_cost_usd": round(total_cost, 4) if total_cost is not None else None,
                "cost_per_100_tickets_usd": (
                    round(total_cost / count * 100, 4)
                    if total_cost is not None and count
                    else None
                ),
                "submitted": args.submit,
                "log": out_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
