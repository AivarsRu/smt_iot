"""
Simulator control service.

Backs the four ``/api/simulator/{status,start,stop,run-once}/`` endpoints
and the dashboard simulator panel. Long-running execution is intentionally
*not* started here — Start/Stop only flip the scenario's ``is_active``
flag so the existing standalone ``run_simulator`` cron / management
command keeps full control over the actual generation cadence. Run-once
performs exactly one bounded cycle synchronously, so a local operator
can immediately see fresh telemetry on the dashboard.

All public functions return plain dictionaries with the same stable shape
used by the API serialisation layer (see ``_build_response`` below).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.dashboard import live_updates
from apps.simulator.models import (
    SimulatorRun,
    SimulatorScenario,
)

logger = logging.getLogger(__name__)


DEFAULT_SCENARIO_CODE = "default_demo"


@dataclass
class SimulatorActionResult:
    """Internal dataclass that ``_build_response`` flattens into JSON."""

    ok: bool = True
    status: str = "ok"
    message: str = ""
    scenario: Optional[SimulatorScenario] = None
    last_run_at: Optional[object] = None
    is_active: Optional[bool] = None
    generated_messages: int = 0
    errors: list = field(default_factory=list)
    http_status: int = 200


# ── Public entry points ──────────────────────────────────────────────────────


def get_simulator_status(scenario_code: Optional[str] = None) -> dict:
    """
    Return the current simulator status as a JSON-friendly dict.

    Selection rule for the scenario: ``scenario_code`` (if supplied) →
    ``default_demo`` → first scenario by code. If no scenario exists at
    all, returns ``ok=False`` and HTTP 404.
    """
    scenario = _resolve_scenario(scenario_code)
    if scenario is None:
        return _build_response(_no_scenario_result(action="status"))

    latest_run = _latest_run(scenario)
    return _build_response(SimulatorActionResult(
        ok=True,
        status="ok",
        message=_status_message_lv(scenario, latest_run),
        scenario=scenario,
        last_run_at=scenario.last_run_at,
        is_active=scenario.is_active,
        generated_messages=(
            latest_run.messages_published if latest_run else 0
        ),
    ))


def start_simulator(scenario_code: Optional[str] = None) -> dict:
    """
    Mark the resolved scenario as active.

    Activates ``SimulatorScenario.is_active = True`` so the standalone
    ``run_simulator`` command / cron job will pick the scenario up on its
    next cycle. Idempotent: starting an already-active scenario is a no-op
    that still returns ``ok=True``.
    """
    scenario = _resolve_scenario(scenario_code)
    if scenario is None:
        return _build_response(_no_scenario_result(action="start"))

    was_active = scenario.is_active
    if not was_active:
        with transaction.atomic():
            scenario.is_active = True
            scenario.save(update_fields=["is_active", "updated_at"])

    message = (
        "Simulators jau ir aktīvs."
        if was_active
        else f"Simulators palaists scenārijam '{scenario.code}'."
    )

    live_updates.publish_simulator_status_changed(
        scenario=scenario,
        status="started",
        is_active=True,
        last_run_at=scenario.last_run_at,
        message=message,
    )

    latest_run = _latest_run(scenario)
    return _build_response(SimulatorActionResult(
        ok=True,
        status="started",
        message=message,
        scenario=scenario,
        last_run_at=scenario.last_run_at,
        is_active=True,
        generated_messages=(
            latest_run.messages_published if latest_run else 0
        ),
    ))


def stop_simulator(scenario_code: Optional[str] = None) -> dict:
    """
    Mark the resolved scenario as inactive.

    Sets ``is_active = False`` so the standalone runner skips the
    scenario on its next cycle. Idempotent.
    """
    scenario = _resolve_scenario(scenario_code)
    if scenario is None:
        return _build_response(_no_scenario_result(action="stop"))

    was_active = scenario.is_active
    if was_active:
        with transaction.atomic():
            scenario.is_active = False
            scenario.save(update_fields=["is_active", "updated_at"])

    message = (
        f"Simulators apturēts scenārijam '{scenario.code}'."
        if was_active
        else "Simulators jau bija apturēts."
    )

    live_updates.publish_simulator_status_changed(
        scenario=scenario,
        status="stopped",
        is_active=False,
        last_run_at=scenario.last_run_at,
        message=message,
    )

    latest_run = _latest_run(scenario)
    return _build_response(SimulatorActionResult(
        ok=True,
        status="stopped",
        message=message,
        scenario=scenario,
        last_run_at=scenario.last_run_at,
        is_active=False,
        generated_messages=(
            latest_run.messages_published if latest_run else 0
        ),
    ))


def run_simulator_once(
    scenario_code: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Execute exactly one synchronous simulator cycle.

    Iterates over every enabled ``SimulatorScenarioDevice``, generates a
    payload, and publishes it to the configured MQTT broker (or prints
    it when ``dry_run=True``). Bounded by design: never starts a
    long-running loop, never spawns a thread or subprocess.

    On any per-device failure the partial publish count is preserved on
    the resulting ``SimulatorRun`` for diagnostics.
    """
    scenario = _resolve_scenario(scenario_code)
    if scenario is None:
        return _build_response(_no_scenario_result(action="run_once"))

    run = SimulatorRun.objects.create(scenario=scenario, status="running")
    generated = 0
    published = 0
    errors: list[str] = []

    try:
        generated, published, errors = _execute_single_cycle(
            scenario, dry_run=dry_run,
        )
        now = timezone.now()
        run.status = "completed" if not errors else "failed"
        run.finished_at = now
        run.messages_published = published
        if errors:
            run.error_message = "; ".join(errors)[:1000]
        run.save(update_fields=[
            "status", "finished_at", "messages_published", "error_message",
        ])

        scenario.last_run_at = now
        scenario.save(update_fields=["last_run_at", "updated_at"])

        if errors:
            message = (
                f"Simulators veica vienu ciklu ar kļūdām "
                f"({published}/{generated} publicēti)."
            )
            ok = False
            http_status = 200  # Partial success: row stored, errors reported.
        elif dry_run:
            message = (
                f"Simulators ģenerēja {generated} ziņojumu(s) (dry-run, "
                "MQTT brokerī netika sūtīti)."
            )
            ok = True
            http_status = 200
        else:
            message = f"Simulators publicēja {published} ziņojumu(s)."
            ok = True
            http_status = 200

    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "run_simulator_once failed for scenario=%s", scenario.code,
        )
        run.status = "failed"
        run.finished_at = timezone.now()
        run.messages_published = published
        run.error_message = str(exc)[:1000]
        run.save(update_fields=[
            "status", "finished_at", "messages_published", "error_message",
        ])
        errors = [str(exc)]
        message = "Simulatora cikls neizdevās."
        ok = False
        http_status = 500

    live_updates.publish_simulator_status_changed(
        scenario=scenario,
        status="ran_once",
        is_active=scenario.is_active,
        last_run_at=scenario.last_run_at,
        generated_messages=published,
        message=message,
    )
    # Phase 7, Task 4 — also emit a dedicated run-completed event so
    # the simulator workspace can show a "last run" pill without
    # having to reload its profile list.
    try:
        live_updates.publish_simulator_run_completed(
            scenario=scenario,
            run=run,
            generated_messages=published,
            errors=errors,
        )
    except Exception:  # noqa: BLE001 — never raise from a live update
        logger.exception(
            "publish_simulator_run_completed failed (best-effort, ignored).",
        )

    return _build_response(SimulatorActionResult(
        ok=ok,
        status="ran_once",
        message=message,
        scenario=scenario,
        last_run_at=scenario.last_run_at,
        is_active=scenario.is_active,
        generated_messages=published,
        errors=errors,
        http_status=http_status,
    ))


# ── Internal helpers ─────────────────────────────────────────────────────────


def _execute_single_cycle(scenario, *, dry_run: bool) -> tuple[int, int, list[str]]:
    """
    Generate + publish exactly one payload per enabled scenario device.

    Returns ``(generated, published, errors)``. Errors are accumulated
    per-device so one bad device doesn't kill an otherwise healthy run.

    Phase 7, Task 4 — emits a ``simulator_mqtt_message_sent`` live update
    for every successful publish (and a failed-status one when an error
    is captured) so the simulator workspace page can append a row to
    its MQTT stream table and a point per metric to its charts. The
    publishing is wrapped in best-effort error handling so a websocket
    outage never aborts an MQTT publish.
    """
    from apps.simulator.services.payload_generator import generate_payload
    from apps.simulator.services.mqtt_publisher import publish_message

    devices_qs = (
        scenario.scenario_devices
        .filter(is_enabled=True)
        .select_related("device__site", "device__asset", "device_profile")
    )
    generated = 0
    published = 0
    errors: list[str] = []

    for sd in devices_qs:
        try:
            topic, payload = generate_payload(sd)
            generated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Payload generation failed for scenario_device=%s", sd.pk,
            )
            errors.append(
                f"generate failed for device={getattr(sd.device, 'device_uid', '?')}: {exc}"
            )
            continue

        if dry_run:
            # Surface dry-run cycles on the simulator workspace too, so
            # operators can see what *would* have been sent.
            _publish_simulator_message(
                scenario=scenario, scenario_device=sd, topic=topic,
                payload=payload, publish_status="dry_run", error="",
            )
            continue

        try:
            publish_message(topic, payload)
            published += 1
            _publish_simulator_message(
                scenario=scenario, scenario_device=sd, topic=topic,
                payload=payload, publish_status="ok", error="",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "MQTT publish failed for scenario_device=%s", sd.pk,
            )
            errors.append(
                f"publish failed for device={getattr(sd.device, 'device_uid', '?')}: {exc}"
            )
            _publish_simulator_message(
                scenario=scenario, scenario_device=sd, topic=topic,
                payload=payload, publish_status="failed", error=str(exc),
            )

    return generated, published, errors


def _publish_simulator_message(
    *, scenario, scenario_device, topic, payload, publish_status, error,
) -> None:
    """
    Best-effort wrapper around
    :func:`apps.dashboard.live_updates.publish_simulator_mqtt_message`.
    Never raises — any failure is logged and swallowed so MQTT
    publishing remains the source of truth for run results.
    """
    try:
        device = getattr(scenario_device, "device", None)
        asset = getattr(device, "asset", None) if device else None
        live_updates.publish_simulator_mqtt_message(
            scenario=scenario,
            device=device,
            asset=asset,
            topic=topic,
            payload_dict=payload,
            publish_status=publish_status,
            error=error,
            message_id=(payload or {}).get("message_id", ""),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "publish_simulator_mqtt_message failed (best-effort, ignored).",
        )


def _resolve_scenario(scenario_code: Optional[str]) -> Optional[SimulatorScenario]:
    """
    Pick the simulator scenario to operate on.

    Selection order:
      1. Exact ``scenario_code`` match if supplied.
      2. ``default_demo`` if it exists.
      3. First scenario by ``code`` ordering.
      4. ``None`` if no scenario exists.
    """
    if scenario_code:
        return (
            SimulatorScenario.objects
            .select_related("site")
            .filter(code=scenario_code)
            .first()
        )
    default = (
        SimulatorScenario.objects
        .select_related("site")
        .filter(code=DEFAULT_SCENARIO_CODE)
        .first()
    )
    if default is not None:
        return default
    return (
        SimulatorScenario.objects
        .select_related("site")
        .order_by("code")
        .first()
    )


def _latest_run(scenario) -> Optional[SimulatorRun]:
    return (
        SimulatorRun.objects
        .filter(scenario=scenario)
        .order_by("-started_at")
        .first()
    )


def _status_message_lv(scenario, latest_run) -> str:
    """Latvian one-line summary suitable for the simulator panel."""
    base = "aktīvs" if scenario.is_active else "apturēts"
    if latest_run is None:
        return f"Scenārijs '{scenario.code}' ({base}). Vēl nav neviena palaidiena."
    return (
        f"Scenārijs '{scenario.code}' ({base}). "
        f"Pēdējais palaidiens: {latest_run.status}."
    )


def _no_scenario_result(*, action: str) -> SimulatorActionResult:
    return SimulatorActionResult(
        ok=False,
        status=action,
        message=(
            "Nav atrasts neviens simulatora scenārijs. "
            "Izveidojiet scenāriju Django administrācijas vidē "
            "vai palaidiet 'seed_demo_data' komandu."
        ),
        scenario=None,
        is_active=None,
        last_run_at=None,
        generated_messages=0,
        errors=["no_scenario"],
        http_status=404,
    )


def _build_response(result: SimulatorActionResult) -> dict:
    """
    Flatten a ``SimulatorActionResult`` into the JSON shape advertised
    by the API. Always includes the same top-level keys so the dashboard
    can rely on the structure.
    """
    scenario = result.scenario
    scenario_payload = None
    if scenario is not None:
        scenario_payload = {
            "id": str(scenario.id),
            "code": scenario.code,
            "name": scenario.name,
            "site_code": getattr(scenario.site, "code", None),
            "interval_seconds": scenario.interval_seconds,
        }

    last_run_at = result.last_run_at
    if hasattr(last_run_at, "isoformat"):
        last_run_at = last_run_at.isoformat()

    return {
        "ok": result.ok,
        "status": result.status,
        "message": result.message,
        "scenario": scenario_payload,
        "last_run_at": last_run_at,
        "is_active": result.is_active,
        "generated_messages": result.generated_messages,
        "errors": list(result.errors),
        "_http_status": result.http_status,
    }
