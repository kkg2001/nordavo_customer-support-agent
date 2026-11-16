import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open("eval/results.json", encoding="utf-8"))
s = d["summary"]
print(f"Model: {s['model']}  |  n = {s['n']}\n")
print("| Metric | Result |\n|---|---|")
print(f"| Category accuracy | {s['category_acc']:.0%} |")
print(f"| Priority exact | {s['priority_exact']:.0%} |")
print(f"| Priority within ±1 level | {s['priority_within_1']:.0%} |")
print(f"| Escalation decision accuracy | {s['escalation_acc']:.0%} |")
print("\n| Ticket | Gold (cat / pri / escalate) | Agent (cat / pri / route) | Cat | Pri | Esc |\n|---|---|---|---|---|---|")
for r in d["rows"]:
    g, p = r["gold"], r["pred"]
    print(f"| {r['ticket_id']} | {g['category']} / {g['priority']} / {g['should_escalate']} | "
          f"{p['category']} / {p['priority']} / {p['route']} | "
          f"{'✓' if r['category_ok'] else '✗'} | {'✓' if r['priority_ok'] else '✗'} | {'✓' if r['escalation_ok'] else '✗'} |")