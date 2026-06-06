"""
Best-effort dashboard live-update publisher.

Backend services (MQTT ingestion, analytics, simulator control) call the
``publish_*`` helpers below to fan out small ``{"event_type": ..., ...}``
messages to the dashboard frontends through Django Channels.

Design rules
------------

* **Best-effort.** Channel-layer or import errors must NEVER break MQTT
  ingestion, analytics, simulator execution, or API responses. Every
  failure is logged and swallowed.
* **Lightweight payloads.** We do NOT duplicate API responses. Each
  message carries just enough context (event type, asset code/UUID,
  timestamp, ids) for the browser to know which API endpoint to refresh.
* **Group naming.** Two stable groups are used:
    - ``dashboard.overview`` — system-wide (overview page).
    - ``dashboard.asset.<safe_id>`` — one per asset; the publisher sends
      to BOTH the UUID-based and code-based group so detail pages routed
      via either identifier receive the message without doing an extra
      ORM lookup in the consumer.
* **Synchronous callers.** All public helpers are plain ``def`` functions
  that wrap channel-layer access in ``async_to_sync`` so they can be
  called from any backend code (management commands, DRF views,
  ingestion service) without refactoring callers to async.

Group names follow the Channels rule of ASCII alphanumerics, hyphens,
underscores, periods, and equal signs (no spaces); see
``_safe_group_segment``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


OVERVIEW_GROUP = "dashboard.overview"
ASSET_GROUP_PREFIX = "dashboard.asset."
# Phase 7, Task 4 — dedicated channel layer group for the simulator
# workspace page. Simulator-specific events (status changed, MQTT
# message sent, run completed) are duplicated to this group so the
# /dashboard/simulator/ page can rely on a focused event stream
# without seeing every overview event.
SIMULATOR_GROUP = "dashboard.simulator"

# Channels enforces a maximum group-name length of 100 characters and a
# strict character set. UUIDs and human-readable codes both fit safely
# inside 100 chars; we still defend the boundary to avoid a runtime crash
# on an exotic identifier.
_GROUP_NAME_MAX_LEN = 100
_GROUP_SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9_.\-]")


# ── Internal helpers ─────────────────────────────────────────────────────────


def _safe_group_segment(value: Any) -> str:
    """
    Sanitise an arbitrary identifier into a Channels-safe group segment.

    Replaces unsafe characters with ``_`` and truncates to a length that
    fits inside the max group name even after the ``dashboard.asset.``
    prefix is added.
    """
    text = "" if value is None else str(value)
    text = _GROUP_SAFE_CHAR_RE.sub("_", text)
    max_segment = _GROUP_NAME_MAX_LEN - len(ASSET_GROUP_PREFIX)
    return text[:max_segment]


def _asset_group_names(asset) -> list[str]:
    """
    Return the list of Channels group names that should receive an
    asset-scoped event for ``asset``.

    Both the UUID-based and the code-based group are addressed so a
    detail page routed via either identifier picks up the broadcast
    without the consumer doing an ORM lookup.
    """
    if asset is None:
        return []
    groups: list[str] = []
    asset_id = getattr(asset, "id", None) or getattr(asset, "pk", None)
    asset_code = getattr(asset, "code", None)
    for raw in (asset_id, asset_code):
        if not raw:
            continue
        seg = _safe_group_segment(raw)
        if not seg:
            continue
        name = ASSET_GROUP_PREFIX + seg
        if name not in groups:
            groups.append(name)
    return groups


def _build_message(event_type: str, payload: Optional[dict] = None) -> dict:
    """Wrap a payload dict in the canonical ``channel_message`` envelope."""
    body = dict(payload) if payload else {}
    body.setdefault("event_type", event_type)
    body.setdefault("ts", timezone.now().isoformat())
    return {
        # Consumer's handler method name; must be unique per event family.
        "type": "dashboard.event",
        "event_type": event_type,
        "payload": body,
    }


def _send_to_groups(groups: list[str], message: dict) -> None:
    """
    Fan out one envelope to every distinct group, swallowing every error.

    Lazy imports keep this module importable in environments where
    ``channels`` may be absent (e.g. ad-hoc scripts), and lets test
    settings override the channel layer to ``InMemoryChannelLayer``
    without paying any startup cost when no consumers are listening.
    """
    if not groups:
        return
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Live update skipped — Channels not importable: %s", exc,
        )
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.debug("Live update skipped — no channel layer configured.")
        return

    seen: set[str] = set()
    for group in groups:
        if not group or group in seen:
            continue
        seen.add(group)
        try:
            async_to_sync(channel_layer.group_send)(group, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Live update group_send failed for group=%s: %s",
                group, exc,
            )


# ── Public API ───────────────────────────────────────────────────────────────


def publish_event(
    event_type: str,
    *,
    asset=None,
    payload: Optional[dict] = None,
    overview: bool = True,
    simulator: bool = False,
) -> None:
    """
    Generic best-effort publisher.

    Args:
        event_type: short stable identifier — one of the documented
            event types (see ``EVENT_TYPES`` below).
        asset: optional ``apps.assets.Asset`` instance; when given, the
            asset-scoped groups are addressed in addition to the overview
            group.
        payload: optional event-specific dict merged into the envelope.
        overview: when ``False``, the overview group is skipped — used
            for events that should only reach the matching asset detail
            page.
        simulator: when ``True``, the simulator workspace group is
            addressed too — used for ``simulator_*`` events so the
            /dashboard/simulator/ page receives them without the JS
            having to subscribe to the overview firehose.
    """
    try:
        groups: list[str] = []
        if overview:
            groups.append(OVERVIEW_GROUP)
        if simulator:
            groups.append(SIMULATOR_GROUP)
        groups.extend(_asset_group_names(asset))
        message = _build_message(event_type, payload)
        _send_to_groups(groups, message)
    except Exception as exc:  # noqa: BLE001 — never raise from a live update
        logger.exception("publish_event(%s) failed: %s", event_type, exc)


def publish_simulator_status_changed(
    *,
    scenario=None,
    status: Optional[str] = None,
    last_run_at=None,
    is_active: Optional[bool] = None,
    generated_messages: Optional[int] = None,
    message: str = "",
) -> None:
    """Simulator scenario state changed (start/stop/run-once)."""
    payload = {
        "status": status,
        "scenario_code": getattr(scenario, "code", None),
        "scenario_name": getattr(scenario, "name", None),
        "is_active": is_active if is_active is not None else getattr(scenario, "is_active", None),
        "last_run_at": (
            last_run_at.isoformat() if hasattr(last_run_at, "isoformat")
            else last_run_at
        ),
        "generated_messages": generated_messages,
        "message": message,
    }
    publish_event("simulator_status_changed", payload=payload, simulator=True)


# Phase 7, Task 4 — dedicated event types for the simulator workspace.

def publish_simulator_mqtt_message(
    *,
    scenario=None,
    device=None,
    asset=None,
    topic: str = "",
    payload_dict: Optional[dict] = None,
    payload_preview: str = "",
    publish_status: str = "ok",
    error: str = "",
    message_id: str = "",
) -> None:
    """
    A single MQTT telemetry message has just been emitted by
    ``run_simulator_once`` (or the standalone runner). Sent to the
    overview AND the dedicated simulator workspace group so the
    /dashboard/simulator/ page can append a row to its MQTT stream
    table and a point to each metric chart without hitting the API.

    ``payload_dict`` and ``payload_preview`` are intentionally separate:
    the dict carries the metric values (small, structured) so charts can
    update directly; the preview is a truncated, browser-safe string so
    the stream table can show a one-line summary without inflating the
    websocket frame.
    """
    metrics = (payload_dict or {}).get("metrics", {}) or {}
    summary_pairs = sorted(
        (k, v) for k, v in metrics.items() if isinstance(v, (int, float))
    )
    metric_summary = ", ".join(f"{k}={v}" for k, v in summary_pairs[:6])
    preview = payload_preview or _safe_payload_preview(payload_dict)

    body = {
        "scenario_code": getattr(scenario, "code", None),
        "scenario_name": getattr(scenario, "name", None),
        "device_uid": getattr(device, "device_uid", None),
        "asset_code": getattr(asset, "code", None) or getattr(
            getattr(device, "asset", None), "code", None,
        ),
        "asset_id": (
            str(getattr(asset, "id", None))
            if asset else (
                str(getattr(getattr(device, "asset", None), "id", None))
                if device else None
            )
        ),
        "topic": topic,
        "metrics": {
            k: v for k, v in metrics.items()
            if isinstance(v, (int, float, bool, str))
        },
        "metric_summary": metric_summary,
        "payload_preview": preview,
        "publish_status": publish_status,
        "error": error,
        "message_id": message_id or (payload_dict or {}).get("message_id", ""),
    }
    publish_event(
        "simulator_mqtt_message_sent",
        asset=asset,
        payload=body,
        simulator=True,
    )


def publish_simulator_run_completed(
    *,
    scenario=None,
    run=None,
    generated_messages: int = 0,
    errors: Optional[list] = None,
) -> None:
    """One ``run_simulator_once`` cycle has finished (success OR partial)."""
    body = {
        "scenario_code": getattr(scenario, "code", None),
        "scenario_name": getattr(scenario, "name", None),
        "run_id": str(getattr(run, "id", None)) if run is not None else None,
        "status": getattr(run, "status", None),
        "started_at": (
            run.started_at.isoformat() if run and run.started_at else None
        ),
        "finished_at": (
            run.finished_at.isoformat() if run and run.finished_at else None
        ),
        "messages_published": (
            getattr(run, "messages_published", None) or generated_messages
        ),
        "errors": list(errors or []),
    }
    publish_event(
        "simulator_run_completed", payload=body, simulator=True,
    )


def _safe_payload_preview(payload: Optional[dict], *, max_chars: int = 240) -> str:
    """Return a JSON preview of ``payload`` truncated to ``max_chars``."""
    if not payload:
        return ""
    try:
        import json as _json
        text = _json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def publish_telemetry_received(
    *,
    asset=None,
    device=None,
    raw_message=None,
    measurements_count: Optional[int] = None,
) -> None:
    """One MQTT telemetry message has been ingested successfully."""
    payload = {
        "asset_code": getattr(asset, "code", None),
        "asset_id": str(getattr(asset, "id", None)) if asset else None,
        "device_uid": getattr(device, "device_uid", None),
        "raw_message_id": str(getattr(raw_message, "id", None)) if raw_message else None,
        "message_id": getattr(raw_message, "message_id", None),
        "measurements_count": measurements_count,
    }
    publish_event("telemetry_received", asset=asset, payload=payload)


def publish_raw_message_received(*, raw_message, asset=None, device=None) -> None:
    """A RawMessage row has been stored (success or failure)."""
    payload = {
        "raw_message_id": str(getattr(raw_message, "id", None)),
        "message_id": getattr(raw_message, "message_id", ""),
        "topic": getattr(raw_message, "topic", ""),
        "processing_status": getattr(raw_message, "processing_status", ""),
        "device_uid": getattr(device, "device_uid", None) or getattr(raw_message, "device_uid", ""),
        "asset_code": getattr(asset, "code", None),
        "asset_id": str(getattr(asset, "id", None)) if asset else None,
    }
    publish_event("raw_message_received", asset=asset, payload=payload)


def publish_asset_state_updated(*, asset_state) -> None:
    """An ``AssetState`` row has been updated by ingestion."""
    asset = getattr(asset_state, "asset", None)
    payload = {
        "asset_code": getattr(asset, "code", None),
        "asset_id": str(getattr(asset, "id", None)) if asset else None,
        "status": getattr(asset_state, "status", None),
        "last_seen_at": (
            asset_state.last_seen_at.isoformat()
            if getattr(asset_state, "last_seen_at", None) else None
        ),
        "active_anomaly_count": getattr(asset_state, "active_anomaly_count", None),
        "has_active_anomaly": getattr(asset_state, "has_active_anomaly", None),
    }
    publish_event("asset_state_updated", asset=asset, payload=payload)


def publish_anomaly_created(*, event) -> None:
    """A new analytics ``Event`` (threshold or communication timeout) was created."""
    asset = getattr(event, "asset", None)
    payload = {
        "event_id": str(getattr(event, "id", None)),
        "event_type": getattr(event, "event_type", None),
        "severity": getattr(event, "severity", None),
        "status": getattr(event, "status", None),
        "title": getattr(event, "title", None),
        "asset_code": getattr(asset, "code", None),
        "asset_id": str(getattr(asset, "id", None)) if asset else None,
        "device_uid": getattr(getattr(event, "device", None), "device_uid", None),
        "metric_key": getattr(getattr(event, "metric", None), "key", None),
        "detected_at": (
            event.detected_at.isoformat()
            if getattr(event, "detected_at", None) else None
        ),
    }
    publish_event("anomaly_created", asset=asset, payload=payload)


# Stable list of event_type values — handy for the frontend allow-list
# and for tests that want to assert "this event_type is recognised".
EVENT_TYPES: tuple[str, ...] = (
    "simulator_status_changed",
    "simulator_mqtt_message_sent",
    "simulator_run_completed",
    "telemetry_received",
    "asset_state_updated",
    "anomaly_created",
    "raw_message_received",
)
