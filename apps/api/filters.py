"""
Helper utilities used by API ViewSets to parse query parameters and apply
list-time filtering. All helpers raise ``rest_framework.exceptions.ValidationError``
on invalid input so DRF translates them to HTTP 400 with a clear message.

Keep this module dependency-light: pure helpers, no DRF mixins.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


_BOOL_TRUE = {"true", "1", "yes", "y", "on", "t"}
_BOOL_FALSE = {"false", "0", "no", "n", "off", "f"}


# ── Primitive parsers ────────────────────────────────────────────────────────

def parse_bool(value, *, param: str = "value") -> bool:
    """Parse a query-string boolean. Raises 400 on bad input."""
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in _BOOL_TRUE:
        return True
    if raw in _BOOL_FALSE:
        return False
    raise ValidationError({
        param: f"expected boolean (true/false), got '{value}'",
    })


def parse_iso_datetime(value, *, param: str):
    """Parse an ISO 8601 datetime. Returns timezone-aware datetime or raises 400."""
    if value is None or value == "":
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError({
            param: f"invalid ISO 8601 datetime: '{value}'",
        })
    if parsed.tzinfo is None:
        from django.utils.timezone import make_aware
        parsed = make_aware(parsed)
    return parsed


def parse_int(value, *, param: str, minimum: Optional[int] = None,
              maximum: Optional[int] = None) -> int:
    """Parse a positive integer with optional bounds. Raises 400 on bad input."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValidationError({param: f"expected integer, got '{value}'"})
    if minimum is not None and result < minimum:
        raise ValidationError({param: f"must be >= {minimum}, got {result}"})
    if maximum is not None and result > maximum:
        raise ValidationError({param: f"must be <= {maximum}, got {result}"})
    return result


def parse_limit(raw, *, default: int, maximum: int, param: str = "limit") -> int:
    """Default + max-aware limit parser used by list endpoints."""
    if raw is None or raw == "":
        return default
    return parse_int(raw, param=param, minimum=1, maximum=maximum)


# ── id-or-code resolution ────────────────────────────────────────────────────

def looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def filter_by_id_or_code(
    queryset,
    raw_value,
    *,
    code_field: str,
    id_field: str = "pk",
    param: str,
):
    """
    Filter ``queryset`` by either UUID PK or by ``code_field``. Returns the
    filtered queryset. Empty input is treated as "no filter applied".
    """
    if raw_value is None or raw_value == "":
        return queryset
    value = str(raw_value).strip()
    if looks_like_uuid(value):
        return queryset.filter(**{id_field: value})
    return queryset.filter(**{code_field: value})


# ── Choice validation ────────────────────────────────────────────────────────

def validate_choice(value, *, choices: list, param: str) -> str:
    """Raise 400 if ``value`` is not in ``choices``. Returns the value if OK."""
    if value not in choices:
        raise ValidationError({
            param: (
                f"invalid value '{value}'. "
                f"Allowed: {sorted(choices)}"
            ),
        })
    return value


# ── Timestamp range filter ───────────────────────────────────────────────────

def apply_datetime_range(queryset, request, *, field: str = "timestamp",
                         from_param: str = "from", to_param: str = "to"):
    """
    Apply ``?from=...`` and ``?to=...`` ISO datetime filters to ``queryset``
    on ``field``. Either side may be omitted.
    """
    raw_from = request.query_params.get(from_param)
    raw_to = request.query_params.get(to_param)
    parsed_from = parse_iso_datetime(raw_from, param=from_param)
    parsed_to = parse_iso_datetime(raw_to, param=to_param)
    if parsed_from is not None:
        queryset = queryset.filter(**{f"{field}__gte": parsed_from})
    if parsed_to is not None:
        queryset = queryset.filter(**{f"{field}__lte": parsed_to})
    return queryset
