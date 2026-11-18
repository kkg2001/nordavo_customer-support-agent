## How to run

From a fresh clone, install and configure:

```powershell
py -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Set HELPDESK_API_KEY, CANDIDATE_EMAIL, and GROQ_API_KEY in .env
py -m pytest -q
py -m agent.helpdesk_cli --api-status
py scripts/list_tickets.py                 # open tickets
py scripts/list_tickets.py --status all
py -m agent.helpdesk_cli --ticket-id T005
py -m agent.helpdesk_cli --show-examples
py -m agent.helpdesk_cli --eval-examples
py -m agent.helpdesk_cli                   # all tickets, dry run
py -m agent.helpdesk_cli --limit 1         # one-ticket dry-run demo
Get-Content .\logs\helpdesk_run.jsonl -Tail 5
py -m agent.helpdesk_cli --submit --reset  # real final practice run
```

`--submit` posts real actions; replies reach customers. Raw run logs are local and ignored; `logs/sample_run.jsonl` is sanitized.

## Decisions

1. Groq makes one structured triage proposal; deterministic code chooses reply or handoff. This keeps escalation rules out of model judgment.
2. Replies use fixed FAQ-based templates. The model proposes Dutch, English, or German; a conservative language check must agree or the ticket goes to a human. I used Copilot to help build and test the code, not to make live ticket decisions.
3. I assumed API priorities are P1–P4 and documented pagination is stable. When the brief and eval labels conflict, the safer human-handoff policy takes precedence.

## Reliability

GET requests retry 429 using `Retry-After` and 503 with backoff; POST actions are not retried to avoid duplicates. A 409 means already handled. After a crash, rerun: handled tickets are omitted by the open-ticket listing or reported as 409. An ambiguous failed POST is logged for review. Ticket text is treated as untrusted, card/IBAN patterns are redacted, `.env` is ignored, and raw ticket bodies are not logged.

## Eval and fix

The earlier baseline was category 90%, priority 100%, action 90%, language 100%. The fix tightened deterministic escalation, matched FAQ topics to tickets, and replaced model-written drafts with localized FAQ templates. Latest 10-example eval: category 100% (10/10), priority 100% (10/10), action 50% (5/10), language 100% (10/10). Action mismatches E01, E02, E05, E07, and E08 reflect deliberate handoff for bug, billing, feature-request, and `other` tickets, although the labels expect replies or spam closure.

Cost: `$0.035538 / 10 tickets * 100 = $0.35538`, or about **$0.3554 per 100 tickets**. Results and token counts are in [eval/results.json](./eval/results.json); a sanitized historical v3 log sample is in [logs/sample_run.jsonl](./logs/sample_run.jsonl).

## What I would improve

Next, add more multilingual and escalation edge cases to the eval set. I would clarify that the written safety policy outranks labels that expect an automatic response or closure for a ticket the policy says to hand off.
