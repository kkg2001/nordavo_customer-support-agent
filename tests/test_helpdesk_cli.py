import json
import sys

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
