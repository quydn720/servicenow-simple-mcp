"""Bounded structured searches; caller query syntax is never forwarded."""

import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BeforeValidator, Field


def validate_search_text(value):
    if isinstance(value, str):
        # Carets separate encoded-query clauses; executable values are never allowed.
        if (
            "^" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or re.search(r"javascript\s*:", value, re.I)
        ):
            raise ValueError("Raw query syntax is prohibited.")
        value = value.strip()
    return value


SearchText = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=160,
        pattern=r"^[^\x00-\x1f\x7f^]+$",
        json_schema_extra={
            "not": {"pattern": r"[jJ][aA][vV][aA][sS][cC][rR][iI][pP][tT]\s*:"}
        },
        description="Literal title substring, 1–160 characters after trimming. No encoded-query delimiters, control characters, or javascript expressions.",
    ),
    BeforeValidator(validate_search_text),
]
IncidentNumber = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^INC[0-9]{1,20}$",
        description="Exact incident number, uppercase INC followed by 1–20 digits.",
    ),
]


def validate_choice_label(value):
    if isinstance(value, str):
        value = value.strip()
        if (
            not value
            or "^" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or re.search(r"javascript\s*:", value, re.I)
        ):
            raise ValueError("A valid literal display label is required.")
    return value


ChoiceLabel = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=100,
        pattern=r"^[^\x00-\x1f\x7f^]+$",
        description="Literal choice display label; query syntax and control characters are prohibited.",
    ),
    BeforeValidator(validate_choice_label),
]


def validate_utc_datetime(value):
    if isinstance(value, str):
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)",
            value,
        ):
            raise ValueError("Use an RFC 3339 UTC date-time.")
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            raise ValueError("Use an RFC 3339 UTC date-time.") from None
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("Use an RFC 3339 UTC date-time ending in Z or +00:00.")
        return parsed.astimezone(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("Use an RFC 3339 UTC date-time ending in Z or +00:00.")
        return value.astimezone(timezone.utc)
    return value


UtcDateTime = Annotated[
    datetime,
    Field(strict=True, description="RFC 3339 UTC date-time; inclusive start or exclusive end."),
    BeforeValidator(validate_utc_datetime),
]

SEARCH_LIMITATIONS = (
    "Searches are literal title substring matches, not full-text or semantic search. "
    "Caller-supplied raw queries and executable expressions are prohibited. "
    "Limit defaults to 10 and must be 1–100. Count is the returned count, not the total. "
    "Read-only: no record writes or confirmation. Only retry errors marked retryable=true. "
)
