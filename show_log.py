import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
path = sys.argv[1] if len(sys.argv) > 1 else "logs/run.jsonl"
for line in open(path, encoding="utf-8"):
    r = json.loads(line)
    print(f"#{r['ticket_id']}  {r['category']} / {r['priority']}  confidence={r['confidence']}")
    print(f"   priority reason: {r['priority_reason']}")
    print(f"   route: {r['route']}  because: {r['route_reason']}")
    if r["draft_reply"]:
        print(f"   draft reply: {r['draft_reply']}")
    print(f"   tokens in/out: {r['input_tokens']}/{r['output_tokens']}  cost: ${r['cost_usd']}  error: {r['error']}\n")