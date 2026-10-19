"""Bounded structured searches; caller query syntax is never forwarded."""

import re
from datetime import datetime, timezone
from typing import Annotated, Literal

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


# Base-system incident state choices. Encoded queries match stored codes, not
# labels, so labels are translated here. Verify against the target instance:
# customized state choices require updating this mapping.
INCIDENT_STATE_CODES = {
    "New": "1",
    "In Progress": "2",
    "On Hold": "3",
    "Resolved": "6",
    "Closed": "7",
    "Canceled": "8",
}
IncidentStateLabel = Annotated[
    Literal["New", "In Progress", "On Hold", "Resolved", "Closed", "Canceled"],
    Field(
        description="Base-system incident state display label; translated to its stored choice code.",
    ),
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

SEARCH_RULES = (
    "Searches are literal title substring matches, not full-text or semantic search. "
    "Caller-supplied raw queries and executable expressions are prohibited. "
)
READ_ONLY_RETRY = (
    "Read-only: no record writes or confirmation. Only retry errors marked retryable=true. "
)
SEARCH_LIMITATIONS = (
    SEARCH_RULES
    + "Limit defaults to 10 and must be 1–100; no pagination. Order is determined by "
    "ServiceNow and is not guaranteed. Count is the returned count, not the total; "
    "there is no truncation indicator and a full page may have more matches. "
    + READ_ONLY_RETRY
)
PAGED_SEARCH_LIMITATIONS = (
    SEARCH_RULES
    + "Limit defaults to 10 and must be 1–100 per page. Results are ordered by "
    "sys_updated_on descending, then sys_id. A full page includes next_offset for the "
    "next page; offsets are 0–100000. Count is the returned count, not the total. "
    + READ_ONLY_RETRY
)
