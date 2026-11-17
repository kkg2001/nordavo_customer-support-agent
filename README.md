# Roosterly helpdesk agent

## How to run

From the repository root, copy `.env.example` to `.env` if needed and set `HELPDESK_API_KEY`, `CANDIDATE_EMAIL`, and `GROQ_API_KEY`. Never commit `.env`.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
py -m pip install -e ".[dev]"
py -m pytest -q
py -m agent.helpdesk_cli --api-status
py scripts/list_tickets.py
py scripts/list_tickets.py --status all
py -m agent.helpdesk_cli --ticket-id T005
py -m agent.helpdesk_cli --show-examples  # print the ten labelled examples (GET only)
py -m agent.helpdesk_cli                    # all open tickets; dry run
py -m agent.helpdesk_cli --limit 1          # one-ticket demo; dry run
py -m agent.helpdesk_cli --limit 1 --submit # post for first open ticket
py -m agent.helpdesk_cli --submit           # post for all open tickets
py -m agent.helpdesk_cli --eval-examples    # evaluate ten labelled examples; no submission
py -m agent.helpdesk_cli --submit --reset   # final run: reset, then submit practice tickets
Get-Content .\logs\helpdesk_run.jsonl -Tail 5
```

`--submit` posts real actions; replies reach customers. Use `--submit --reset` once for the final practice run. Each ticket prints language, category, priority, action, and status; `--limit` is for demos. Logs contain one record per ticket, not its body.

## Decisions

- One structured Groq call proposes triage and a draft; deterministic code selects reply, handoff, or close. Replies use FAQ facts and the customer's language. An English summary and FAQ reference help reviewers verify Dutch drafts.
- Sensitive, uncertain, urgent, and non-FAQ cases go to a human. Ticket text is untrusted; card and IBAN patterns are redacted.
- Cost uses `pricing.json`; unknown rates stay unknown. Copilot helped build the agent. Assumptions: documented pagination is stable; supported languages are Dutch, English, and German.

## Reliability

The client paginates open tickets, stays below five requests per second, retries 429 via `Retry-After` and 503 with backoff, and treats 409 as already handled. It does not retry ambiguous POST failures. Reruns rely on server state/409; do not run concurrent submissions. Groq failures hand off safely.

Last recorded 30-ticket run: 30 successful actions (3 replies, 26 handoffs, 1 close); Groq rate-limited 25, leaving their triage fields unavailable. Actions completed, but classification did not.

## Eval and fix

The eval uses ten `GET /examples` labels; the model does not write them. The fix added invoice-to-billing classification and clarified FAQ handling for F10 ideas and F12 compatibility. Before the fix: 90% category, 100% priority, 90% action, 100% language (misses E02, E05). Post-fix eval did not return; its score and cost are unverified.

Last completed eval cost: `$0.039653 / 10 * 100 = $0.39653 per 100 examples`. Rerun after rate limits allow; scores vary on this small set.

## What I would improve

Next, add bounded provider waits and eval progress without weakening handoff. The brief should define a confidence threshold and response-time target.
