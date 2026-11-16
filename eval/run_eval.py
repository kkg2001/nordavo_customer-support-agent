import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dotenv import load_dotenv  # noqa: E402
from agent.llm import DEFAULT_MODEL  # noqa: E402
from agent.logger import JsonlLogger  # noqa: E402
from agent.pipeline import load_tickets, process_ticket  # noqa: E402

ORDER = ["low", "medium", "high", "urgent"]


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/tickets.csv")
    ap.add_argument("--labels", default="eval/labels.csv")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="eval/results.json")
    args = ap.parse_args()

    labels = {r["ticket_id"].strip(): r for r in csv.DictReader(open(args.labels, encoding="utf-8-sig"))}
    if not labels:
        sys.exit("eval/labels.csv has no rows. Label ~10 tickets first.")
    tickets = [t for t in load_tickets(args.csv) if t.id in labels]
    logger = JsonlLogger("logs/eval_run.jsonl")

    rows, cat_ok, pri_ok, pri_near, esc_ok, cost = [], 0, 0, 0, 0, 0.0
    for t in tickets:
        r = process_ticket(t, logger, args.model)
        g = labels[t.id]
        c = r["category"] == g["category"].strip()
        p = r["priority"] == g["priority"].strip()
        near = (r["priority"] in ORDER and abs(ORDER.index(r["priority"]) - ORDER.index(g["priority"].strip())) <= 1)
        e = (r["route"] == "human_review") == (g["should_escalate"].strip().lower() in ("yes", "y", "true", "1"))
        cat_ok += c; pri_ok += p; pri_near += near; esc_ok += e; cost += r["cost_usd"]
        rows.append({"ticket_id": t.id, "gold": g, "pred": {k: r[k] for k in ("category", "priority", "route", "route_reason")},
                     "category_ok": c, "priority_ok": p, "escalation_ok": e})
        print(f"{t.id:>6}  cat {'✓' if c else '✗'} ({g['category']}→{r['category']})  "
              f"pri {'✓' if p else '✗'} ({g['priority']}→{r['priority']})  esc {'✓' if e else '✗'} [{r['route']}]")

    n = len(tickets)
    summary = {"n": n, "category_acc": cat_ok / n, "priority_exact": pri_ok / n,
               "priority_within_1": pri_near / n, "escalation_acc": esc_ok / n,
               "cost_per_100_tickets_usd": round(cost / n * 100, 4), "model": args.model}
    print("\n" + json.dumps(summary, indent=2))
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
