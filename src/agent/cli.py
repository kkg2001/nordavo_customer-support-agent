import argparse
import json
from dotenv import load_dotenv
from .logger import JsonlLogger
from .pipeline import DEFAULT_MODEL, load_tickets, run_batch


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Support ticket triage agent")
    ap.add_argument("--csv", default="data/tickets.csv")
    ap.add_argument("--out", default="logs/run.jsonl")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    tickets = load_tickets(args.csv)[: args.limit]
    results = run_batch(tickets, JsonlLogger(args.out), args.model)

    routes: dict[str, int] = {}
    for r in results:
        routes[r["route"]] = routes.get(r["route"], 0) + 1
    total = sum(r["cost_usd"] for r in results)
    print(json.dumps({"tickets": len(results), "routes": routes,
                      "total_cost_usd": round(total, 4),
                      "cost_per_100_tickets_usd": round(total / max(len(results), 1) * 100, 4)}, indent=2))


if __name__ == "__main__":
    main()
