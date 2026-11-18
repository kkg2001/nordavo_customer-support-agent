from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from .cost import known_cost_usd
from .llm import DEFAULT_MODEL, Usage, call_structured
from .logger import JsonlLogger

DEFAULT_HELPDESK_URL = "https://nakywgkztvzkihdjnwbc.supabase.co/functions/v1/helpdesk"
PROMPT_VERSION = "helpdesk_v4"
CONFIDENCE_THRESHOLD = 0.75
RETRY_LIMIT = 4
MIN_REQUEST_INTERVAL = 0.21
FAQ_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "faq.md"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "helpdesk_v4.md"

_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}\b", re.I)
_RISKY = re.compile(
    r"\b(refund\w*|charge ?back|disput\w* charge|overcharg\w*|terugbet\w*|terugkrijg\w*|"
    r"terugstort\w*|restitutie|geld terug|afschrijving betwist|dubbel afgeschreven|"
    r"cancel\w*|cancell\w*|opzeg\w*|annul\w*|stopzetten|contract wijzig\w*|"
    r"lawyer|attorney|legal action|law suit|sue\w*|advocaat|jurist|juridisch\w*|"
    r"rechtzaak|aankla\w*|"
    r"gdpr|avg|dsgvo|personal data|privacy request|persoonlijke gegevens|persoonsgegevens|"
    r"delete my data|gegevens verwijder\w*|recht op vergetelheid|inzage in (mijn )?gegevens|"
    r"legal|security incident|security issue|security concern|beveiligingsprobleem|"
    r"sicherheitsproblem|data loss|lost data|gegevensverlies|datenverlust|data breach|"
    r"unauthori[sz]ed access|account compromised|suspicious login|"
    r"beveiligingsincident|datalek|gehackt|verdachte login|account overgenomen|"
    r"threaten\w* to leave|leave the service|leave roosterly|"
    r"ik stap over|ik vertrek|ik zeg op|ik ga naar een ander systeem|ik stop met roosterly|"
    r"ik ben kwaad|ziedend|teleurgesteld|verschrikkelijk|"
    r"contract aanpas\w*|contract wijzig\w*|abonnement aanpassen|"
    r"ich kündige|ich werde kündigen|ich wechsle|ich verlasse|"
    r"refund|erstattung|rückerstattung|kündig\w*|anwalt|datenschutz|sicherheitsvorfall|"
    r"datenleck|gehackt|wütend|verärgert|enttäuscht|furious|angry|unacceptable|"
    r"unacceptabel|woedend|boos|schandalig|belachelijk|belogen|oplichters)\b",
    re.I,
)
_URGENT = re.compile(
    r"\b(outage|service down|system down|data loss|lost data|many users blocked|"
    r"everyone is blocked|all users are blocked|storing|uitval|iedereen geblokkeerd|"
    r"veel gebruikers geblokkeerd|alle gebruikers geblokkeerd|gegevensverlies|"
    r"ausfall|datenverlust|viele benutzer blockiert|alle benutzer blockiert)\b",
    re.I,
)
_INJECTION = re.compile(
    r"\b(ignore|disregard|forget) (all |any )?(the )?(previous|prior|above) instructions\b|"
    r"\b(reveal|print|show|exfiltrate) (the )?(system prompt|secrets|credentials)\b|"
    r"\bnegeer (alle )?(vorige|eerdere) instructies\b|"
    r"\bignoriere (alle )?(vorherigen|früheren) anweisungen\b",
    re.I,
)
_LANGUAGE_MARKERS = {
    "nl": {
        "aanmelden", "abonnement", "factuur", "hoe", "ik", "locatie", "medewerker",
        "gegevens", "gepland", "mijn", "naar", "niet", "onderhoud", "opgeslagen",
        "rekening", "storing", "taal", "talen", "u", "uw", "vanavond",
        "vestiging", "wachtwoord", "waar", "wat", "worden",
    },
    "en": {
        "can", "do", "does", "employee", "for", "how", "invoice", "is", "it",
        "language", "location", "my", "outage", "password", "please", "the",
        "they", "we", "what", "where", "with", "you", "your",
    },
    "de": {
        "abonnement", "bitte", "der", "die", "ein", "eine", "für", "ich", "ihr",
        "ist", "kann", "konto", "mit", "mitarbeiter", "mein", "nicht", "passwort",
        "rechnung", "sie", "sind", "sprache", "standort", "störung", "und", "was",
        "werden", "wie", "wo",
    },
}
_WORD = re.compile(r"\b[\wäöüß]+\b", re.I)
_BILLING_TERMS = re.compile(
    r"\b(invoice\w*|factuur\w*|rechnung\w*|bill\w*|billing|payment\w*|charge\w*|"
    r"betaling\w*|betaal\w*|afschrijving\w*|zahlung\w*|preis\w*|price\w*|"
    r"plan\s+price|planprijs|cost\w*|kosten|kost\w*|prijs\w*|how much|wat kost|"
    r"subscription\w*|abonnement\w*|terugbetaling\w*|terugbetalen|refund\w*)\b",
    re.I,
)
_FAQ_REFERENCE = re.compile(r"^F(?:0[1-9]|1[0-2])$")
_FAQ_TOPIC_PATTERNS = {
    "F01": re.compile(r"\b(password|wachtwoord|passwort|login|aanmelden|sign[ -]?in)\b", re.I),
    "F02": re.compile(r"\b(employee|medewerker|mitarbeiter|team member|teammitglied|invite|uitnodig\w*|einlad\w*)\b", re.I),
    "F03": re.compile(r"\b(shift|dienst|schicht|swap|tausch|ruil\w*)\b", re.I),
    "F04": re.compile(r"\b(payroll|salaris|loonk|nmbrs|loket|afas|csv|export\w*|abrechnung)\b", re.I),
    "F07": re.compile(r"\b(location|locatie|vestiging|standort|branch)\b", re.I),
    "F08": re.compile(r"\b(language|taal|sprache|sprachen)\b", re.I),
    "F09": re.compile(r"\b(data|gegevens|daten|server|storage|opslag|speicherung|stored|gespeichert)\b", re.I),
    "F11": re.compile(r"\b(status|outage|maintenance|storing|onderhoud|ausfall|wartung|verstoring|beschikbaar)\b", re.I),
}
_FAQ_REPLIES = {
    "F01": {
        "nl": "Ga naar app.roosterly.nl/login, kies 'Wachtwoord vergeten' en vul het e-mailadres van uw account in. De link is 60 minuten geldig. Ontvangt u binnen 10 minuten geen e-mail, controleer dan uw spammap.",
        "en": "Go to app.roosterly.nl/login, select 'Wachtwoord vergeten,' and enter your account email. The link is valid for 60 minutes. If no email arrives within 10 minutes, check your spam folder.",
        "de": "Öffnen Sie app.roosterly.nl/login, wählen Sie 'Wachtwoord vergeten' und geben Sie die E-Mail-Adresse Ihres Kontos ein. Der Link ist 60 Minuten gültig. Wenn innerhalb von 10 Minuten keine E-Mail ankommt, prüfen Sie Ihren Spam-Ordner.",
    },
    "F02": {
        "nl": "Een manager opent Team → Medewerker toevoegen, vult de naam, het e-mailadres en de contracturen van de medewerker in en kiest Uitnodigen. De medewerker ontvangt een installatie-e-mail. Kosten gelden voor actieve medewerkers.",
        "en": "A manager opens Team → Medewerker toevoegen, enters the employee's name, email, and contract hours, then selects Uitnodigen. The employee receives an installation email. Charges apply to active employees.",
        "de": "Eine Führungskraft öffnet Team → Medewerker toevoegen, trägt Name, E-Mail-Adresse und Vertragsstunden der Person ein und wählt Uitnodigen. Die Person erhält eine Installations-E-Mail. Gebühren fallen für aktive Mitarbeitende an.",
    },
    "F03": {
        "nl": "Een medewerker biedt de ruil aan vanuit de dienst in de app. Een collega met dezelfde rol kan deze accepteren. Goedkeuring door een manager staat standaard aan en wordt beheerd onder Rooster → Verzoeken of Instellingen → Rooster.",
        "en": "An employee offers a swap from the shift in the app. A colleague with the same role can accept it. Manager approval is on by default and is managed under Rooster → Verzoeken or Instellingen → Rooster.",
        "de": "Mitarbeitende bieten einen Tausch über die Schicht in der App an. Eine Person mit derselben Rolle kann ihn annehmen. Die Genehmigung durch eine Führungskraft ist standardmäßig aktiviert und wird unter Rooster → Verzoeken oder Instellingen → Rooster verwaltet.",
    },
    "F04": {
        "nl": "Goedgekeurde uren kunnen worden geëxporteerd naar Nmbrs, Loket.nl, AFAS of CSV. Stel exports in onder Instellingen → Koppelingen → Salaris en kies een week-, vierweken- of maandperiode. De drie genoemde integraties zijn inbegrepen bij Plus.",
        "en": "Approved hours can be exported to Nmbrs, Loket.nl, AFAS, or CSV. Configure exports under Instellingen → Koppelingen → Salaris and choose a weekly, four-week, or monthly pay period. The three named integrations are included in Plus.",
        "de": "Genehmigte Stunden können nach Nmbrs, Loket.nl, AFAS oder als CSV exportiert werden. Richten Sie Exporte unter Instellingen → Koppelingen → Salaris ein und wählen Sie einen wöchentlichen, vierwöchentlichen oder monatlichen Abrechnungszeitraum. Die drei genannten Integrationen sind in Plus enthalten.",
    },
    "F07": {
        "nl": "Meerdere vestigingen vereisen Plus. Voeg een vestiging toe via Instellingen → Vestigingen → Nieuwe vestiging. Medewerkers kunnen aan meerdere vestigingen zijn gekoppeld.",
        "en": "Multiple locations require Plus. Add a location under Instellingen → Vestigingen → Nieuwe vestiging. Employees can belong to multiple locations.",
        "de": "Mehrere Standorte erfordern Plus. Fügen Sie einen Standort unter Instellingen → Vestigingen → Nieuwe vestiging hinzu. Mitarbeitende können mehreren Standorten zugeordnet sein.",
    },
    "F08": {
        "nl": "De web- en mobiele apps ondersteunen Nederlands, Engels en Duits. Iedere gebruiker kiest een taal via Profiel → Taal.",
        "en": "The web and mobile apps support Dutch, English, and German. Each user selects a language under Profiel → Taal.",
        "de": "Die Web- und Mobil-Apps unterstützen Niederländisch, Englisch und Deutsch. Jede Person wählt eine Sprache unter Profiel → Taal aus.",
    },
    "F09": {
        "nl": "Gegevens worden opgeslagen in Frankfurt, Duitsland (EU) en verwerkt onder een verwerkersovereenkomst. U vindt die onder Instellingen → Juridisch.",
        "en": "Data is stored in Frankfurt, Germany (EU), and processed under a data-processing agreement. It is available under Instellingen → Juridisch.",
        "de": "Daten werden in Frankfurt, Deutschland (EU), gespeichert und gemäß einem Auftragsverarbeitungsvertrag verarbeitet. Sie finden diesen unter Instellingen → Juridisch.",
    },
    "F11": {
        "nl": "Actuele storingen en gepland onderhoud staan op status.roosterly.nl.",
        "en": "Current outages and planned maintenance are listed at status.roosterly.nl.",
        "de": "Aktuelle Ausfälle und geplante Wartungsarbeiten finden Sie auf status.roosterly.nl.",
    },
}


def detect_ticket_language(text: str) -> Literal["nl", "en", "de"] | None:
    words = set(_WORD.findall(text.casefold()))
    scores = {
        language: len(words & markers)
        for language, markers in _LANGUAGE_MARKERS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ranked[0][1] < 2 or ranked[0][1] == ranked[1][1]:
        return None
    if ranked[0][0] in {"nl", "en", "de"}:
        return ranked[0][0]
    return None


def redact_payment_details(value: str) -> str:
    value = _IBAN.sub("[REDACTED IBAN]", value)
    return _PAYMENT_CARD.sub("[REDACTED CARD]", value)


def ticket_prompt_text(ticket: HelpdeskTicket) -> str:
    return f"<ticket>\n{html.escape(redact_payment_details(ticket.text))}\n</ticket>"


class HelpdeskTicket(BaseModel):
    id: str
    subject: str = ""
    body: str = ""
    customer_plan: str | None = None

    @property
    def text(self) -> str:
        return f"Subject: {self.subject}\n\n{self.body}".strip()


class HelpdeskTriage(BaseModel):
    language: Literal["nl", "en", "de"]
    category: Literal["bug", "billing", "feature_request", "question", "other"]
    priority: Literal["P1", "P2", "P3", "P4"]
    priority_reason: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    needs_human: bool
    human_reason: str | None = None
    is_simple_question: bool
    answerable_from_faq: bool
    faq_reference: str | None = None
    handoff_note: str = ""


class Action(str, Enum):
    reply = "reply"
    handoff = "handoff"
    close = "close"


@dataclass
class HelpdeskDecision:
    action: Action
    payload: dict
    reason: str


class HelpdeskApiError(Exception):
    def __init__(self, status: int, code: str | None = None):
        self.status = status
        self.code = code
        super().__init__(f"Helpdesk API returned HTTP {status}" + (f" ({code})" if code else ""))


class AlreadyHandledError(HelpdeskApiError):
    def __init__(self):
        super().__init__(409, "already_handled")


def _base_payload(triage: HelpdeskTriage | None) -> dict:
    if triage is None:
        return {
            "language": "nl",
            "category": "other",
            "priority": "P4",
            "reason": "Automated analysis failed; a support agent must review this ticket.",
            "confidence": 0.0,
        }
    return {
        "language": triage.language,
        "category": triage.category,
        "priority": triage.priority,
        "reason": redact_payment_details(triage.priority_reason),
        "confidence": triage.confidence,
    }


def decide_helpdesk(
    ticket: HelpdeskTicket,
    triage: HelpdeskTriage | None,
) -> HelpdeskDecision:
    text = ticket.text
    if (
        triage is not None
        and triage.category == "question"
        and _BILLING_TERMS.search(text)
    ):
        triage = triage.model_copy(update={"category": "billing"})
    base = _base_payload(triage)

    if not ticket.subject.strip() and not ticket.body.strip():
        reason = "Empty ticket requires human review."
        note = "The ticket is empty. Please review it and decide whether any action is needed."
        return HelpdeskDecision(
            Action.handoff,
            {**base, "reason": reason, "handoff_note": note},
            reason,
        )
    if _INJECTION.search(text) or _URGENT.search(text) or _RISKY.search(text):
        reason = (
            "Ticket contains instructions directed at the agent."
            if _INJECTION.search(text)
            else (
                "Ticket indicates an urgent incident."
                if _URGENT.search(text)
                else "Ticket involves a restricted or sensitive support matter."
            )
        )
        note = redact_payment_details(
            triage.handoff_note.strip()
            if triage and triage.handoff_note.strip()
            else "Please review this sensitive request and determine the appropriate next step."
        )
        payload_reason = _decision_reason(triage, Action.handoff, reason) if triage else reason
        return HelpdeskDecision(
            Action.handoff,
            {**base, "reason": payload_reason, "handoff_note": note},
            reason,
        )
    if triage is None:
        reason = "Automated analysis failed; a support agent must review this ticket."
        note = "Automated analysis failed. Please review the ticket and decide how to respond."
        return HelpdeskDecision(Action.handoff, {**base, "handoff_note": note}, reason)
    if triage.category == "billing" or _BILLING_TERMS.search(text):
        reason = "Billing requests require human review."
        note = redact_payment_details(
            triage.handoff_note.strip()
            or "Please review this billing request and determine the appropriate next step."
        )
        return HelpdeskDecision(
            Action.handoff,
            {**base, "reason": _decision_reason(triage, Action.handoff, reason), "handoff_note": note},
            reason,
        )
    if triage.needs_human:
        reason = redact_payment_details(
            triage.human_reason or "The model flagged this ticket for human review."
        )
    elif triage.confidence < CONFIDENCE_THRESHOLD:
        reason = f"Low confidence ({triage.confidence:.2f}); a support agent must review."
    elif triage.category == "other":
        reason = f"Category {triage.category} requires human review."
    elif triage.priority == "P1":
        reason = "P1 priority requires immediate human attention."
    elif triage.category == "other":
        reason = "Category other requires human review."
    else:
        reason = ""

    if reason:
        note = redact_payment_details(
            triage.handoff_note.strip()
            or "Please review the customer's request and determine the appropriate next step."
        )
        return HelpdeskDecision(
            Action.handoff,
            {**base, "reason": _decision_reason(triage, Action.handoff, reason), "handoff_note": note},
            reason,
        )

    faq_reference = triage.faq_reference or ""
    topic_pattern = _FAQ_TOPIC_PATTERNS.get(faq_reference)
    language_in_ticket = detect_ticket_language(
        f"{ticket.subject}\n{ticket.body}"
    )
    reply = _FAQ_REPLIES.get(faq_reference, {}).get(triage.language)
    can_reply = (
        triage.category == "question"
        and triage.is_simple_question
        and triage.answerable_from_faq
        and bool(_FAQ_REFERENCE.fullmatch(faq_reference))
        and topic_pattern is not None
        and bool(topic_pattern.search(text))
        and language_in_ticket == triage.language
        and bool(reply)
        and len(reply.split()) <= 120
    )
    if can_reply:
        reason = _decision_reason(triage, Action.reply, "")
        return HelpdeskDecision(
            Action.reply,
            {**base, "reason": reason, "draft_reply": reply},
            "Confident simple question answered with a localized help-centre response.",
        )

    if language_in_ticket != triage.language:
        reason = "The customer's language could not be verified with sufficient confidence."
    elif topic_pattern is None or not topic_pattern.search(text):
        reason = "The FAQ reference does not clearly match the ticket topic."
    else:
        reason = "The ticket is not a confident, FAQ-grounded simple question."
    note = redact_payment_details(
        triage.handoff_note.strip()
        or "Please review the request; an FAQ-grounded reply could not be prepared safely."
    )
    return HelpdeskDecision(
        Action.handoff,
        {**base, "reason": _decision_reason(triage, Action.handoff, reason), "handoff_note": note},
        reason,
    )


def _decision_reason(triage: HelpdeskTriage, action: Action, route_reason: str) -> str:
    priority_reason = redact_payment_details(triage.priority_reason.strip())
    if action == Action.reply:
        detail = (
            f"FAQ {triage.faq_reference} supports this simple question, so a reply is appropriate."
        )
    else:
        detail = f"A human must handle this {triage.category} ticket: {route_reason}"
    return redact_payment_details(f"{priority_reason} {detail}")[:400]


class HelpdeskClient:
    def __init__(
        self,
        api_key: str,
        candidate_email: str,
        base_url: str = DEFAULT_HELPDESK_URL,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = RETRY_LIMIT,
    ):
        if not api_key or not candidate_email:
            raise ValueError("HELPDESK_API_KEY and CANDIDATE_EMAIL are required.")
        self.api_key = api_key
        self.candidate_email = candidate_email
        self.base_url = base_url.rstrip("/")
        self.opener = opener
        self.sleep = sleep
        self.max_retries = max_retries
        self._last_request_at: float | None = None
        self._rate_limit_lock = Lock()

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                delay = MIN_REQUEST_INTERVAL - (now - self._last_request_at)
                if delay > 0:
                    self.sleep(delay)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        fallback = min(0.5 * 2**attempt, 4)
        if not retry_after:
            return fallback
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError, OverflowError):
                return fallback
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Candidate-Email": self.candidate_email,
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(url, data=body, headers=headers, method=method)
            try:
                with self.opener(request, timeout=30) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8")) if raw else {}
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Helpdesk API returned invalid JSON.") from exc
            except HTTPError as exc:
                if exc.code == 409:
                    raise AlreadyHandledError() from exc
                retryable = exc.code in {429, 503}
                if not retryable or attempt == self.max_retries:
                    code = None
                    try:
                        code = json.loads(exc.read().decode("utf-8")).get("error")
                    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                        pass
                    raise HelpdeskApiError(exc.code, code) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleep(self._retry_delay(retry_after, attempt))
            except (TimeoutError, URLError) as exc:
                if attempt == self.max_retries or method != "GET":
                    raise ConnectionError(f"Helpdesk {method} request failed.") from exc
                self.sleep(min(0.5 * 2**attempt, 4))
        raise RuntimeError("Helpdesk request retry loop exited unexpectedly.")

    def list_tickets(self,limit: int | None = None,status: Literal["open", "all"] = "open",) -> list[HelpdeskTicket]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be a positive integer.")
        if status not in {"open", "all"}:
            raise ValueError("status must be 'open' or 'all'.")
        tickets: list[HelpdeskTicket] = []
        cursor: str | None = None
        while True:
            params = {"limit": 10, "status": status}
            if cursor:
                params["cursor"] = cursor
            response = self._request("GET", f"/tickets?{urlencode(params)}")
            if not isinstance(response, dict):
                raise ValueError("Helpdesk ticket response must be a JSON object.")
            page = response.get("tickets")
            if not isinstance(page, list):
                raise ValueError("Helpdesk ticket response is missing a tickets list.")
            tickets.extend(HelpdeskTicket.model_validate(item) for item in page)
            if limit is not None and len(tickets) >= limit:
                return tickets[:limit]
            next_cursor = response.get("next_cursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise ValueError("Helpdesk next_cursor must be a string or null.")
            if next_cursor == cursor and next_cursor is not None:
                raise ValueError("Helpdesk returned the same cursor for consecutive pages.")
            cursor = next_cursor
            if cursor is None:
                return tickets

    def get_status(self) -> dict[str, Any]:
        response = self._request("GET", "/status")
        if not isinstance(response, dict):
            raise ValueError("Helpdesk status response must be a JSON object.")
        return response

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        if not ticket_id.strip():
            raise ValueError("ticket_id must not be empty.")
        response = self._request("GET", f"/tickets/{quote(ticket_id, safe='')}")
        if not isinstance(response, dict):
            raise ValueError("Helpdesk ticket detail response must be a JSON object.")
        return response

    def get_examples(self) -> list[dict]:
        response = self._request("GET", "/examples")
        if isinstance(response, list):
            examples = response
        elif isinstance(response, dict):
            examples = response.get("examples")
        else:
            examples = None
        if not isinstance(examples, list):
            raise ValueError("Helpdesk examples response is missing an examples list.")
        return examples

    def submit(self, ticket_id: str, decision: HelpdeskDecision) -> None:
        path = f"/tickets/{quote(ticket_id, safe='')}/{decision.action.value}"
        self._request("POST", path, decision.payload)

    def reset_practice(self) -> dict:
        response = self._request("POST", "/practice/reset", {})
        if not isinstance(response, dict):
            raise ValueError("Helpdesk reset response must be a JSON object.")
        return response


class HelpdeskAgent:
    def __init__(self,client: HelpdeskClient,logger: JsonlLogger,model: str = DEFAULT_MODEL,):
        self.client = client
        self.logger = logger
        self.model = model
        self.system_prompt = (
            PROMPT_PATH.read_text(encoding="utf-8")
            + "\n\nHelp-centre source of truth:\n"
            + FAQ_PATH.read_text(encoding="utf-8")
        )

    def process_ticket(self, ticket: HelpdeskTicket, submit: bool = False) -> dict:
        started = time.monotonic()
        usage = Usage()
        triage: HelpdeskTriage | None = None
        error: str | None = None
        try:
            triage, call_usage = call_structured(
                self.system_prompt,
                ticket_prompt_text(ticket),
                HelpdeskTriage,
                self.model,
            )
            usage += call_usage
        except Exception as exc:
            error = type(exc).__name__

        decision = decide_helpdesk(ticket, triage)
        submitted_action: str | None = None
        submission_status = "dry_run"
        if submit:
            try:
                self.client.submit(ticket.id, decision)
                submitted_action = decision.action.value
                submission_status = "submitted"
            except AlreadyHandledError:
                submission_status = "already_handled"
            except Exception as exc:
                failure = (
                    f"HTTP {exc.status} ({exc.code})"
                    if isinstance(exc, HelpdeskApiError)
                    else type(exc).__name__
                )
                submission_status = f"failed: {failure}"
                error = error or failure
        model_cost = known_cost_usd(self.model, usage)
        result = {
            "ticket_id": ticket.id,
            "language": triage.language if triage else None,
            "category": decision.payload["category"] if triage else None,
            "priority": triage.priority if triage else None,
            "priority_reason": redact_payment_details(triage.priority_reason) if triage else None,
            "reason": decision.payload["reason"],
            "confidence": triage.confidence if triage else 0.0,
            "action": decision.action.value,
            "triage_status": "succeeded" if triage else "failed",
            "route_reason": decision.reason,
            "faq_reference": triage.faq_reference if triage else None,
            "handoff_note": (
                redact_payment_details(decision.payload.get("handoff_note", ""))
                if decision.action == Action.handoff
                else None
            ),
            "draft_reply": (
                redact_payment_details(decision.payload.get("draft_reply", ""))
                if decision.action == Action.reply
                else None
            ),
            "english_summary": (
                _FAQ_REPLIES.get(triage.faq_reference or "", {}).get("en")
                if triage and decision.action == Action.reply
                else None
            ),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(model_cost, 6) if model_cost is not None else None,
            "latency_s": round(time.monotonic() - started, 2),
            "prompt_version": PROMPT_VERSION,
            "submitted_action": submitted_action,
            "submission_status": submission_status,
            "error": error,
        }
        self.logger.log(result)
        return result

    def run(
        self,
        limit: int | None = None,
        submit: bool = False,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict]:
        tickets = self.client.list_tickets(limit=limit)
        results = []
        for ticket in tickets:
            result = self.process_ticket(ticket, submit=submit)
            results.append(result)
            if on_result is not None:
                on_result(result)
        return results


def evaluate_examples(
    agent: HelpdeskAgent,
    examples: list[dict],
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    totals = {"category": 0, "priority": 0, "action": 0, "language": 0}
    failures: list[dict] = []
    usage_total = Usage()
    for index, example in enumerate(examples, start=1):
        if on_progress is not None:
            on_progress(index, len(examples), example["id"])
        ticket = HelpdeskTicket(
            id=example["id"],
            subject=example.get("subject", ""),
            body=example.get("body", ""),
        )
        triage: HelpdeskTriage | None = None
        triage, usage = call_structured(
            agent.system_prompt,
            ticket_prompt_text(ticket),
            HelpdeskTriage,
            agent.model,
        )
        usage_total += usage
        decision = decide_helpdesk(ticket, triage)
        label = example["label"]
        predicted = {
            "category": decision.payload["category"],
            "priority": triage.priority,
            "action": decision.action.value,
            "language": triage.language,
        }
        expected = {key: label[key] for key in totals}
        mismatches = {
            key: {"expected": expected[key], "predicted": predicted[key]}
            for key in totals
            if expected[key] != predicted[key]
        }
        for metric in totals:
            totals[metric] += int(expected[metric] == predicted[metric])
        if mismatches:
            failures.append({"id": example["id"], "mismatches": mismatches})
    count = len(examples)
    total_cost = known_cost_usd(agent.model, usage_total)
    return {
        "examples": count,
        "correct": totals,
        "failures": failures,
        "accuracy": {
            metric: round(correct / count, 3) if count else 0.0
            for metric, correct in totals.items()
        },
        "input_tokens": usage_total.input_tokens,
        "output_tokens": usage_total.output_tokens,
        "total_cost_usd": round(total_cost, 6) if total_cost is not None else None,
        "cost_per_100_examples_usd": (
            round(total_cost / count * 100, 4)
            if count and total_cost is not None
            else None
        ),
    }
