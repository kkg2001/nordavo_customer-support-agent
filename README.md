# Support Ticket Agent

An agent that reads support tickets, classifies them, gives a priority with a short reason, drafts replies for simple questions, sends anything it is unsure about to a human, and logs every decision.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
y
python -m pytest -q                  # router + loader tests, no API key needed
python -m agent.cli                  # all tickets -> logs/run.jsonl, prints routes and cost per 100 tickets
python eval/run_eval.py              # accuracy on the 10 labelled tickets -> eval/results.json
python eval_table.py                 # eval results as a markdown table
python show_log.py                   # readable view of the log (priority reasons, drafts, route reasons)
```

## How it works

```
CSV -> triage (1 structured LLM call) -> router (deterministic rules) -> reply draft (only if routed to auto-reply) -> JSONL log
```

Each ticket ends in one of three routes:

| Route | Meaning |
|---|---|
| `auto_reply_draft` | Confident, simple question. A draft reply is attached for a human to approve. Nothing is sent automatically. |
| `team_queue` | Confident classification, but the ticket needs team action (for example a bug or a feature request). |
| `human_review` | The agent is unsure or the topic is risky. A human decides and the agent does not guess. |

## Choices

- **Single pass, no agent framework.** About 200 tickets per week with a fixed decision per ticket does not need loops or multi-agent orchestration. One call is cheaper, faster and easier to debug. I would add tools or retrieval only when a ticket needs information the agent does not have.
- **The model proposes, the code decides.** The model returns category, priority, a one-sentence reason, confidence and a `needs_human` flag. `router.py` then applies hard rules on top: model-flagged tickets, low confidence, risky keywords (refund, cancel, legal, security, anger, prompt-injection phrases), category `other`, billing, urgent priority, and any failure. The escalation logic is auditable and unit-tested instead of living only in a prompt.
- **Over-escalate by design.** A wrongly auto-sent reply costs more than a human reading one extra ticket. Replies are drafts for approval, never auto-sent.
- **Structured output with validation.** The model is asked for JSON that matches a Pydantic schema (schema mode first, plain JSON mode as a fallback), with one retry. If the output is still invalid, or the API fails, the ticket goes to a human. A bad response never crashes the batch.
- **Prompt injection.** Ticket text is wrapped in `<ticket>` tags and treated as data. Injection phrases also trigger escalation. [Add one line on how the agent handled ticket 24, after you check the log.]
- **Separate reply step.** The reply is generated only for confident simple questions. This keeps triage cheap and lets me tune the two prompts independently.
- **Model:** `openai/gpt-oss-20b` on Groq's free tier, chosen because Groq lists it as supporting structured outputs and the free tier let me run the whole eval at no cost. Only `llm.py` talks to the provider, so switching models is a one-file change.
- **Logging:** one JSONL line per ticket with category, priority, priority reason, confidence, route and route reason, draft reply, tokens, cost, latency, prompt version and any error.

## Eval (10 tickets)

I picked 10 tickets at random from the 30 and labelled them myself: category, priority, and whether a human should handle the ticket (`should_escalate`).

**Labelling rubric.** Categories use the same definitions as `prompts/triage_v1.md`. `should_escalate = yes` means a human must decide before any reply or action when money, an outage, an angry customer, legal or privacy matters, or an unclear mixed request is involved.

**Important caveat on the labels.** My first labels contained errors: some were attached to the wrong ticket id, and three used a category that does not exist. I corrected them after seeing the agent's output, so the first runs are not clean measurements. I report all three runs for transparency. The last run uses the final labels, and I did not change any label after it.

| Metric | Run 1 (label errors) | Run 2 (partly corrected) | Run 3 (final labels) |
|---|---|---|---|
| Category accuracy | 30% | 50% | **80%** |
| Priority exact | 30% | 20% | **20%** |
| Priority within ±1 level | 80% | 90% | **90%** |
| Escalation decision | 70% | 60% | **90%** |

Final run, ticket by ticket: [paste the output of `python eval_table.py` here]

**What the final run shows**
- **Priority is the weak spot.** The agent inflates priority on broken things (tickets 9, 12, 13 and 23 came back `high`, and 20 came back `urgent`) and deflates it on others (4, 26 and 30 came back `low` where I labelled `medium`). Only ticket 12 is two levels off, which is why the ±1 score is high. Priority is partly subjective, and on ticket 20 an outage blocking every user arguably fits the rubric's "urgent" better than my `high`.
- **Category misses are 26 and 30.** Ticket 30 (cancel account and delete data under GDPR) was labelled `feature_request`, which is wrong. Ticket 26 (a how-to plus a refund request) was labelled `other`. Both still went to a human, so the safety behaviour held even though the category did not.
- **One escalation miss.** Ticket 9, a bug that appeared after a deploy, went to `team_queue` because the model was confident. I labelled it as needing a human, and the router has no rule for post-deploy regressions.
- **Run-to-run variation.** The model is a reasoning model, and temperature 0 did not make it fully repeatable (for example, ticket 29 changed route between runs). [Add your own repeat-run numbers if you ran it again.]
- **Small sample.** With n=10, one ticket moves a score by 10 points. Treat these numbers as a smoke test, not a precise measurement. I did not tune the prompt to the eval tickets. [If you did tune it, say what changed and report v1 and v2 side by side.]

## Cost per 100 tickets

Measured from token counts returned by the API, not guessed.

- Full run of 30 tickets: **$[X] per 100 tickets** (from `python -m agent.cli`).
- The three 10-ticket eval runs gave $0.20 to $0.27 per 100 tickets, for comparison.
- Price basis: [model] at $[input] per 1M input tokens and $[output] per 1M output tokens, from Groq's pricing page on [date] (see `pricing.json`).
- I ran on the free tier, so my actual spend was $0. The figure above is the paid-tier equivalent.
- Cost drivers: the reply call happens only for confident simple questions, so most tickets cost one call. Shorter prompts and a smaller model would lower it further.

## Assumptions

- There is no knowledge base or account data, so drafts use only the ticket text and general knowledge, and list assumptions for the reviewer to verify.
- A human approves every draft. Nothing is sent automatically.
- Tickets are in English and short enough that truncation is not needed.
- Free-tier rate limits apply, so `llm.py` retries with backoff on rate-limit errors.

## What I would do with more time

- A larger, stratified eval set with a separate holdout, and per-prompt-version results tracked in CI.
- Better priority calibration: concrete examples per level in the prompt, and a check of how confidence relates to correctness.
- A router rule for recent regressions, and a better treatment of mixed-category tickets (tickets 25 and 26).
- Retrieval over help-center documents so drafted replies are grounded in the product's real behaviour.
- A feedback loop: human corrections become new eval cases and examples.
- Duplicate and related-ticket detection, SLA-aware priority, and async batching for higher volume.

## Harness

Describes how I built this with AI tooling. None of these files affect the agent at runtime.

- **`.cursor/rules/`**: [describe your actual rule files, for example project-wide rules, router rules, prompt rules].
- **`CLAUDE.md`**: [keep this bullet only if you used Claude Code. Describe the workflow and guardrails.]
- **MCP**: none. The agent and the build needed no external tools.
- **Workflow:** [one or two lines on how you used the tool: plan first, tests first, how you checked its work.]

## Repo layout

```
src/agent/     pipeline, router, llm wrapper, logger, cost
prompts/       versioned triage and reply prompts
eval/          run_eval.py, labels.csv, results.json
tests/         router and loader tests
data/          tickets.csv
examples/      sample_run.jsonl (a real log)
```