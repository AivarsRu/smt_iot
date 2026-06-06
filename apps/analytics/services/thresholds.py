"""
Threshold-based anomaly evaluation.

Evaluates one or more ``telemetry.Measurement`` rows against the active
``analytics.ThresholdRule`` records that match the measurement's metric and
scope (site / asset / device). For each violating measurement the service
creates or updates a single open ``events.Event`` (event_type=
``threshold_anomaly``); when the value returns to the allowed range and the
rule has ``close_when_normal=True``, the corresponding open event is closed.

This service is invoked **after** measurements are committed by the MQTT
ingestion service. It is intentionally idempotent and isolated: an exception
inside the service must not corrupt already-stored telemetry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.utils import timezone

from apps.analytics.models import ThresholdRule, ThresholdRuleScope
from apps.events.models import Event, EventStatus, EventType

logger = logging.getLogger(__name__)


ANALYTICS_SOURCE = "analytics"


@dataclass
class ThresholdEvaluationResult:
    """Aggregate result for one or more threshold evaluations."""

    rules_checked: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_closed: int = 0
    events_unchanged: int = 0
    errors: list = field(default_factory=list)


# ── Public entry points ───────────────────────────────────────────────────────

def evaluate_measurement_thresholds(measurement) -> ThresholdEvaluationResult:
    """Evaluate threshold rules for a single Measurement."""
    result = ThresholdEvaluationResult()
    _evaluate_one(measurement, result)
    return result


def evaluate_measurements_thresholds(
    measurements: Iterable,
) -> ThresholdEvaluationResult:
    """Evaluate threshold rules for an iterable of Measurements."""
    aggregate = ThresholdEvaluationResult()
    for measurement in measurements:
        _evaluate_one(measurement, aggregate)
    return aggregate


# ── Per-measurement evaluation ────────────────────────────────────────────────

def _evaluate_one(measurement, aggregate: ThresholdEvaluationResult) -> None:
    """Evaluate a single Measurement; mutates ``aggregate`` in place."""
    try:
        value = _extract_numeric_value(measurement)
        if value is None:
            return

        rules = list(_applicable_rules(measurement))
        aggregate.rules_checked += len(rules)

        for rule in rules:
            try:
                _apply_rule(rule, measurement, value, aggregate)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Threshold rule '%s' failed for measurement_id=%s",
                    rule.code, measurement.id,
                )
                aggregate.errors.append(
                    f"rule={rule.code}, measurement={measurement.id}: {exc}"
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Threshold evaluation failed for measurement_id=%s",
            getattr(measurement, "id", "<unknown>"),
        )
        aggregate.errors.append(f"measurement={getattr(measurement, 'id', '?')}: {exc}")


def _apply_rule(rule, measurement, value, aggregate: ThresholdEvaluationResult) -> None:
    if _is_violation(value, rule):
        existing = _find_open_event(rule, measurement)
        if existing is None:
            _create_threshold_event(rule, measurement, value)
            aggregate.events_created += 1
        else:
            _update_open_event(existing, rule, measurement, value)
            aggregate.events_updated += 1
        return

    # Value is within bounds.
    if rule.close_when_normal:
        closed = _close_open_events(rule, measurement, value)
        aggregate.events_closed += closed
        if closed == 0:
            aggregate.events_unchanged += 1
    else:
        aggregate.events_unchanged += 1


# ── Value extraction ──────────────────────────────────────────────────────────

def _extract_numeric_value(measurement) -> Optional[float]:
    """
    Return a numeric value (float or int) for threshold evaluation, or None
    if the measurement has no numeric value (boolean / text / missing). Booleans
    are intentionally rejected even though Python treats them as ints.
    """
    if measurement.value_float is not None:
        return float(measurement.value_float)
    if measurement.value_int is not None:
        return int(measurement.value_int)
    return None


# ── Rule lookup ───────────────────────────────────────────────────────────────

def _applicable_rules(measurement):
    """
    Active ``ThresholdRule`` rows whose explicit ``scope_level`` matches the
    measurement at exactly that level.

    Phase 7 bugfix: previously a rule with a NULL ``sensor`` (or
    ``device``/``asset``/``site``) was treated as a wildcard, meaning a rule
    intended for one sensor would silently fire for every other sensor under
    the same metric. The new semantics require each rule to declare the
    scope at which it should be evaluated and bind exactly one FK at that
    level.

    Inference rules:

      * ``scope_level == global``  → metric match is sufficient.
      * ``scope_level == site``    → measurement.site must equal rule.site.
      * ``scope_level == asset``   → measurement.asset must equal rule.asset.
      * ``scope_level == device``  → measurement.device must equal rule.device.
      * ``scope_level == sensor``  → measurement.sensor must equal rule.sensor.
    """
    base = ThresholdRule.objects.filter(
        is_enabled=True,
        metric=measurement.metric,
    ).select_related("metric", "sensor", "device", "asset", "site")

    # Build the union of per-scope querysets so that one DB call per scope
    # remains both readable and trivially cacheable by Django. ``measurement``
    # values are passed positionally to avoid kwarg/string typos.
    applicable: list = []

    applicable.extend(
        base.filter(scope_level=ThresholdRuleScope.GLOBAL),
    )
    if measurement.site_id:
        applicable.extend(
            base.filter(
                scope_level=ThresholdRuleScope.SITE,
                site_id=measurement.site_id,
            ),
        )
    if measurement.asset_id:
        applicable.extend(
            base.filter(
                scope_level=ThresholdRuleScope.ASSET,
                asset_id=measurement.asset_id,
            ),
        )
    if measurement.device_id:
        applicable.extend(
            base.filter(
                scope_level=ThresholdRuleScope.DEVICE,
                device_id=measurement.device_id,
            ),
        )
    if measurement.sensor_id:
        applicable.extend(
            base.filter(
                scope_level=ThresholdRuleScope.SENSOR,
                sensor_id=measurement.sensor_id,
            ),
        )
    return applicable


# ── Bound check ───────────────────────────────────────────────────────────────

def _is_violation(value: float, rule) -> bool:
    if rule.lower_bound is not None and value < rule.lower_bound:
        return True
    if rule.upper_bound is not None and value > rule.upper_bound:
        return True
    return False


# ── Open-event lookup, create, update, close ──────────────────────────────────

def _find_open_event(rule, measurement):
    """
    Locate an existing open threshold_anomaly event for the same rule and
    the matching scope, used both for de-duplication and for closing on
    return-to-normal.

    ``payload__rule_code`` already uniquely identifies the rule; we add the
    scope-specific FK filter (sensor for sensor-scoped rules, etc.) so that
    a stale rule_code never accidentally collapses two distinct events from
    different scopes into one.
    """
    qs = Event.objects.filter(
        event_type=EventType.THRESHOLD_ANOMALY,
        status=EventStatus.OPEN,
        source=ANALYTICS_SOURCE,
        metric=measurement.metric,
        payload__rule_code=rule.code,
    )
    qs = _scope_filter(qs, rule, measurement)
    return qs.order_by("-detected_at").first()


def _create_threshold_event(rule, measurement, value: float):
    description = _describe(rule, measurement, value, normal=False)
    payload = _build_payload(rule, measurement, value)
    event = Event.objects.create(
        event_type=EventType.THRESHOLD_ANOMALY,
        severity=rule.severity,
        status=EventStatus.OPEN,
        site=measurement.site,
        asset=measurement.asset,
        device=measurement.device,
        sensor=measurement.sensor,
        metric=measurement.metric,
        measurement=measurement,
        raw_message=measurement.raw_message,
        title=f"Threshold anomaly: {measurement.metric.key}",
        description=description,
        source=ANALYTICS_SOURCE,
        payload=payload,
    )
    _best_effort_publish_anomaly(event)
    return event


def _best_effort_publish_anomaly(event) -> None:
    """Fan out anomaly creation to the dashboard live-update bus."""
    try:
        from apps.dashboard import live_updates
        live_updates.publish_anomaly_created(event=event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Anomaly live update skipped: %s", exc)


def _update_open_event(event, rule, measurement, value: float) -> None:
    """
    Update an existing open event for repeated violation. Preserves
    ``detected_at`` (the original detection time) so the operator sees how
    long the anomaly has been active.
    """
    event.description = _describe(rule, measurement, value, normal=False)
    event.measurement = measurement
    event.raw_message = measurement.raw_message
    event.payload = _build_payload(rule, measurement, value, prior_payload=event.payload)
    event.save(update_fields=["description", "measurement", "raw_message", "payload"])


def _close_open_events(rule, measurement, value: float) -> int:
    """
    Close any open threshold_anomaly events for the same rule and the
    matching scope. A normal value reported by a *different* sensor must not
    close another sensor's open event — that is what :func:`_scope_filter`
    enforces here.

    Returns the number of events closed.
    """
    qs = Event.objects.filter(
        event_type=EventType.THRESHOLD_ANOMALY,
        status=EventStatus.OPEN,
        source=ANALYTICS_SOURCE,
        metric=measurement.metric,
        payload__rule_code=rule.code,
    )
    qs = _scope_filter(qs, rule, measurement)
    now = timezone.now()
    closed_count = 0
    for event in qs:
        event.status = EventStatus.CLOSED
        event.closed_at = now
        event.description = _describe(rule, measurement, value, normal=True)
        prior_payload = dict(event.payload or {})
        prior_payload.update({
            "closed_value": value,
            "closed_measurement_id": str(measurement.id),
            "closed_at": now.isoformat(),
        })
        event.payload = prior_payload
        event.save(update_fields=["status", "closed_at", "description", "payload"])
        closed_count += 1
    return closed_count


# ── Description / payload helpers ─────────────────────────────────────────────

def _describe(rule, measurement, value: float, *, normal: bool) -> str:
    asset_code = getattr(measurement.asset, "code", "?")
    metric_key = getattr(measurement.metric, "key", "?")
    bounds = (
        f"lower_bound={rule.lower_bound}, upper_bound={rule.upper_bound}"
    )
    timestamp = (
        measurement.timestamp.isoformat()
        if measurement.timestamp is not None
        else "<unknown>"
    )
    if normal:
        return (
            f"Value returned to normal range. "
            f"Asset {asset_code}, metric {metric_key}, value {value} "
            f"(rule {rule.code}, {bounds}, at {timestamp})"
        )
    return (
        f"Threshold violated. "
        f"Asset {asset_code}, metric {metric_key}, value {value} "
        f"(rule {rule.code}, {bounds}, at {timestamp})"
    )


def _build_payload(rule, measurement, value: float, *, prior_payload=None) -> dict:
    payload: dict = {
        "rule_code": rule.code,
        "scope_level": rule.scope_level,
        "metric_key": getattr(measurement.metric, "key", None),
        "sensor_code": getattr(measurement.sensor, "code", None),
        "sensor_id": (
            str(measurement.sensor_id) if measurement.sensor_id else None
        ),
        "device_uid": getattr(measurement.device, "device_uid", None),
        "asset_code": getattr(measurement.asset, "code", None),
        "site_code": getattr(measurement.site, "code", None),
        "value": value,
        "lower_bound": rule.lower_bound,
        "upper_bound": rule.upper_bound,
        "measurement_id": str(measurement.id),
    }
    if prior_payload:
        # Preserve any existing diagnostic keys like first_value if present.
        merged = dict(prior_payload)
        merged.update(payload)
        return merged
    return payload


def _scope_filter(qs, rule, measurement):
    """
    Narrow an Event queryset down to the rule's own scope so that
    deduplication and closing only ever touch events that actually belong
    to this (rule, scope) pair.

    The match shape mirrors :func:`_applicable_rules`:

      * global rules    → no extra constraint;
      * site rules      → ``event.site == measurement.site``;
      * asset rules     → ``event.asset == measurement.asset``;
      * device rules    → ``event.device == measurement.device``;
      * sensor rules    → ``event.sensor == measurement.sensor``.
    """
    scope = rule.scope_level
    if scope == ThresholdRuleScope.GLOBAL:
        # Per-measurement isolation: a "normal" reading from a different
        # asset must not close another asset's open event, even for a
        # global rule. We isolate on the strongest scope the measurement
        # itself carries.
        if measurement.sensor_id:
            return qs.filter(sensor_id=measurement.sensor_id)
        if measurement.device_id:
            return qs.filter(device_id=measurement.device_id)
        if measurement.asset_id:
            return qs.filter(asset_id=measurement.asset_id)
        if measurement.site_id:
            return qs.filter(site_id=measurement.site_id)
        return qs
    if scope == ThresholdRuleScope.SITE:
        return qs.filter(site_id=measurement.site_id)
    if scope == ThresholdRuleScope.ASSET:
        return qs.filter(asset_id=measurement.asset_id)
    if scope == ThresholdRuleScope.DEVICE:
        return qs.filter(device_id=measurement.device_id)
    if scope == ThresholdRuleScope.SENSOR:
        return qs.filter(sensor_id=measurement.sensor_id)
    return qs
