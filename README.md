# Roosterly helpdesk agent

## How to run

Fresh clone: install dependencies, copy `.env.example` to `.env`, then set `HELPDESK_API_KEY`, `CANDIDATE_EMAIL`, and `GROQ_API_KEY`. Never commit `.env`.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
py -m pip install -e ".[dev]"
py -m pytest -q
py -m agent.helpdesk_cli --api-status       # prints the current mode plus counts of open and handled tickets, along with a list of supported API endpoints
py scripts/list_tickets.py                  # lists all the open tickets
py scripts/list_tickets.py --status all     # lists all practice tickets, not just open ones,
py -m agent.helpdesk_cli --ticket-id T005   # fetches status details for ticket T005
py -m agent.helpdesk_cli --show-examples    # print the ten labelled examples (GET only)
py -m agent.helpdesk_cli                    # all open tickets; dry run
py -m agent.helpdesk_cli --limit 1          # one-ticket demo; dry run
py -m agent.helpdesk_cli --limit 1 --submit # post for first open ticket
py -m agent.helpdesk_cli --submit           # post for all open tickets
py -m agent.helpdesk_cli --eval-examples    # evaluate ten labelled examples; no submission
py -m agent.helpdesk_cli --reset-only       # reopen practice tickets; no ticket actions
py -m agent.helpdesk_cli --submit --reset   # final run: reset, then submit practice tickets
Get-Content .\logs\helpdesk_run.jsonl -Tail 5
Get-Content .\logs\submitted_run.jsonl -Tail 5
```

Dry runs write to `logs/helpdesk_run.jsonl`; `--submit` writes to `logs/submitted_run.jsonl`. Use `--out <path>` to override either default. `--reset-only` reopens all practice tickets and exits without submitting actions. `--submit` performs real actions and sends replies; `--submit --reset` resets practice tickets first, then processes them. Logs contain one record per ticket, not its body.

Example output (ticket counts and costs vary):

```text
Dry run:
[T001] language=nl category=question priority=P4 priority_reason="General password reset question." action=reply triage_status=succeeded submitted_action=- submission_status=dry_run
Summary: "submitted": false, "log": "logs/helpdesk_run.jsonl"

Submit:
[T001] language=nl category=question priority=P4 priority_reason="General password reset question." action=reply triage_status=succeeded submitted_action=reply submission_status=submitted
Summary: "submitted": true, "log": "logs/submitted_run.jsonl"
```

## Decisions

1. Groq proposes structured triage; deterministic code routes. Only FAQ-matched simple questions get fixed FAQ replies.
2. The model proposes Dutch, English, or German; a conservative language check must agree or the ticket is handed off. Copilot helped build and test the agent, not decide live actions.
3. I assume API priorities are P1–P4 and pagination is stable. Safety rules override conflicting eval labels.

## Reliability

The client serializes requests at 0.21-second minimum intervals (under five calls/second). It retries 429 using `Retry-After` and random 503s with bounded backoff, including POST actions; if a retry finds the ticket already answered, the API's 409 is recorded as `already_handled` rather than retried. Other 4xx responses fail explicitly. Requests with ambiguous network failures on POST are not retried; they are logged for review. Decisions append to JSONL, so after a crash rerun: handled tickets are omitted or return 409. Ticket text is untrusted, card/IBAN patterns are redacted, `.env` is ignored, and raw bodies are not logged.

## Eval and fix

Before the latest fix, the official 10-example eval scored category 100%, priority 100%, action 50%, and language 100%; a Dutch status question containing “storing” was incorrectly handed off (focused case: 0/1). The fix stopped treating that word alone as an active outage while preserving escalation for explicit outage reports. Afterward, the focused case replied with the F11 status-page answer (1/1). The official score remained 100% / 100% / 50% / 100% because that case is not in the API's ten examples; the action mismatches are deliberate policy handoffs.

Latest official eval output:

```json
{
  "examples": 10,
  "correct": {"category": 10, "priority": 10, "action": 5, "language": 10},
  "accuracy": {"category": 1.0, "priority": 1.0, "action": 0.5, "language": 1.0},
  "failures": ["E01", "E02", "E05", "E07", "E08"],
  "input_tokens": 15833,
  "output_tokens": 4221,
  "total_cost_usd": 0.036938,
  "cost_per_100_examples_usd": 0.3694
}
```

Cost per 100 tickets: `$0.036938 / 10 * 100 = $0.36938` (about **$0.3694**). Eval labels come from the API, not the model.

## What I would improve

Next, add multilingual and escalation eval cases. I would make explicit that safety policy overrides labels that expect unsafe automatic replies or closure.
