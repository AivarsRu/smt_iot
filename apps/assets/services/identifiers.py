"""
System-generated technical identifier helpers for the operator UI.

Phase 7, Task 3B made ``Asset.code``, ``Device.device_uid``, and
``Sensor.code`` system-generated instead of operator-entered. This
module centralises the generation logic so every staged-workflow view
(and matching tests) produces the same readable, deterministic format:

    asset-NNNNNN   device-NNNNNN   sensor-NNNNNN   rule-NNNNNN

The pattern is intentionally simple — a fixed prefix plus a zero-padded
sequential suffix. We compute the next suffix by scanning existing rows
with the same prefix; on the rare race-condition collision (two POSTs
in the same millisecond) the caller wraps the actual ORM ``create()``
in a savepoint and retries with :func:`next_code`. See
:func:`create_with_unique_code` for the canonical pattern.

Why not UUID slugs for the operator-facing code?
The codes appear in URLs, MQTT topics, log lines, and ``device_uid``
fields on telemetry messages — keeping them short and readable lets a
human grep production logs without copy-pasting 36-char hex strings.
The primary key remains ``BaseModel.id`` (UUID), which is always
collision-free and is what foreign keys actually reference.
"""

from __future__ import annotations

import re
from typing import Optional

from django.db import IntegrityError, transaction


_SUFFIX_PATTERN_TEMPLATE = r"^{prefix}-(\d+)$"

# Hard cap so a runaway loop cannot silently spin forever.
DEFAULT_MAX_ATTEMPTS = 25
DEFAULT_WIDTH = 6


def _max_suffix(model, field_name: str, prefix: str) -> int:
    """Largest integer suffix currently used for ``<prefix>-NNN`` codes."""
    pattern = re.compile(_SUFFIX_PATTERN_TEMPLATE.format(prefix=re.escape(prefix)))
    lookup = {f"{field_name}__startswith": f"{prefix}-"}
    max_n = 0
    for value in model.objects.filter(**lookup).values_list(field_name, flat=True):
        match = pattern.match(value or "")
        if match:
            try:
                n = int(match.group(1))
            except ValueError:
                continue
            if n > max_n:
                max_n = n
    return max_n


def next_code(
    model,
    field_name: str,
    prefix: str,
    *,
    width: int = DEFAULT_WIDTH,
) -> str:
    """Return the next ``<prefix>-NNNNNN`` candidate for ``model.field_name``."""
    return f"{prefix}-{(_max_suffix(model, field_name, prefix) + 1):0{width}d}"


def create_with_unique_code(
    model,
    field_name: str,
    prefix: str,
    *,
    width: int = DEFAULT_WIDTH,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    **fields,
):
    """
    Generate ``<prefix>-NNN``, attempt ``model.objects.create(...)``,
    retry on the unique-constraint collision.

    Each attempt runs inside its own savepoint so a collision rolls back
    just the failed ``INSERT`` and leaves the outer per-stage transaction
    (started by the calling view) intact.
    """
    last_error: Optional[IntegrityError] = None
    for _ in range(max_attempts):
        candidate = next_code(model, field_name, prefix, width=width)
        try:
            with transaction.atomic():
                fields[field_name] = candidate
                return model.objects.create(**fields)
        except IntegrityError as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"Could not allocate a unique {prefix!r} code for "
        f"{model.__name__}.{field_name} after {max_attempts} attempts: "
        f"{last_error}"
    )


# ── Domain-specific shortcuts ────────────────────────────────────────────────
# Each helper imports the model lazily so this module stays importable in
# Django's app-loading phase (it is also handy in unit tests that mock
# specific models).


def generate_asset_code(asset_type: Optional[str] = None, site=None) -> str:
    from apps.assets.models import Asset
    return next_code(Asset, "code", "asset")


def generate_device_uid(device_type: Optional[str] = None) -> str:
    from apps.assets.models import Device
    return next_code(Device, "device_uid", "device")


def generate_sensor_code(device=None, sensor_type: Optional[str] = None) -> str:
    from apps.assets.models import Sensor
    return next_code(Sensor, "code", "sensor")


def generate_threshold_rule_code() -> str:
    from apps.analytics.models import ThresholdRule
    return next_code(ThresholdRule, "code", "rule")


def create_asset_with_unique_code(**fields):
    from apps.assets.models import Asset
    return create_with_unique_code(Asset, "code", "asset", **fields)


def create_device_with_unique_uid(**fields):
    from apps.assets.models import Device
    return create_with_unique_code(Device, "device_uid", "device", **fields)


def create_sensor_with_unique_code(**fields):
    from apps.assets.models import Sensor
    return create_with_unique_code(Sensor, "code", "sensor", **fields)


def create_threshold_rule_with_unique_code(**fields):
    from apps.analytics.models import ThresholdRule
    return create_with_unique_code(ThresholdRule, "code", "rule", **fields)
