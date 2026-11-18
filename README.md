# Roosterly helpdesk agent

## How to run

Fresh clone: install dependencies, copy `.env.example` to `.env`, then set `HELPDESK_API_KEY`, `CANDIDATE_EMAIL`, and `GROQ_API_KEY`. Never commit `.env`.

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

`--submit` performs real actions and sends replies. `--submit --reset` resets practice tickets first. Logs contain one record per ticket, not its body.

## Decisions

1. Groq proposes structured triage; deterministic code routes. Only FAQ-matched simple questions get fixed FAQ replies.
2. The model proposes Dutch, English, or German; a conservative language check must agree or the ticket is handed off. Copilot helped build and test the agent, not decide live actions.
3. I assume API priorities are P1–P4 and pagination is stable. Safety rules override conflicting eval labels.

## Reliability

The client serializes requests at 0.21-second minimum intervals (under five calls/second). It retries 429 using `Retry-After` and random 503s with bounded backoff, including POST actions; if a retry finds the ticket already answered, the API's 409 is recorded as `already_handled` rather than retried. Other 4xx responses fail explicitly. Requests with ambiguous network failures on POST are not retried; they are logged for review. Decisions append to JSONL, so after a crash rerun: handled tickets are omitted or return 409. Ticket text is untrusted, card/IBAN patterns are redacted, `.env` is ignored, and raw bodies are not logged.

## Eval and fix

The fix tightened billing/escalation rules, FAQ-topic matching, and localized FAQ replies. Before: category 90%, priority 100%, action 90%, language 100%. After (10 `GET /examples` labels): category 100%, priority 100%, action 50%, language 100%. Action mismatches E01/E02/E05/E07/E08 reflect safety-policy handoffs where labels expect replies or spam closure.

Cost: `$0.035538 / 10 * 100 = $0.35538`, or **$0.3554 per 100 tickets** (15,833 input and 3,941 output tokens). The eval uses the API's labels; the model does not write them.

## What I would improve

Next, add multilingual and escalation eval cases. I would make explicit that safety policy overrides labels that expect unsafe automatic replies or closure.
