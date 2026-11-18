import json
import sys

import pytest

from agent import helpdesk_cli
from agent.helpdesk_cli import format_ticket_result, redact_display_data


def test_format_ticket_result_shows_classification_and_post_status():
    result = {
        "ticket_id": "T001",
        "language": "nl",
        "category": "question",
        "priority": "P3",
        "priority_reason": "This is a low-impact question.",
        "action": "reply",
        "triage_status": "succeeded",
        "submitted_action": "reply",
        "submission_status": "submitted",
    }

    assert format_ticket_result(result) == (
        "[T001] language=nl category=question priority=P3 "
        "priority_reason=\"This is a low-impact question.\" action=reply "
        "triage_status=succeeded "
        "submitted_action=reply submission_status=submitted"
    )


def test_format_ticket_result_marks_missing_classification_and_errors():
    result = {
        "ticket_id": "T002",
        "language": None,
        "category": None,
        "priority": None,
        "action": "handoff",
        "submitted_action": "handoff",
        "submission_status": "submitted",
        "error": "RateLimitError",
    }

    assert "language=unavailable" in format_ticket_result(result)
    assert "category=unavailable" in format_ticket_result(result)
    assert "priority=unavailable" in format_ticket_result(result)
    assert "action=handoff" in format_ticket_result(result)
    assert "error=RateLimitError" in format_ticket_result(result)


def test_redact_display_data_redacts_nested_ticket_text():
    data = {"ticket": {"body": "Card 4111 1111 1111 1111"}, "events": ["safe"]}

    redacted = redact_display_data(data)

    assert "4111 1111 1111 1111" not in str(redacted)
    assert redacted["events"] == ["safe"]


def test_api_status_cli_prints_status_and_endpoint_purposes(monkeypatch, capsys):
    class Client:
        def __init__(self, **kwargs):
            pass

        def get_status(self):
            return {"mode": "practice", "open": 1, "handled": 29}

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(sys, "argv", ["helpdesk_cli", "--api-status"])

    helpdesk_cli.main()

    output = json.loads(capsys.readouterr().out)

    assert output["status"] == {"mode": "practice", "open": 1, "handled": 29}
    reply_endpoint = next(
        endpoint
        for endpoint in output["endpoints"]
        if endpoint["path"] == "/tickets/{id}/reply"
    )
    assert reply_endpoint == {
        "method": "POST",
        "path": "/tickets/{id}/reply",
        "description": "Send a reply to the customer.",
    }


def test_ticket_detail_cli_redacts_payment_details(monkeypatch, capsys):
    class Client:
        def __init__(self, **kwargs):
            pass

        def get_ticket(self, ticket_id):
            return {"id": ticket_id, "body": "Card 4111 1111 1111 1111"}

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(sys, "argv", ["helpdesk_cli", "--ticket-id", "T005"])

    helpdesk_cli.main()

    printed = capsys.readouterr().out
    assert "4111 1111 1111 1111" not in printed
    assert "[REDACTED CARD]" in printed


def test_eval_cli_prints_progress_before_final_metrics(monkeypatch, capsys):
    class Client:
        def __init__(self, **kwargs):
            pass

        def get_examples(self):
            return [{"id": "E01"}]

    def fake_evaluate(agent, examples, on_progress=None):
        if on_progress is not None:
            on_progress(1, len(examples), examples[0]["id"])
        return {"accuracy": {"category": 1.0}}

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskAgent", lambda *args: object())
    monkeypatch.setattr(helpdesk_cli, "evaluate_examples", fake_evaluate)
    monkeypatch.setattr(sys, "argv", ["helpdesk_cli", "--eval-examples"])

    helpdesk_cli.main()

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Fetching labelled examples from GET /examples..."
    assert lines[1].startswith("Evaluating 1 labelled examples with model ")
    assert lines[2] == "Evaluating example 1/1: E01"
    assert json.loads("\n".join(lines[3:])) == {"accuracy": {"category": 1.0}}


def test_show_examples_cli_prints_redacted_labels_without_running_agent(monkeypatch, capsys):
    examples = [
        {
            "id": "E01",
            "subject": "Invoice question",
            "body": "Card 4111 1111 1111 1111",
            "label": {"category": "billing", "action": "handoff"},
        }
    ]
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def get_examples(self):
            calls.append("GET /examples")
            return examples

    def unexpected_agent(*args):
        raise AssertionError("showing examples must not initialize the model agent")

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskAgent", unexpected_agent)
    monkeypatch.setattr(sys, "argv", ["helpdesk_cli", "--show-examples"])

    helpdesk_cli.main()

    output = capsys.readouterr().out
    displayed = json.loads(output)
    assert calls == ["GET /examples"]
    assert displayed[0]["label"] == {
        "category": "billing",
        "action": "handoff",
    }
    assert "[REDACTED CARD]" in displayed[0]["body"]
    assert "4111 1111 1111 1111" not in output


def test_reset_only_reopens_practice_tickets_without_running_agent(monkeypatch, capsys):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def reset_practice(self):
            calls.append("POST /practice/reset")
            return {"reset": True}

    def unexpected_agent(*args):
        raise AssertionError("--reset-only must not initialize the agent")

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskAgent", unexpected_agent)
    monkeypatch.setattr(sys, "argv", ["helpdesk_cli", "--reset-only"])

    helpdesk_cli.main()

    assert calls == ["POST /practice/reset"]
    assert capsys.readouterr().out.strip() == "Practice tickets reset."


@pytest.mark.parametrize(
    "options",
    [
        ["--submit"],
        ["--reset"],
        ["--eval-examples"],
        ["--limit", "1"],
        ["--api-status"],
    ],
)
def test_reset_only_rejects_other_run_or_inspection_options(
    monkeypatch, capsys, options
):
    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["helpdesk_cli", "--reset-only", *options]
    )

    with pytest.raises(SystemExit) as exc:
        helpdesk_cli.main()

    assert exc.value.code == 2


@pytest.mark.parametrize(
    "submit,expected_path",
    [
        (False, "logs/helpdesk_run.jsonl"),
        (True, "logs/submitted_run.jsonl"),
    ],
)
def test_cli_uses_separate_default_logs_for_dry_run_and_submission(
    monkeypatch, capsys, submit, expected_path
):
    log_paths = []
    argv = ["helpdesk_cli"]
    if submit:
        argv.append("--submit")

    class Client:
        def __init__(self, **kwargs):
            pass

    class Agent:
        def __init__(self, client, logger, model):
            log_paths.append(logger)

        def run(self, limit=None, submit=False, on_result=None):
            return []

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskAgent", Agent)
    monkeypatch.setattr(
        helpdesk_cli, "JsonlLogger", lambda path: log_paths.append(path) or path
    )
    monkeypatch.setattr(sys, "argv", argv)

    helpdesk_cli.main()

    assert log_paths == [expected_path, expected_path]
    assert json.loads(capsys.readouterr().out)["log"] == expected_path


def test_cli_explicit_log_path_overrides_mode_default(monkeypatch, capsys):
    log_paths = []

    class Client:
        def __init__(self, **kwargs):
            pass

    class Agent:
        def __init__(self, client, logger, model):
            log_paths.append(logger)

        def run(self, limit=None, submit=False, on_result=None):
            return []

    monkeypatch.setattr(helpdesk_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskClient", Client)
    monkeypatch.setattr(helpdesk_cli, "HelpdeskAgent", Agent)
    monkeypatch.setattr(
        helpdesk_cli, "JsonlLogger", lambda path: log_paths.append(path) or path
    )
    monkeypatch.setattr(
        sys, "argv", ["helpdesk_cli", "--submit", "--out", "logs/custom.jsonl"]
    )

    helpdesk_cli.main()

    assert log_paths == ["logs/custom.jsonl", "logs/custom.jsonl"]
    assert json.loads(capsys.readouterr().out)["log"] == "logs/custom.jsonl"
