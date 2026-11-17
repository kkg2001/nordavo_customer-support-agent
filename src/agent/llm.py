from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Type, TypeVar

import groq
from groq import Groq
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = os.getenv("TICKET_AGENT_MODEL", "moonshotai/kimi-k2-instruct-0905")
MAX_RATE_LIMIT_RETRIES = 5


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __iadd__(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        return self


class StructuredCallError(Exception):
    pass


def _create(client: Groq, model: str, system: str, user: str, schema: Type[BaseModel], schema_mode: bool):
    if schema_mode:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": False, "schema": schema.model_json_schema()},
        }
        sys_msg = system
    else:
        response_format = {"type": "json_object"}
        sys_msg = (system + "\n\nRespond with ONLY a JSON object matching this JSON schema:\n"
                   + json.dumps(schema.model_json_schema()))
    return client.chat.completions.create(
        model=model, temperature=0, max_tokens=800, response_format=response_format,
        messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user}],
    )


def _rate_limit_delay(error: Exception, attempt: int) -> float:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(retry_after))
            except (TypeError, ValueError, OverflowError):
                retry_at = None
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    return min(2 ** attempt * 2, 30)


def _with_backoff(fn):
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return fn()
        except groq.RateLimitError as exc:
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            time.sleep(_rate_limit_delay(exc, attempt))


def call_structured(system: str, user: str, schema: Type[T], model: str = DEFAULT_MODEL,
                    max_retries: int = 2, client: Groq | None = None) -> tuple[T, Usage]:
    client = client or Groq()
    usage = Usage()
    schema_mode = True
    last_err: Exception | None = None
    for _ in range(max_retries + 1):
        try:
            resp = _with_backoff(lambda: _create(client, model, system, user, schema, schema_mode))
        except groq.BadRequestError as e:
            last_err = e
            if schema_mode:          # model probably lacks json_schema support -> fall back once
                schema_mode = False
                continue
            raise StructuredCallError(str(e))
        usage += Usage(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        try:
            return schema.model_validate_json(resp.choices[0].message.content), usage
        except ValidationError as e:
            last_err = e
    raise StructuredCallError(str(last_err))