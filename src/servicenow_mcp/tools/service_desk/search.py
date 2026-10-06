"""Bounded structured searches; caller query syntax is never forwarded."""

import re
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

SEARCH_LIMITATIONS = (
    "Searches are literal title substring matches, not full-text or semantic search. "
    "Caller-supplied raw queries and executable expressions are prohibited. "
    "Limit defaults to 10 and must be 1–100; no pagination. Order is determined by "
    "ServiceNow and is not guaranteed. Count is the returned count, not the total; "
    "there is no truncation indicator and a full page may have more matches. "
    "Read-only: no record writes or confirmation. Only retry errors marked retryable=true. "
)
