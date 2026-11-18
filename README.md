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

- One structured Groq call proposes triage; deterministic code selects reply or human handoff. Only a simple question with a matching FAQ topic can receive a reply. Replies are fixed, localized FAQ templates rather than model-written text; unsupported language or topic matches go to a human.
- Billing, category `other`, urgent, sensitive, angry, ambiguous, and non-FAQ cases go to a human. Ticket text is untrusted; card and IBAN patterns are redacted.
- Cost uses `pricing.json`; unknown rates stay unknown. Copilot helped build the agent. Assumptions: documented pagination is stable; supported languages are Dutch, English, and German.

## Reliability

The client paginates open tickets, stays below five requests per second, retries GET requests on 429 via `Retry-After` and 503 with backoff, and treats 409 as already handled. It does not retry POST actions after transient errors, avoiding possible duplicate customer actions. Reruns rely on server state/409; do not run concurrent submissions. Per-ticket Groq failures hand off safely.

Last recorded 30-ticket run: 30 successful actions (3 replies, 26 handoffs, 1 close); Groq rate-limited 25, leaving their triage fields unavailable. Actions completed, but classification did not.

## Eval and fix

The eval uses ten `GET /examples` labels; the model does not write them. Latest run: category 100% (10/10), priority 100% (10/10), action 50% (5/10), and language 100% (10/10). It used 15,833 input tokens and 3,941 output tokens; cost was `$0.035538` for 10 examples (`$0.3554` per 100).

Action mismatches were E01, E02, E05, E07, and E08. These are intentional differences from the supplied labels under the stricter routing policy: E01 is a bug/compatibility issue, E02 and E07 are billing, E05 is a feature request, and E08 is category `other` spam. The policy sends each to a human rather than replying or closing automatically. Do not interpret the 50% action score as a model failure alone; it also reflects this deliberate policy/label conflict.

## What I would improve

The language/topic checks intentionally prefer human review when uncertain. Add more multilingual edge cases to the labelled evaluation set before relaxing those checks.
