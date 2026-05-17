"""
Read-only dashboard summary endpoints. They are intentionally separated
from ``apps/api/views.py`` because each handler is a self-contained
aggregation script that builds plain dictionaries (no model serializers
needed).

All endpoints share these conventions:

* GET-only — POST/PUT/etc. return 405 thanks to ``@api_view(["GET"])``;
* ``generated_at = timezone.now()`` is added to every response so that
  the dashboard can display its freshness;
* counts and "recent" item lists honour the same filter parameters as
  Phase 6 Task 1, parsed via ``apps/api/filters.py`` (invalid input ⇒
  HTTP 400);
* recent lists use ``select_related`` and a hard-capped ``?limit=N``.
"""

from __future__ import annotations

from typing import Optional

from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.api.filters import (
    apply_datetime_range,
    filter_by_id_or_code,
    parse_bool,
    parse_limit,
    validate_choice,
)
from apps.assets.models import Asset, AssetType, Device, Site
from apps.core.models import OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.simulator.models import SimulatorRun, SimulatorScenario
from apps.telemetry.models import (
    Measurement,
    ProcessingStatus,
    RawMessage,
    SourceType,
)


# ── Limits (overview-specific) ───────────────────────────────────────────────

OVERVIEW_DEFAULT_RECENT_LIMIT = 20
OVERVIEW_MAX_RECENT_LIMIT = 200

OVERVIEW_ASSETS_DEFAULT_LIMIT = 100
OVERVIEW_ASSETS_MAX_LIMIT = 1000

ASSET_SUMMARY_DEFAULT_INNER_LIMIT = 20
ASSET_SUMMARY_MAX_INNER_LIMIT = 100


# ── Helpers ──────────────────────────────────────────────────────────────────

def _aggregate_asset_counts(qs):
    """Return the standard 5-bucket asset counts (filtered queryset)."""
    aggs = qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=OperationalStatus.ACTIVE)),
        offline=Count("id", filter=Q(status=OperationalStatus.OFFLINE)),
        warning=Count("id", filter=Q(status=OperationalStatus.WARNING)),
        error=Count("id", filter=Q(status=OperationalStatus.ERROR)),
    )
    return {k: v or 0 for k, v in aggs.items()}


def _scope_event_qs(qs, request):
    """
    Apply only *scope* filters (asset/device/from/to) so dashboard counts
    stay meaningful when callers also pass status/event_type/severity to
    narrow the ``recent`` list.
    """
    raw_asset = request.query_params.get("asset")
    qs = filter_by_id_or_code(
        qs, raw_asset, code_field="asset__code",
        id_field="asset__id", param="asset",
    )
    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(
        qs, raw_device, code_field="device__device_uid",
        id_field="device__id", param="device",
    )
    qs = apply_datetime_range(qs, request, field="detected_at")
    return qs


def _full_event_qs(qs, request):
    """``_scope_event_qs`` + status/event_type/severity choice filters."""
    qs = _scope_event_qs(qs, request)

    raw_status = request.query_params.get("status")
    if raw_status:
        validate_choice(raw_status, choices=list(EventStatus.values), param="status")
        qs = qs.filter(status=raw_status)

    raw_event_type = request.query_params.get("event_type")
    if raw_event_type:
        validate_choice(
            raw_event_type, choices=list(EventType.values), param="event_type",
        )
        qs = qs.filter(event_type=raw_event_type)

    raw_severity = request.query_params.get("severity")
    if raw_severity:
        validate_choice(
            raw_severity, choices=list(Severity.values), param="severity",
        )
        qs = qs.filter(severity=raw_severity)

    return qs


def _scope_measurement_qs(qs, request):
    """asset/device/metric/from/to filters used for both totals and recent."""
    raw_asset = request.query_params.get("asset")
    qs = filter_by_id_or_code(
        qs, raw_asset, code_field="asset__code",
        id_field="asset__id", param="asset",
    )
    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(
        qs, raw_device, code_field="device__device_uid",
        id_field="device__id", param="device",
    )
    raw_metric = request.query_params.get("metric")
    qs = filter_by_id_or_code(
        qs, raw_metric, code_field="metric__key",
        id_field="metric__id", param="metric",
    )
    qs = apply_datetime_range(qs, request, field="timestamp")
    return qs


def _scope_raw_message_qs(qs, request):
    raw_asset = request.query_params.get("asset")
    qs = filter_by_id_or_code(
        qs, raw_asset, code_field="asset__code",
        id_field="asset__id", param="asset",
    )
    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(
        qs, raw_device, code_field="device__device_uid",
        id_field="device__id", param="device",
    )
    qs = apply_datetime_range(qs, request, field="received_at")
    return qs


def _scope_simulator_run_qs(qs, request):
    raw_scenario = request.query_params.get("scenario")
    qs = filter_by_id_or_code(
        qs, raw_scenario, code_field="scenario__code",
        id_field="scenario__id", param="scenario",
    )
    raw_status = request.query_params.get("status")
    if raw_status:
        validate_choice(
            raw_status,
            choices=[c[0] for c in SimulatorRun.RUN_STATUS_CHOICES],
            param="status",
        )
        qs = qs.filter(status=raw_status)
    qs = apply_datetime_range(qs, request, field="started_at")
    return qs


def _serialise_event_summary(event: Event) -> dict:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "severity": event.severity,
        "status": event.status,
        "title": event.title,
        "asset_code": event.asset.code if event.asset_id else None,
        "device_uid": event.device.device_uid if event.device_id else None,
        "detected_at": event.detected_at,
        "closed_at": event.closed_at,
        "source": event.source,
    }


def _serialise_measurement_summary(measurement: Measurement) -> dict:
    return {
        "id": str(measurement.id),
        "asset_code": measurement.asset.code if measurement.asset_id else None,
        "device_uid": measurement.device.device_uid if measurement.device_id else None,
        "metric_key": measurement.metric.key if measurement.metric_id else None,
        "value": measurement.value,
        "unit": measurement.unit or (
            measurement.metric.unit if measurement.metric_id else ""
        ),
        "timestamp": measurement.timestamp,
    }


def _serialise_simulator_run_summary(run: SimulatorRun) -> dict:
    return {
        "id": str(run.id),
        "scenario_code": run.scenario.code if run.scenario_id else None,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "messages_published": run.messages_published,
        "error_message": run.error_message,
    }


# ── /api/overview/ ───────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def overview_view(request):
    """Compact system-wide dashboard summary."""
    asset_counts = _aggregate_asset_counts(Asset.objects.all())
    asset_counts["with_active_anomaly"] = AssetState.objects.filter(
        has_active_anomaly=True,
    ).count()

    device_aggs = Device.objects.aggregate(
        total=Count("id"),
        simulated=Count("id", filter=Q(is_simulated=True)),
        active=Count("id", filter=Q(status=OperationalStatus.ACTIVE)),
        offline=Count("id", filter=Q(status=OperationalStatus.OFFLINE)),
        never_seen=Count("id", filter=Q(last_seen_at__isnull=True)),
    )
    device_counts = {k: v or 0 for k, v in device_aggs.items()}

    raw_aggs = RawMessage.objects.aggregate(
        total=Count("id"), latest=Max("received_at"),
    )
    measurement_aggs = Measurement.objects.aggregate(
        total=Count("id"), latest=Max("timestamp"),
    )
    telemetry = {
        "raw_messages_total": raw_aggs["total"] or 0,
        "measurements_total": measurement_aggs["total"] or 0,
        "latest_measurement_at": measurement_aggs["latest"],
        "latest_raw_message_at": raw_aggs["latest"],
    }

    event_aggs = Event.objects.aggregate(
        open_total=Count("id", filter=Q(status=EventStatus.OPEN)),
        open_threshold_anomaly=Count(
            "id",
            filter=Q(status=EventStatus.OPEN, event_type=EventType.THRESHOLD_ANOMALY),
        ),
        open_communication_timeout=Count(
            "id",
            filter=Q(status=EventStatus.OPEN, event_type=EventType.COMMUNICATION_TIMEOUT),
        ),
        warning_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.WARNING),
        ),
        error_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.ERROR),
        ),
        critical_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.CRITICAL),
        ),
    )
    events = {k: v or 0 for k, v in event_aggs.items()}

    scenario_aggs = SimulatorScenario.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
    )
    latest_run = (
        SimulatorRun.objects.select_related("scenario")
        .order_by("-started_at")
        .first()
    )
    simulator = {
        "scenarios_total": scenario_aggs["total"] or 0,
        "active_scenarios": scenario_aggs["active"] or 0,
        "last_run_status": latest_run.status if latest_run else None,
        "last_run_at": latest_run.started_at if latest_run else None,
        "last_messages_published": (
            latest_run.messages_published if latest_run else None
        ),
    }

    return Response({
        "status": "ok",
        "generated_at": timezone.now(),
        "assets": asset_counts,
        "devices": device_counts,
        "telemetry": telemetry,
        "events": events,
        "simulator": simulator,
    })


# ── /api/overview/assets/ ────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def overview_assets_view(request):
    """Asset list summary tailored for the dashboard cards / status grid."""
    qs = (
        Asset.objects
        .select_related("site", "state")
        .order_by("site__code", "code")
    )

    raw_site = request.query_params.get("site")
    qs = filter_by_id_or_code(
        qs, raw_site, code_field="site__code",
        id_field="site__id", param="site",
    )

    raw_status = request.query_params.get("status")
    if raw_status:
        validate_choice(
            raw_status, choices=list(OperationalStatus.values), param="status",
        )
        qs = qs.filter(status=raw_status)

    raw_asset_type = request.query_params.get("asset_type")
    if raw_asset_type:
        validate_choice(
            raw_asset_type, choices=list(AssetType.values), param="asset_type",
        )
        qs = qs.filter(asset_type=raw_asset_type)

    raw_anomaly = request.query_params.get("has_active_anomaly")
    if raw_anomaly is not None:
        flag = parse_bool(raw_anomaly, param="has_active_anomaly")
        # OneToOne reverse: filter via state__has_active_anomaly. Assets
        # without an AssetState are treated as has_active_anomaly=false.
        if flag:
            qs = qs.filter(state__has_active_anomaly=True)
        else:
            qs = qs.exclude(state__has_active_anomaly=True)

    counts = _aggregate_asset_counts(qs)
    counts["with_active_anomaly"] = qs.filter(
        state__has_active_anomaly=True,
    ).count()

    by_type_rows = (
        qs.values("asset_type")
        .annotate(count=Count("id"))
        .order_by("asset_type")
    )
    by_type = [
        {"asset_type": row["asset_type"], "count": row["count"]}
        for row in by_type_rows
    ]

    limit = parse_limit(
        request.query_params.get("limit"),
        default=OVERVIEW_ASSETS_DEFAULT_LIMIT,
        maximum=OVERVIEW_ASSETS_MAX_LIMIT,
    )

    items = []
    for asset in qs[:limit]:
        try:
            state: Optional[AssetState] = asset.state
        except AssetState.DoesNotExist:
            state = None
        items.append({
            "asset_id": str(asset.id),
            "asset_code": asset.code,
            "asset_name": asset.name,
            "site_code": asset.site.code if asset.site_id else None,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "last_seen_at": state.last_seen_at if state else None,
            "last_measurement_at": state.last_measurement_at if state else None,
            "has_active_anomaly": bool(state.has_active_anomaly) if state else False,
            "active_anomaly_count": state.active_anomaly_count if state else 0,
            "last_temperature_c": state.last_temperature_c if state else None,
            "last_voltage_v": state.last_voltage_v if state else None,
            "last_battery_soc_pct": state.last_battery_soc_pct if state else None,
        })

    return Response({
        "generated_at": timezone.now(),
        "counts": counts,
        "by_type": by_type,
        "items": items,
    })


# ── /api/overview/events/ ────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def overview_events_view(request):
    """Event summary + recent events for the dashboard alerts panel."""
    base_qs = Event.objects.select_related("asset", "device", "metric")
    scope_qs = _scope_event_qs(base_qs, request)

    # Counts ignore status/event_type/severity choice filters so they remain
    # meaningful breakdowns within the scoped subset.
    count_aggs = scope_qs.aggregate(
        open_total=Count("id", filter=Q(status=EventStatus.OPEN)),
        closed_total=Count("id", filter=Q(status=EventStatus.CLOSED)),
        threshold_anomaly_open=Count(
            "id",
            filter=Q(status=EventStatus.OPEN, event_type=EventType.THRESHOLD_ANOMALY),
        ),
        communication_timeout_open=Count(
            "id",
            filter=Q(status=EventStatus.OPEN, event_type=EventType.COMMUNICATION_TIMEOUT),
        ),
        warning_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.WARNING),
        ),
        error_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.ERROR),
        ),
        critical_open=Count(
            "id", filter=Q(status=EventStatus.OPEN, severity=Severity.CRITICAL),
        ),
    )
    counts = {k: v or 0 for k, v in count_aggs.items()}

    by_type_rows = (
        scope_qs.values("event_type")
        .annotate(
            open=Count("id", filter=Q(status=EventStatus.OPEN)),
            closed=Count("id", filter=Q(status=EventStatus.CLOSED)),
        )
        .order_by("event_type")
    )
    by_type = [
        {
            "event_type": row["event_type"],
            "open": row["open"] or 0,
            "closed": row["closed"] or 0,
        }
        for row in by_type_rows
    ]

    recent_qs = _full_event_qs(base_qs, request).order_by("-detected_at")
    limit = parse_limit(
        request.query_params.get("limit"),
        default=OVERVIEW_DEFAULT_RECENT_LIMIT,
        maximum=OVERVIEW_MAX_RECENT_LIMIT,
    )
    recent = [_serialise_event_summary(e) for e in recent_qs[:limit]]

    return Response({
        "generated_at": timezone.now(),
        "counts": counts,
        "by_type": by_type,
        "recent": recent,
    })


# ── /api/overview/telemetry/ ─────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def overview_telemetry_view(request):
    """Telemetry health + per-metric latest values + recent measurements."""
    raw_qs = _scope_raw_message_qs(
        RawMessage.objects.select_related("asset", "device"),
        request,
    )
    measurement_qs = _scope_measurement_qs(
        Measurement.objects.select_related("asset", "device", "metric"),
        request,
    )

    raw_aggs = raw_qs.aggregate(
        total=Count("id"),
        parsed=Count("id", filter=Q(processing_status=ProcessingStatus.PARSED)),
        failed=Count("id", filter=Q(processing_status=ProcessingStatus.FAILED)),
        latest=Max("received_at"),
    )
    raw_summary = {
        "total": raw_aggs["total"] or 0,
        "parsed": raw_aggs["parsed"] or 0,
        "failed": raw_aggs["failed"] or 0,
        "latest_received_at": raw_aggs["latest"],
    }

    measurement_aggs = measurement_qs.aggregate(
        total=Count("id"), latest=Max("timestamp"),
    )

    metric_rows = (
        measurement_qs
        .values("metric_id", "metric__key", "metric__unit")
        .annotate(count=Count("id"), latest_timestamp=Max("timestamp"))
        .order_by("metric__key")
    )
    metric_summaries = []
    for row in metric_rows:
        latest_at = row["latest_timestamp"]
        latest_value = None
        if latest_at is not None:
            latest_obj = (
                measurement_qs
                .filter(metric_id=row["metric_id"], timestamp=latest_at)
                .first()
            )
            if latest_obj is not None:
                latest_value = latest_obj.value
        metric_summaries.append({
            "metric_key": row["metric__key"],
            "unit": row["metric__unit"] or "",
            "latest_value": latest_value,
            "latest_timestamp": latest_at,
            "count": row["count"] or 0,
        })

    limit = parse_limit(
        request.query_params.get("limit"),
        default=OVERVIEW_DEFAULT_RECENT_LIMIT,
        maximum=OVERVIEW_MAX_RECENT_LIMIT,
    )
    recent_measurements = [
        _serialise_measurement_summary(m)
        for m in measurement_qs.order_by("-timestamp")[:limit]
    ]

    return Response({
        "generated_at": timezone.now(),
        "raw_messages": raw_summary,
        "measurements": {
            "total": measurement_aggs["total"] or 0,
            "latest_timestamp": measurement_aggs["latest"],
            "metrics": metric_summaries,
        },
        "recent_measurements": recent_measurements,
    })


# ── /api/overview/simulator/ ─────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def overview_simulator_view(request):
    """Simulator scenarios + run history summary."""
    scenario_aggs = SimulatorScenario.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
    )

    runs_qs = _scope_simulator_run_qs(
        SimulatorRun.objects.select_related("scenario"),
        request,
    )
    run_aggs = runs_qs.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        failed=Count("id", filter=Q(status="failed")),
        running=Count("id", filter=Q(status="running")),
    )
    latest_run = runs_qs.order_by("-started_at").first()
    runs_summary = {
        "total": run_aggs["total"] or 0,
        "completed": run_aggs["completed"] or 0,
        "failed": run_aggs["failed"] or 0,
        "running": run_aggs["running"] or 0,
        "latest_status": latest_run.status if latest_run else None,
        "latest_started_at": latest_run.started_at if latest_run else None,
        "latest_finished_at": latest_run.finished_at if latest_run else None,
        "latest_messages_published": (
            latest_run.messages_published if latest_run else None
        ),
    }

    limit = parse_limit(
        request.query_params.get("limit"),
        default=OVERVIEW_DEFAULT_RECENT_LIMIT,
        maximum=OVERVIEW_MAX_RECENT_LIMIT,
    )
    recent_runs = [
        _serialise_simulator_run_summary(run)
        for run in runs_qs.order_by("-started_at")[:limit]
    ]

    return Response({
        "generated_at": timezone.now(),
        "scenarios": {
            "total": scenario_aggs["total"] or 0,
            "active": scenario_aggs["active"] or 0,
        },
        "runs": runs_summary,
        "recent_runs": recent_runs,
    })


# ── /api/assets/{id-or-code}/summary/ helper ─────────────────────────────────

def build_asset_summary(asset, request) -> dict:
    """
    Build the response payload for ``/api/assets/{id-or-code}/summary/``.
    Defined here (instead of inline in ``AssetViewSet.summary``) so the
    aggregation logic is colocated with the rest of the dashboard
    serialisation.
    """
    metrics_limit = parse_limit(
        request.query_params.get("metrics_limit"),
        default=ASSET_SUMMARY_DEFAULT_INNER_LIMIT,
        maximum=ASSET_SUMMARY_MAX_INNER_LIMIT,
        param="metrics_limit",
    )
    events_limit = parse_limit(
        request.query_params.get("events_limit"),
        default=ASSET_SUMMARY_DEFAULT_INNER_LIMIT,
        maximum=ASSET_SUMMARY_MAX_INNER_LIMIT,
        param="events_limit",
    )

    try:
        state: Optional[AssetState] = asset.state
    except AssetState.DoesNotExist:
        state = None

    state_block = None
    if state is not None:
        state_block = {
            "status": state.status,
            "last_seen_at": state.last_seen_at,
            "last_measurement_at": state.last_measurement_at,
            "last_temperature_c": state.last_temperature_c,
            "last_voltage_v": state.last_voltage_v,
            "last_current_a": state.last_current_a,
            "last_power_w": state.last_power_w,
            "last_battery_soc_pct": state.last_battery_soc_pct,
            "has_active_anomaly": state.has_active_anomaly,
            "active_anomaly_count": state.active_anomaly_count,
        }

    open_events_qs = (
        Event.objects
        .select_related("asset", "device", "metric")
        .filter(asset=asset, status=EventStatus.OPEN)
        .order_by("-detected_at")
    )
    open_events = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "severity": e.severity,
            "status": e.status,
            "title": e.title,
            "detected_at": e.detected_at,
        }
        for e in open_events_qs[:events_limit]
    ]

    # Latest measurement per metric, scoped to this asset.
    metric_rows = (
        Measurement.objects
        .filter(asset=asset)
        .values("metric_id", "metric__key", "metric__unit")
        .annotate(latest_timestamp=Max("timestamp"))
        .order_by("metric__key")[:metrics_limit]
    )
    latest_measurements = []
    for row in metric_rows:
        latest_at = row["latest_timestamp"]
        if latest_at is None:
            continue
        latest_obj = (
            Measurement.objects
            .select_related("metric")
            .filter(asset=asset, metric_id=row["metric_id"], timestamp=latest_at)
            .first()
        )
        if latest_obj is None:
            continue
        latest_measurements.append({
            "metric_key": row["metric__key"],
            "value": latest_obj.value,
            "unit": latest_obj.unit or row["metric__unit"] or "",
            "timestamp": latest_at,
        })

    latest_raw = (
        RawMessage.objects
        .filter(asset=asset)
        .order_by("-received_at")
        .first()
    )
    latest_raw_block = None
    if latest_raw is not None:
        latest_raw_block = {
            "message_id": latest_raw.message_id,
            "processing_status": latest_raw.processing_status,
            "received_at": latest_raw.received_at,
            "topic": latest_raw.topic,
        }

    return {
        "asset": {
            "id": str(asset.id),
            "code": asset.code,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "site_code": asset.site.code if asset.site_id else None,
            "status": asset.status,
        },
        "state": state_block,
        "open_events": open_events,
        "latest_measurements": latest_measurements,
        "latest_raw_message": latest_raw_block,
    }
