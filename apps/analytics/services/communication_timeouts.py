"""
Communication timeout detection.

Periodically evaluates whether each eligible Device has communicated within
its expected interval. When a device has not been seen for longer than
``expected_interval_seconds * COMMUNICATION_TIMEOUT_GRACE_MULTIPLIER`` an
open ``events.Event`` (event_type=``communication_timeout``) is created or
updated. When communication resumes, the open event is closed and the
related ``digital_twin.AssetState`` anomaly counters are recalculated.

The service is invoked from the ``check_communication_timeouts`` management
command (cron-friendly) and from a small recovery hook in the MQTT
ingestion service. It never publishes to MQTT and never modifies telemetry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.conf import settings
from django.utils import timezone

from apps.assets.models import Device, Site
from apps.core.models import OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventStatus, EventType, Severity

logger = logging.getLogger(__name__)


ANALYTICS_SOURCE = "analytics"

DEVICE_STATUS_OK = "ok"
DEVICE_STATUS_TIMED_OUT = "timed_out"
DEVICE_STATUS_NEVER_SEEN = "never_seen"
DEVICE_STATUS_SKIPPED = "skipped"


@dataclass
class DeviceCheckRecord:
    """Per-device snapshot of what happened during a single timeout check."""

    device_uid: str
    site_code: str
    asset_code: str
    status: str
    last_seen_at: Optional[object] = None
    expected_interval_seconds: Optional[int] = None
    timeout_seconds: Optional[float] = None
    event_action: Optional[str] = None  # 'created' | 'updated' | 'closed' | None
    skip_reason: str = ""


@dataclass
class CommunicationTimeoutCheckResult:
    """Aggregate result returned by the public check functions."""

    devices_checked: int = 0
    timeouts_created: int = 0
    timeouts_updated: int = 0
    timeouts_closed: int = 0
    devices_ok: int = 0
    devices_skipped: int = 0
    errors: list = field(default_factory=list)
    device_records: list = field(default_factory=list)


# ── Public entry points ───────────────────────────────────────────────────────

def check_device_communication_timeout(
    device,
    *,
    now=None,
    grace_multiplier: Optional[float] = None,
    dry_run: bool = False,
) -> CommunicationTimeoutCheckResult:
    """Run a timeout check for a single Device."""
    result = CommunicationTimeoutCheckResult()
    _check_one(device, result, now=now, grace_multiplier=grace_multiplier, dry_run=dry_run)
    return result


def check_all_device_communication_timeouts(
    *,
    now=None,
    site=None,
    device=None,
    grace_multiplier: Optional[float] = None,
    dry_run: bool = False,
) -> CommunicationTimeoutCheckResult:
    """
    Run timeout checks across all eligible devices, optionally restricted
    to a single Site or a single Device.
    """
    result = CommunicationTimeoutCheckResult()

    qs = Device.objects.select_related("site", "asset").all()
    if site is not None:
        qs = qs.filter(site=site)
    if device is not None:
        qs = qs.filter(pk=device.pk)

    for d in qs:
        _check_one(d, result, now=now, grace_multiplier=grace_multiplier, dry_run=dry_run)

    return result


def close_communication_timeout_for_device(device, *, now=None) -> int:
    """
    Recovery hook for the ingestion service.

    Closes any open ``communication_timeout`` Event for the given device and
    recalculates the related AssetState anomaly counters. Never creates a
    timeout event. Returns the number of events closed.
    """
    if device is None or not device.is_active:
        return 0

    now = now or timezone.now()
    closed = _close_open_timeouts(device, now=now, last_seen_at=device.last_seen_at)
    if closed > 0:
        _recompute_asset_state_after_recovery(device.asset)
    return closed


# ── Per-device evaluation ─────────────────────────────────────────────────────

def _check_one(
    device,
    aggregate: CommunicationTimeoutCheckResult,
    *,
    now=None,
    grace_multiplier: Optional[float] = None,
    dry_run: bool = False,
) -> None:
    """Run the timeout check for a single device; mutates ``aggregate``."""
    aggregate.devices_checked += 1
    now = now or timezone.now()

    record = DeviceCheckRecord(
        device_uid=device.device_uid,
        site_code=getattr(device.site, "code", ""),
        asset_code=getattr(device.asset, "code", "") if device.asset else "",
        status=DEVICE_STATUS_OK,
        expected_interval_seconds=device.expected_interval_seconds,
    )

    try:
        # 1. Eligibility
        skip_reason = _ineligible_reason(device)
        if skip_reason:
            record.status = DEVICE_STATUS_SKIPPED
            record.skip_reason = skip_reason
            aggregate.devices_skipped += 1
            aggregate.device_records.append(record)
            return

        # 2. Resolve last_seen_at (Device first, AssetState as fallback)
        last_seen_at = _resolve_last_seen_at(device)
        record.last_seen_at = last_seen_at

        # 3. Compute timeout threshold
        timeout_seconds = _compute_timeout_seconds(device, grace_multiplier)
        record.timeout_seconds = timeout_seconds

        # 4. Classify
        if last_seen_at is None:
            record.status = DEVICE_STATUS_NEVER_SEEN
            timed_out = True
        else:
            elapsed = (now - last_seen_at).total_seconds()
            timed_out = elapsed > timeout_seconds
            record.status = DEVICE_STATUS_TIMED_OUT if timed_out else DEVICE_STATUS_OK

        # 5. Apply changes
        if timed_out:
            action = _handle_timeout(
                device, record, now=now,
                last_seen_at=last_seen_at,
                timeout_seconds=timeout_seconds,
                dry_run=dry_run,
            )
            record.event_action = action
            if action == "created":
                aggregate.timeouts_created += 1
            elif action == "updated":
                aggregate.timeouts_updated += 1
        else:
            closed = _handle_recovery(
                device, record, now=now,
                last_seen_at=last_seen_at,
                dry_run=dry_run,
            )
            if closed:
                record.event_action = "closed"
                aggregate.timeouts_closed += closed
            else:
                aggregate.devices_ok += 1

        aggregate.device_records.append(record)

    except Exception as exc:  # noqa: BLE001 — never let one device break the loop
        logger.exception(
            "Communication timeout check failed for device_uid=%s",
            getattr(device, "device_uid", "<unknown>"),
        )
        aggregate.errors.append(
            f"device={getattr(device, 'device_uid', '?')}: {exc}"
        )
        record.skip_reason = f"error: {exc}"
        aggregate.device_records.append(record)


# ── Eligibility / threshold helpers ───────────────────────────────────────────

def _ineligible_reason(device) -> str:
    """Return a non-empty string when the device must be skipped."""
    if not device.is_active:
        return "device_inactive"
    if device.site_id is None:
        return "device_has_no_site"
    if device.asset_id is None:
        return "device_has_no_asset"
    return ""


def _resolve_last_seen_at(device):
    """Use Device.last_seen_at, falling back to AssetState.last_seen_at."""
    if device.last_seen_at is not None:
        return device.last_seen_at
    if device.asset_id is None:
        return None
    state = AssetState.objects.filter(asset_id=device.asset_id).first()
    if state is not None and state.last_seen_at is not None:
        return state.last_seen_at
    return None


def _compute_timeout_seconds(device, grace_multiplier: Optional[float]) -> float:
    multiplier = (
        grace_multiplier
        if grace_multiplier is not None
        else getattr(settings, "COMMUNICATION_TIMEOUT_GRACE_MULTIPLIER", 3.0)
    )
    base = device.expected_interval_seconds
    if not base or base <= 0:
        base = getattr(settings, "COMMUNICATION_TIMEOUT_DEFAULT_SECONDS", 300)
    return float(base) * float(multiplier)


# ── Timeout / recovery handlers ───────────────────────────────────────────────

def _handle_timeout(
    device, record, *, now, last_seen_at, timeout_seconds: float, dry_run: bool,
) -> str:
    """Create or update an open timeout event. Returns 'created' or 'updated'."""
    if dry_run:
        existing = _find_open_timeout(device)
        return "updated" if existing is not None else "created"

    existing = _find_open_timeout(device)
    if existing is not None:
        _update_open_timeout(
            existing, device,
            now=now, last_seen_at=last_seen_at, timeout_seconds=timeout_seconds,
        )
        _mark_assetstate_offline(device)
        return "updated"

    _create_open_timeout(
        device,
        now=now, last_seen_at=last_seen_at, timeout_seconds=timeout_seconds,
    )
    _mark_assetstate_offline(device)
    return "created"


def _handle_recovery(device, record, *, now, last_seen_at, dry_run: bool) -> int:
    """Close any open timeout events for the device. Returns the count closed."""
    if dry_run:
        return _count_open_timeouts(device)

    closed = _close_open_timeouts(device, now=now, last_seen_at=last_seen_at)
    if closed > 0:
        _recompute_asset_state_after_recovery(device.asset)
    return closed


# ── Event create / update / close ─────────────────────────────────────────────

def _find_open_timeout(device):
    return (
        Event.objects.filter(
            event_type=EventType.COMMUNICATION_TIMEOUT,
            status=EventStatus.OPEN,
            source=ANALYTICS_SOURCE,
            device=device,
        )
        .order_by("-detected_at")
        .first()
    )


def _count_open_timeouts(device) -> int:
    return Event.objects.filter(
        event_type=EventType.COMMUNICATION_TIMEOUT,
        status=EventStatus.OPEN,
        source=ANALYTICS_SOURCE,
        device=device,
    ).count()


def _create_open_timeout(device, *, now, last_seen_at, timeout_seconds: float):
    description = _describe(
        device, last_seen_at=last_seen_at,
        timeout_seconds=timeout_seconds, checked_at=now, recovered=False,
    )
    payload = _build_payload(
        device, last_seen_at=last_seen_at,
        timeout_seconds=timeout_seconds, checked_at=now,
    )
    event = Event.objects.create(
        event_type=EventType.COMMUNICATION_TIMEOUT,
        severity=Severity.WARNING,
        status=EventStatus.OPEN,
        site=device.site,
        asset=device.asset,
        device=device,
        title=f"Communication timeout: {device.device_uid}",
        description=description,
        source=ANALYTICS_SOURCE,
        payload=payload,
        detected_at=now,
    )
    _best_effort_publish_anomaly(event)


def _best_effort_publish_anomaly(event) -> None:
    """Fan out a new communication-timeout event to the dashboard."""
    try:
        from apps.dashboard import live_updates
        live_updates.publish_anomaly_created(event=event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Anomaly live update skipped: %s", exc)


def _update_open_timeout(event, device, *, now, last_seen_at, timeout_seconds: float):
    """Update description and payload but preserve detected_at."""
    event.description = _describe(
        device, last_seen_at=last_seen_at,
        timeout_seconds=timeout_seconds, checked_at=now, recovered=False,
    )
    event.payload = _build_payload(
        device, last_seen_at=last_seen_at,
        timeout_seconds=timeout_seconds, checked_at=now,
        prior_payload=event.payload,
    )
    event.save(update_fields=["description", "payload"])


def _close_open_timeouts(device, *, now, last_seen_at) -> int:
    """Close every open timeout event for the device. Returns count closed."""
    qs = Event.objects.filter(
        event_type=EventType.COMMUNICATION_TIMEOUT,
        status=EventStatus.OPEN,
        source=ANALYTICS_SOURCE,
        device=device,
    )
    closed = 0
    for event in qs:
        event.status = EventStatus.CLOSED
        event.closed_at = now
        event.description = _describe(
            device, last_seen_at=last_seen_at,
            timeout_seconds=None, checked_at=now, recovered=True,
        )
        prior = dict(event.payload or {})
        prior.update({
            "recovered_at": now.isoformat(),
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
            "checked_at": now.isoformat(),
        })
        event.payload = prior
        event.save(update_fields=["status", "closed_at", "description", "payload"])
        closed += 1
    return closed


# ── AssetState updates ────────────────────────────────────────────────────────

def _mark_assetstate_offline(device) -> None:
    """Conservative: only flips status to OFFLINE; recomputes anomaly counters."""
    if device.asset_id is None:
        return
    state = AssetState.objects.filter(asset_id=device.asset_id).first()
    if state is None:
        return
    open_count = _open_event_count_for_asset(device.asset_id)
    state.status = OperationalStatus.OFFLINE
    state.has_active_anomaly = open_count > 0
    state.active_anomaly_count = open_count
    state.save(update_fields=["status", "has_active_anomaly", "active_anomaly_count"])


def _recompute_asset_state_after_recovery(asset) -> None:
    """
    Recompute open-event counters after closing a timeout. Only flips status
    back to ACTIVE if the AssetState is currently OFFLINE and no other open
    events remain — never overrides an unrelated WARNING/ERROR state.
    """
    if asset is None:
        return
    state = AssetState.objects.filter(asset_id=asset.id).first()
    if state is None:
        return
    open_count = _open_event_count_for_asset(asset.id)
    state.active_anomaly_count = open_count
    state.has_active_anomaly = open_count > 0

    update_fields = ["active_anomaly_count", "has_active_anomaly"]
    if state.status == OperationalStatus.OFFLINE and open_count == 0:
        state.status = OperationalStatus.ACTIVE
        update_fields.append("status")
    state.save(update_fields=update_fields)


def _open_event_count_for_asset(asset_id) -> int:
    return Event.objects.filter(
        asset_id=asset_id, status=EventStatus.OPEN,
    ).count()


# ── Description / payload helpers ─────────────────────────────────────────────

def _describe(device, *, last_seen_at, timeout_seconds, checked_at, recovered: bool) -> str:
    asset_code = getattr(device.asset, "code", "?") if device.asset else "?"
    last_seen_repr = last_seen_at.isoformat() if last_seen_at else "<never>"
    if recovered:
        return (
            f"Communication recovered. device_uid={device.device_uid}, "
            f"asset={asset_code}, last_seen_at={last_seen_repr}, "
            f"checked_at={checked_at.isoformat()}"
        )
    return (
        f"Communication timeout. device_uid={device.device_uid}, "
        f"asset={asset_code}, last_seen_at={last_seen_repr}, "
        f"expected_interval_seconds={device.expected_interval_seconds}, "
        f"timeout_seconds={timeout_seconds}, "
        f"checked_at={checked_at.isoformat()}"
    )


def _build_payload(
    device,
    *,
    last_seen_at,
    timeout_seconds: float,
    checked_at,
    prior_payload=None,
) -> dict:
    payload = {
        "device_uid": device.device_uid,
        "asset_code": (device.asset.code if device.asset else None),
        "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
        "expected_interval_seconds": device.expected_interval_seconds,
        "grace_multiplier": getattr(
            settings, "COMMUNICATION_TIMEOUT_GRACE_MULTIPLIER", 3.0,
        ),
        "timeout_seconds": timeout_seconds,
        "checked_at": checked_at.isoformat(),
    }
    if prior_payload:
        merged = dict(prior_payload)
        merged.update(payload)
        return merged
    return payload
