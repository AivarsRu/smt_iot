"""
Simulator profile service (Phase 7, Task 4).

A "profile" in the dashboard UI maps directly to one
:class:`apps.simulator.models.SimulatorScenario` row plus the
``SimulatorScenarioDevice`` / ``SimulatorMetricProfile`` rows attached
to it. No new model is introduced — the existing simulator schema
already captures every field the workspace UI needs.

This module exposes pure-Python services so the same logic is reused by:

* ``GET /api/simulator/profiles/`` (list serialisation),
* ``GET /api/simulator/profiles/<code>/`` (detail serialisation),
* ``POST /api/simulator/profiles/`` (create-or-update profile),
* ``PUT|PATCH /api/simulator/profiles/<code>/`` (update profile),
* the dashboard workspace JavaScript (via the same JSON shape).

Permission checks happen at the HTTP layer (``apps/api/views.py``); this
module is intentionally HTTP-agnostic so management commands and tests
can call it without any ``request`` object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from django.db import transaction

from apps.iot_config.models import MetricDefinition
from apps.simulator.models import (
    SimulatorMetricProfile,
    SimulatorScenario,
    SimulatorScenarioDevice,
)

logger = logging.getLogger(__name__)


# ── Public read API ─────────────────────────────────────────────────────────


def list_profiles() -> list[dict]:
    """Return every simulator profile as a JSON-friendly list of dicts."""
    qs = (
        SimulatorScenario.objects
        .select_related("site")
        .prefetch_related(
            "scenario_devices__device",
            "scenario_devices__metric_profiles__metric",
            "scenario_devices__metric_profiles__sensor",
        )
        .order_by("code")
    )
    return [serialise_profile(p) for p in qs]


def get_profile(code: str) -> Optional[dict]:
    """Return a single profile by ``code`` or ``None`` if not found."""
    scenario = (
        SimulatorScenario.objects
        .select_related("site")
        .prefetch_related(
            "scenario_devices__device",
            "scenario_devices__metric_profiles__metric",
            "scenario_devices__metric_profiles__sensor",
        )
        .filter(code=code)
        .first()
    )
    if scenario is None:
        return None
    return serialise_profile(scenario)


def serialise_profile(scenario: SimulatorScenario) -> dict:
    """Flatten a ``SimulatorScenario`` and its children into a JSON dict."""
    devices = []
    for sd in scenario.scenario_devices.all():
        metrics = []
        for mp in sd.metric_profiles.all():
            metric = mp.metric
            sensor = mp.sensor
            metrics.append({
                "id": str(mp.id),
                "metric_key": getattr(metric, "key", ""),
                "metric_label": getattr(metric, "display_name", "") or getattr(metric, "key", ""),
                "unit": getattr(metric, "unit", "") or "",
                "sensor_code": getattr(sensor, "code", "") or "",
                "base_value": mp.base_value,
                "min_value": mp.min_value,
                "max_value": mp.max_value,
                "noise_amplitude": mp.noise_amplitude,
                "generation_mode": mp.generation_mode,
                "is_enabled": mp.is_enabled,
                "sort_order": mp.sort_order,
            })
        devices.append({
            "id": str(sd.id),
            "device_uid": getattr(sd.device, "device_uid", ""),
            "device_name": getattr(sd.device, "name", "") or "",
            "is_enabled": sd.is_enabled,
            "sort_order": sd.sort_order,
            "status_override": sd.status_override or "",
            "metrics": metrics,
        })
    return {
        "id": str(scenario.id),
        "code": scenario.code,
        "name": scenario.name,
        "description": scenario.description,
        "site_code": getattr(scenario.site, "code", None),
        "interval_seconds": scenario.interval_seconds,
        "default_status": scenario.default_status,
        "is_active": scenario.is_active,
        "last_run_at": (
            scenario.last_run_at.isoformat()
            if scenario.last_run_at else None
        ),
        "devices": devices,
    }


# ── Validation ──────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Container for profile validation outcomes."""
    ok: bool
    field_errors: dict
    summary: str

    def as_response(self) -> dict:
        """Build the stable JSON denial body."""
        return {
            "ok": False,
            "status": "validation_error",
            "message": self.summary,
            "field_errors": self.field_errors,
        }


def validate_profile_payload(
    data: dict, *, instance: Optional[SimulatorScenario] = None,
    partial: bool = False,
) -> ValidationResult:
    """
    Validate a profile payload according to the Phase 7, Task 4 spec.

    * ``code`` is required (and unique) on create; on partial update it
      may be omitted but, if supplied, must remain unique.
    * ``interval_seconds`` must be a positive integer.
    * ``metrics`` (when present) must be a list; each row must have a
      non-empty ``metric_key`` + ``unit`` (or referenced
      MetricDefinition supplies the unit), valid ``min_value``,
      ``max_value``, ``base_value`` (within range), and a non-negative
      ``noise_amplitude``. At least one metric must be enabled.

    Returns a :class:`ValidationResult` with field-level errors and a
    Latvian summary suitable for the dashboard feedback area.
    """
    errors: dict[str, Any] = {}

    if not partial or "code" in data:
        code = (data.get("code") or "").strip()
        if not code:
            errors["code"] = "Profila kods ir obligāts."
        elif len(code) > 64:
            errors["code"] = "Profila kods drīkst būt līdz 64 simboliem."
        else:
            qs = SimulatorScenario.objects.filter(code=code)
            if instance is not None:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                errors["code"] = f"Profils ar kodu '{code}' jau eksistē."

    if not partial or "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            errors["name"] = "Nosaukums ir obligāts."

    if not partial or "interval_seconds" in data:
        interval = data.get("interval_seconds")
        if interval is None:
            if not partial:
                errors["interval_seconds"] = "Intervāls ir obligāts."
        else:
            try:
                interval_int = int(interval)
            except (TypeError, ValueError):
                interval_int = None
            if interval_int is None or interval_int <= 0:
                errors["interval_seconds"] = (
                    "Intervālam jābūt pozitīvam veselam skaitlim."
                )

    metrics = data.get("metrics")
    if metrics is not None:
        metric_errors, summary_metrics = _validate_metrics_block(metrics)
        if metric_errors:
            errors["metrics"] = metric_errors
        if not summary_metrics["any_enabled"] and metrics:
            errors.setdefault("metrics_summary", []).append(
                "Vismaz vienai metrikai jābūt iespējotai.",
            )
    elif not partial:
        # On full create, having no metrics is valid (the user can add
        # them later); only the workspace UI enforces "at least one
        # enabled metric" before letting Save commit.
        pass

    if errors:
        return ValidationResult(
            ok=False,
            field_errors=errors,
            summary="Profila konfigurācija nav derīga. Lūdzu, pārbaudiet laukus.",
        )
    return ValidationResult(ok=True, field_errors={}, summary="ok")


def _validate_metrics_block(metrics: Any) -> tuple[list, dict]:
    """Per-metric validation. Returns ``(errors, summary)``."""
    if not isinstance(metrics, list):
        return (
            [{"_": "Metrikas jābūt sarakstam."}],
            {"any_enabled": False},
        )
    out: list = []
    any_enabled = False
    seen_keys: set = set()

    for idx, raw in enumerate(metrics):
        row_errors: dict = {}
        if not isinstance(raw, dict):
            out.append({"_": f"Metrika #{idx + 1} nav korekta objekta forma."})
            continue
        key = (raw.get("metric_key") or "").strip()
        unit = (raw.get("unit") or "").strip()

        if not key:
            row_errors["metric_key"] = "Metrikas atslēga ir obligāta."
        elif key in seen_keys:
            row_errors["metric_key"] = (
                f"Metrika '{key}' jau ir definēta šajā profilā."
            )
        seen_keys.add(key)

        if not unit:
            # Check whether the MetricDefinition provides a unit.
            metric_def = MetricDefinition.objects.filter(key=key).first()
            if metric_def is None or not (metric_def.unit or "").strip():
                row_errors["unit"] = "Mērvienība ir obligāta."

        min_v = _to_float_or_none(raw.get("min_value"))
        max_v = _to_float_or_none(raw.get("max_value"))
        base_v = _to_float_or_none(raw.get("base_value"))
        noise = _to_float_or_none(raw.get("noise_amplitude"))

        if base_v is None:
            row_errors["base_value"] = "Bāzes vērtībai jābūt skaitlim."
        if min_v is not None and max_v is not None and min_v >= max_v:
            row_errors["min_value"] = (
                "Minimālajai vērtībai jābūt mazākai par maksimālo."
            )
        if base_v is not None:
            if min_v is not None and base_v < min_v:
                row_errors["base_value"] = (
                    "Bāzes vērtībai jābūt vienādai vai lielākai par minimālo."
                )
            if max_v is not None and base_v > max_v:
                row_errors["base_value"] = (
                    "Bāzes vērtībai jābūt vienādai vai mazākai par maksimālo."
                )
        if noise is not None and noise < 0:
            row_errors["noise_amplitude"] = (
                "Trokšņa amplitūdai jābūt 0 vai pozitīvai."
            )

        if raw.get("is_enabled"):
            any_enabled = True

        if row_errors:
            row_errors["index"] = idx
            row_errors["metric_key"] = row_errors.get("metric_key", key or None)
            out.append(row_errors)

    return out, {"any_enabled": any_enabled}


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Persistence ─────────────────────────────────────────────────────────────


def update_profile(scenario: SimulatorScenario, data: dict, *, partial: bool) -> dict:
    """
    Apply ``data`` to ``scenario`` (and its metric profiles).

    Only top-level scenario fields and per-metric configuration on
    existing :class:`SimulatorMetricProfile` rows are editable here. The
    user CANNOT add new sensors / devices through this endpoint —
    those still go through the staged asset configuration workflow.

    Wrapped in ``transaction.atomic`` so a partial failure leaves no
    half-written rows.
    """
    with transaction.atomic():
        if "code" in data:
            scenario.code = (data["code"] or "").strip()
        if "name" in data:
            scenario.name = (data["name"] or "").strip()
        if "description" in data:
            scenario.description = data["description"] or ""
        if "interval_seconds" in data:
            scenario.interval_seconds = int(data["interval_seconds"])
        if "default_status" in data:
            scenario.default_status = (data["default_status"] or "charging").strip()
        if "is_active" in data:
            scenario.is_active = bool(data["is_active"])

        scenario.save()

        metrics = data.get("metrics")
        if metrics is not None:
            _apply_metric_overrides(scenario, metrics)

    return get_profile(scenario.code) or serialise_profile(scenario)


def _apply_metric_overrides(scenario: SimulatorScenario, metric_rows: list) -> None:
    """
    Update existing ``SimulatorMetricProfile`` rows whose
    ``(scenario_device, metric.key)`` pair matches one of the supplied
    rows. Unknown rows are ignored — adding brand-new metrics requires
    the staged sensor workflow because the simulator profile cannot
    invent a new ``Sensor`` from thin air.
    """
    if not metric_rows:
        return
    by_key: dict = {}
    for row in metric_rows:
        if not isinstance(row, dict):
            continue
        key = (row.get("metric_key") or "").strip()
        if not key:
            continue
        by_key[key] = row

    qs = (
        SimulatorMetricProfile.objects
        .filter(scenario_device__scenario=scenario)
        .select_related("metric")
    )
    for mp in qs:
        key = getattr(mp.metric, "key", None)
        if not key or key not in by_key:
            continue
        row = by_key[key]
        if "base_value" in row and row["base_value"] is not None:
            mp.base_value = float(row["base_value"])
        if "min_value" in row:
            mp.min_value = (
                float(row["min_value"]) if row["min_value"] is not None else None
            )
        if "max_value" in row:
            mp.max_value = (
                float(row["max_value"]) if row["max_value"] is not None else None
            )
        if "noise_amplitude" in row and row["noise_amplitude"] is not None:
            mp.noise_amplitude = float(row["noise_amplitude"])
        if "is_enabled" in row:
            mp.is_enabled = bool(row["is_enabled"])
        if "sort_order" in row and row["sort_order"] is not None:
            mp.sort_order = int(row["sort_order"])
        if "generation_mode" in row and row["generation_mode"]:
            mp.generation_mode = str(row["generation_mode"])
        mp.save()


def create_profile(data: dict) -> tuple[Optional[SimulatorScenario], Optional[ValidationResult]]:
    """
    Create a new ``SimulatorScenario`` from ``data``.

    A ``site`` reference (by ``site_code``) is required because a
    scenario must be anchored to an existing site. Devices and metric
    profiles are not added here; the operator attaches them through the
    staged asset workflow afterwards.
    """
    from apps.assets.models import Site

    validation = validate_profile_payload(data, instance=None, partial=False)
    if not validation.ok:
        return None, validation

    site_code = (data.get("site_code") or "").strip()
    if not site_code:
        return None, ValidationResult(
            ok=False,
            field_errors={"site_code": "Vietas kods ir obligāts."},
            summary="Profila konfigurācija nav derīga.",
        )
    site = Site.objects.filter(code=site_code).first()
    if site is None:
        return None, ValidationResult(
            ok=False,
            field_errors={"site_code": f"Vieta '{site_code}' nav atrasta."},
            summary="Profila konfigurācija nav derīga.",
        )

    with transaction.atomic():
        scenario = SimulatorScenario.objects.create(
            code=(data["code"] or "").strip(),
            name=(data["name"] or "").strip(),
            description=data.get("description") or "",
            site=site,
            interval_seconds=int(data["interval_seconds"]),
            default_status=(data.get("default_status") or "charging").strip(),
            is_active=bool(data.get("is_active", False)),
        )
    return scenario, None
