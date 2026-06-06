"""
Read-only DRF ViewSets and a tiny health endpoint for the SMT Digital
Solution prototype API. Phase 6 Task 1 keeps everything read-only.

ViewSets share a small ``LimitedListMixin`` that applies a default and
maximum ``?limit=N`` slice on list responses; ``retrieve`` is unaffected.
List queries always pass through ``select_related`` to avoid N+1 fan-out
when the serializer dereferences related fields.
"""

from __future__ import annotations

from typing import Optional

from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import (
    action,
    api_view,
    permission_classes,
)
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.analytics.models import ThresholdRule
from apps.api.filters import (
    apply_datetime_range,
    filter_by_id_or_code,
    looks_like_uuid,
    parse_bool,
    parse_limit,
    validate_choice,
)
from apps.api.overview import build_asset_summary
from apps.api.serializers import (
    AssetSerializer,
    AssetStateSerializer,
    DeviceSerializer,
    EventSerializer,
    MeasurementSerializer,
    MetricDefinitionSerializer,
    RawMessageSerializer,
    SensorMetricSerializer,
    SensorSerializer,
    SimulatorRunSerializer,
    SimulatorScenarioSerializer,
    SiteSerializer,
    ThresholdRuleSerializer,
)
from apps.assets.models import Asset, Device, Sensor, SensorMetric, Site
from apps.core.models import OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.iot_config.models import MetricDefinition
from apps.simulator.models import SimulatorRun, SimulatorScenario
from apps.telemetry.models import Measurement, ProcessingStatus, RawMessage, SourceType


DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


# ── Health ───────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    """Lightweight liveness + DB reachability probe for the dashboard."""
    db_status = "ok"
    http_status = 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        db_status = f"error: {exc}"
        http_status = 503

    return Response(
        {
            "status": "ok" if http_status == 200 else "degraded",
            "service": "smt-digital-solution",
            "database": db_status,
        },
        status=http_status,
    )


# ── Shared mixin: bounded ?limit=N slicing ───────────────────────────────────

class LimitedListMixin:
    """
    Applies ``?limit=N`` slicing to list endpoints, defaulting to
    ``DEFAULT_LIMIT`` and capped at ``MAX_LIMIT``. ``retrieve`` is
    unaffected because ``list()`` is overridden directly here.
    """

    default_limit = DEFAULT_LIMIT
    max_limit = MAX_LIMIT

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        limit = parse_limit(
            request.query_params.get("limit"),
            default=self.default_limit, maximum=self.max_limit,
        )
        sliced = queryset[:limit]
        serializer = self.get_serializer(sliced, many=True)
        return Response(serializer.data)


class IdOrCodeLookupMixin:
    """
    Lets ``/api/<resource>/<lookup>/`` accept either a UUID primary key or a
    human-readable identifier (subclass picks the column via
    ``code_lookup_field`` — for example ``code`` for ``Asset`` and ``Site``,
    or ``device_uid`` for ``Device``). Mirrors the id-or-code behaviour
    already used by the list filters so URLs like
    ``/api/assets/charger-001/state/`` work out of the box.
    """

    code_lookup_field: str = "code"

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if looks_like_uuid(lookup_value):
            obj = get_object_or_404(queryset, pk=lookup_value)
        else:
            obj = get_object_or_404(queryset, **{self.code_lookup_field: lookup_value})
        self.check_object_permissions(self.request, obj)
        return obj


# ── Sites ────────────────────────────────────────────────────────────────────

class SiteViewSet(IdOrCodeLookupMixin, LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Site.objects.all().order_by("code")
    serializer_class = SiteSerializer
    code_lookup_field = "code"


# ── Assets ───────────────────────────────────────────────────────────────────

class AssetViewSet(IdOrCodeLookupMixin, LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AssetSerializer
    code_lookup_field = "code"

    def get_queryset(self):
        qs = (
            Asset.objects
            .select_related("site", "parent")
            .order_by("site__code", "code")
        )
        request = self.request
        if request is None:
            return qs

        raw_site = request.query_params.get("site")
        qs = filter_by_id_or_code(qs, raw_site, code_field="site__code", id_field="site__id", param="site")

        raw_status = request.query_params.get("status")
        if raw_status:
            validate_choice(
                raw_status, choices=list(OperationalStatus.values), param="status",
            )
            qs = qs.filter(status=raw_status)

        raw_asset_type = request.query_params.get("asset_type")
        if raw_asset_type:
            from apps.assets.models import AssetType
            validate_choice(
                raw_asset_type, choices=list(AssetType.values), param="asset_type",
            )
            qs = qs.filter(asset_type=raw_asset_type)

        return qs

    # ── nested convenience routes ────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="state")
    def state(self, request, pk=None):
        asset = self.get_object()
        try:
            state = asset.state
        except AssetState.DoesNotExist:
            raise NotFound("AssetState does not exist for this asset.")
        return Response(AssetStateSerializer(state).data)

    @action(detail=True, methods=["get"], url_path="measurements")
    def measurements(self, request, pk=None):
        asset = self.get_object()
        qs = (
            Measurement.objects
            .select_related("site", "asset", "device", "sensor", "metric", "raw_message")
            .filter(asset=asset)
            .order_by("-timestamp")
        )
        qs = _apply_measurement_filters(qs, request, restrict_to_asset=False)
        limit = parse_limit(
            request.query_params.get("limit"),
            default=DEFAULT_LIMIT, maximum=MAX_LIMIT,
        )
        return Response(MeasurementSerializer(qs[:limit], many=True).data)

    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, pk=None):
        asset = self.get_object()
        qs = (
            Event.objects
            .select_related("site", "asset", "device", "sensor", "metric",
                            "measurement", "raw_message")
            .filter(asset=asset)
            .order_by("-detected_at")
        )
        qs = _apply_event_filters(qs, request, restrict_to_asset=False)
        limit = parse_limit(
            request.query_params.get("limit"),
            default=DEFAULT_LIMIT, maximum=MAX_LIMIT,
        )
        return Response(EventSerializer(qs[:limit], many=True).data)

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        # Inherits IdOrCodeLookupMixin via get_object(), so the URL accepts
        # either a UUID or the human-readable asset code.
        asset = self.get_object()
        return Response(build_asset_summary(asset, request))


# ── Devices ──────────────────────────────────────────────────────────────────

class DeviceViewSet(IdOrCodeLookupMixin, LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DeviceSerializer
    code_lookup_field = "device_uid"

    def get_queryset(self):
        qs = (
            Device.objects
            .select_related("site", "asset")
            .order_by("site__code", "device_uid")
        )
        request = self.request
        if request is None:
            return qs

        raw_site = request.query_params.get("site")
        qs = filter_by_id_or_code(qs, raw_site, code_field="site__code", id_field="site__id", param="site")

        raw_asset = request.query_params.get("asset")
        qs = filter_by_id_or_code(qs, raw_asset, code_field="asset__code", id_field="asset__id", param="asset")

        raw_status = request.query_params.get("status")
        if raw_status:
            validate_choice(
                raw_status, choices=list(OperationalStatus.values), param="status",
            )
            qs = qs.filter(status=raw_status)

        raw_simulated = request.query_params.get("is_simulated")
        if raw_simulated is not None:
            qs = qs.filter(is_simulated=parse_bool(raw_simulated, param="is_simulated"))

        return qs


# ── Sensors ──────────────────────────────────────────────────────────────────

class SensorViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SensorSerializer

    def get_queryset(self):
        qs = (
            Sensor.objects
            .select_related("device")
            .prefetch_related("sensor_metrics__metric")
            .order_by("device__device_uid", "code")
        )
        request = self.request
        if request is None:
            return qs

        raw_device = request.query_params.get("device")
        qs = filter_by_id_or_code(
            qs, raw_device,
            code_field="device__device_uid", id_field="device__id", param="device",
        )
        return qs


# ── Sensor metrics ───────────────────────────────────────────────────────────

class SensorMetricViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of the per-sensor metric capability mapping. Filterable
    by ``sensor`` (id or code), ``device`` (id or device_uid), and
    ``metric`` (id or key).
    """

    serializer_class = SensorMetricSerializer

    def get_queryset(self):
        qs = (
            SensorMetric.objects
            .select_related("sensor", "sensor__device", "metric")
            .order_by("sensor__device__device_uid", "sensor__code",
                      "sort_order", "metric__key")
        )
        request = self.request
        if request is None:
            return qs

        raw_sensor = request.query_params.get("sensor")
        qs = filter_by_id_or_code(
            qs, raw_sensor, code_field="sensor__code", id_field="sensor__id",
            param="sensor",
        )

        raw_device = request.query_params.get("device")
        qs = filter_by_id_or_code(
            qs, raw_device, code_field="sensor__device__device_uid",
            id_field="sensor__device__id", param="device",
        )

        raw_metric = request.query_params.get("metric")
        qs = filter_by_id_or_code(
            qs, raw_metric, code_field="metric__key", id_field="metric__id",
            param="metric",
        )
        return qs


# ── Metric definitions ───────────────────────────────────────────────────────

class MetricDefinitionViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    queryset = MetricDefinition.objects.all().order_by("sort_order", "key")
    serializer_class = MetricDefinitionSerializer


# ── Asset states ─────────────────────────────────────────────────────────────

class AssetStateViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AssetStateSerializer

    def get_queryset(self):
        qs = (
            AssetState.objects
            .select_related("site", "asset", "device")
            .order_by("site__code", "asset__code")
        )
        request = self.request
        if request is None:
            return qs

        raw_status = request.query_params.get("status")
        if raw_status:
            validate_choice(
                raw_status, choices=list(OperationalStatus.values), param="status",
            )
            qs = qs.filter(status=raw_status)

        raw_anomaly = request.query_params.get("has_active_anomaly")
        if raw_anomaly is not None:
            qs = qs.filter(
                has_active_anomaly=parse_bool(raw_anomaly, param="has_active_anomaly"),
            )

        raw_site = request.query_params.get("site")
        qs = filter_by_id_or_code(qs, raw_site, code_field="site__code", id_field="site__id", param="site")

        return qs


# ── Measurements ─────────────────────────────────────────────────────────────

def _apply_measurement_filters(qs, request, *, restrict_to_asset: bool):
    """Apply Measurement-style query parameters to ``qs``.

    Supported filters (all optional, all id-or-code where applicable):
      * ``asset``    — only when ``restrict_to_asset`` is True (top-level
                       list endpoint). Nested asset routes hard-bind the
                       FK and skip this branch.
      * ``device``   — device UUID or device_uid.
      * ``sensor``   — sensor UUID or sensor code. Added in Phase 7,
                       Task 4A so the event-detail timeline can pin a
                       chart to one specific sensor.
      * ``metric``   — metric UUID or metric key.
      * ``from``/``to`` — ISO 8601 timestamp range on ``Measurement.timestamp``.
    """
    if restrict_to_asset:
        raw_asset = request.query_params.get("asset")
        qs = filter_by_id_or_code(qs, raw_asset, code_field="asset__code", id_field="asset__id", param="asset")

    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(qs, raw_device, code_field="device__device_uid", id_field="device__id", param="device")

    raw_sensor = request.query_params.get("sensor")
    qs = filter_by_id_or_code(qs, raw_sensor, code_field="sensor__code", id_field="sensor__id", param="sensor")

    raw_metric = request.query_params.get("metric")
    qs = filter_by_id_or_code(qs, raw_metric, code_field="metric__key", id_field="metric__id", param="metric")

    qs = apply_datetime_range(qs, request, field="timestamp")
    return qs


class MeasurementViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = MeasurementSerializer
    default_limit = DEFAULT_LIMIT
    max_limit = MAX_LIMIT

    def get_queryset(self):
        qs = (
            Measurement.objects
            .select_related("site", "asset", "device", "sensor", "metric", "raw_message")
            .order_by("-timestamp")
        )
        request = self.request
        if request is None:
            return qs
        return _apply_measurement_filters(qs, request, restrict_to_asset=True)


# ── Events ───────────────────────────────────────────────────────────────────

def _apply_event_filters(qs, request, *, restrict_to_asset: bool):
    """Apply Event-style query parameters to ``qs``.

    Supported filters (all optional, all id-or-code where applicable):
      * ``asset``       — only when ``restrict_to_asset`` is True; nested
                          asset routes hard-bind the FK.
      * ``device``      — device UUID or device_uid.
      * ``sensor``      — sensor UUID or sensor code. Added in Phase 7,
                          Task 4A so the operator events page can pin to
                          one sensor.
      * ``metric``      — metric UUID or metric key. Added in Phase 7,
                          Task 4A for sensor + metric correlation.
      * ``status``      — EventStatus choice (validated, 400 on bad value).
      * ``event_type``  — EventType choice (validated).
      * ``severity``    — Severity choice (validated).
      * ``from``/``to`` — ISO 8601 range on ``Event.detected_at``.
    """
    if restrict_to_asset:
        raw_asset = request.query_params.get("asset")
        qs = filter_by_id_or_code(qs, raw_asset, code_field="asset__code", id_field="asset__id", param="asset")

    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(qs, raw_device, code_field="device__device_uid", id_field="device__id", param="device")

    raw_sensor = request.query_params.get("sensor")
    qs = filter_by_id_or_code(qs, raw_sensor, code_field="sensor__code", id_field="sensor__id", param="sensor")

    raw_metric = request.query_params.get("metric")
    qs = filter_by_id_or_code(qs, raw_metric, code_field="metric__key", id_field="metric__id", param="metric")

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

    qs = apply_datetime_range(qs, request, field="detected_at")
    return qs


class EventViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = (
            Event.objects
            .select_related("site", "asset", "device", "sensor", "metric",
                            "measurement", "raw_message")
            .order_by("-detected_at")
        )
        request = self.request
        if request is None:
            return qs
        return _apply_event_filters(qs, request, restrict_to_asset=True)


# ── Raw messages ─────────────────────────────────────────────────────────────

class RawMessageViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = RawMessageSerializer

    def get_queryset(self):
        qs = (
            RawMessage.objects
            .select_related("site", "asset", "device")
            .order_by("-received_at")
        )
        request = self.request
        if request is None:
            return qs

        raw_uid = request.query_params.get("device_uid")
        if raw_uid:
            qs = qs.filter(device_uid=raw_uid)

        raw_status = request.query_params.get("processing_status")
        if raw_status:
            validate_choice(
                raw_status, choices=list(ProcessingStatus.values),
                param="processing_status",
            )
            qs = qs.filter(processing_status=raw_status)

        raw_source = request.query_params.get("source_type")
        if raw_source:
            validate_choice(
                raw_source, choices=list(SourceType.values), param="source_type",
            )
            qs = qs.filter(source_type=raw_source)

        qs = apply_datetime_range(qs, request, field="received_at")
        return qs


# ── Threshold rules ──────────────────────────────────────────────────────────

class ThresholdRuleViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    queryset = (
        ThresholdRule.objects
        .select_related("metric", "site", "asset", "device", "sensor")
        .order_by("sort_order", "code")
    )
    serializer_class = ThresholdRuleSerializer


# ── Simulator scenarios ──────────────────────────────────────────────────────

class SimulatorScenarioViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    queryset = (
        SimulatorScenario.objects
        .select_related("site")
        .order_by("code")
    )
    serializer_class = SimulatorScenarioSerializer


# ── Simulator runs ───────────────────────────────────────────────────────────

class SimulatorRunViewSet(LimitedListMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SimulatorRunSerializer

    def get_queryset(self):
        qs = (
            SimulatorRun.objects
            .select_related("scenario")
            .order_by("-started_at")
        )
        request = self.request
        if request is None:
            return qs

        raw_scenario = request.query_params.get("scenario")
        qs = filter_by_id_or_code(
            qs, raw_scenario,
            code_field="scenario__code", id_field="scenario__id",
            param="scenario",
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


# ── Simulator control endpoints (Phase 7, Task 3A + 3B) ────────────────────
#
# Four explicit, narrowly-scoped write endpoints on top of the otherwise
# read-only API. The views wrap the service layer in
# :mod:`apps.simulator.services.control` so the same logic is reused by:
#   * the dashboard simulator panel (HTTP);
#   * future cron / management commands (Python imports);
#   * tests (Python imports without HTTP).
#
# Phase 7, Task 3B replaces the temporary "no auth" stance from Task 3A
# with Django's standard authentication and per-permission gating:
# ``simulator.can_control_simulator`` (or superuser). The permission
# itself is declared on :class:`apps.simulator.models.SimulatorScenario`
# (see ``Meta.permissions``); the gate is enforced inside the views via
# :class:`apps.api.permissions.CanControlSimulator` so the response
# always preserves the stable JSON shape — DRF's default
# ``{"detail": "..."}`` is intentionally avoided here.

from apps.api.permissions import (
    CanControlSimulator,
    SIMULATOR_CONTROL_PERMISSION,
    user_can_control_simulator,
)


def _simulator_response(result: dict) -> Response:
    """Strip the internal ``_http_status`` key and forward it to DRF."""
    payload = dict(result)
    http_status = payload.pop("_http_status", 200)
    return Response(payload, status=http_status)


def _simulator_denied_response(*, action: str, authenticated: bool) -> Response:
    """
    Build a stable JSON denial response with Latvian user-facing text.

    Returns HTTP 401 for anonymous callers and HTTP 403 for authenticated
    users who lack ``simulator.can_control_simulator``. The response body
    matches the standard simulator-control JSON shape so the dashboard
    JavaScript renders it without special-casing error envelopes.
    """
    if authenticated:
        message = "Lietotājam nav tiesību vadīt simulatoru."
        status_code = 403
        status_str = "forbidden"
        error_code = "permission_denied"
    else:
        message = (
            "Lai vadītu simulatoru, lietotājam jābūt pierakstītam sistēmā."
        )
        status_code = 401
        status_str = "unauthenticated"
        error_code = "not_authenticated"
    return Response(
        {
            "ok": False,
            "status": status_str,
            "message": message,
            "scenario": None,
            "last_run_at": None,
            "is_active": False,
            "generated_messages": 0,
            "errors": [error_code],
        },
        status=status_code,
    )


def _check_simulator_control_permission(request) -> Optional[Response]:
    """
    Run ``CanControlSimulator`` against ``request`` and return a
    pre-formatted denial response, or ``None`` to allow the action.
    Keeping the check inside the view (rather than via
    ``permission_classes``) lets us preserve the stable JSON shape
    instead of DRF's default ``{"detail": "..."}`` body.
    """
    if CanControlSimulator().has_permission(request, None):
        return None
    return _simulator_denied_response(
        action="simulator-control",
        authenticated=bool(getattr(request.user, "is_authenticated", False)),
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def simulator_status_view(request):
    """
    Return the current simulator status (no side effects).

    Stays publicly readable because the dashboard panel needs to render
    even for users without control rights — they should see WHY they
    can't press the buttons. The response always includes a
    ``can_control`` boolean derived from
    :func:`apps.api.permissions.user_can_control_simulator` so the
    frontend can decide whether to enable the action buttons.
    """
    from apps.simulator.services.control import get_simulator_status
    scenario_code = request.query_params.get("scenario") or None
    body = get_simulator_status(scenario_code)
    body["can_control"] = user_can_control_simulator(getattr(request, "user", None))
    body["is_authenticated"] = bool(
        getattr(getattr(request, "user", None), "is_authenticated", False)
    )
    return _simulator_response(body)


@api_view(["POST"])
def simulator_start_view(request):
    """Mark the resolved simulator scenario as active."""
    denied = _check_simulator_control_permission(request)
    if denied is not None:
        return denied
    from apps.simulator.services.control import start_simulator
    scenario_code = (
        request.data.get("scenario")
        or request.query_params.get("scenario")
        or None
    )
    body = start_simulator(scenario_code)
    body["can_control"] = True
    return _simulator_response(body)


@api_view(["POST"])
def simulator_stop_view(request):
    """Mark the resolved simulator scenario as inactive."""
    denied = _check_simulator_control_permission(request)
    if denied is not None:
        return denied
    from apps.simulator.services.control import stop_simulator
    scenario_code = (
        request.data.get("scenario")
        or request.query_params.get("scenario")
        or None
    )
    body = stop_simulator(scenario_code)
    body["can_control"] = True
    return _simulator_response(body)


@api_view(["POST"])
def simulator_run_once_view(request):
    """Execute exactly one bounded simulator cycle synchronously."""
    denied = _check_simulator_control_permission(request)
    if denied is not None:
        return denied
    from apps.simulator.services.control import run_simulator_once
    scenario_code = (
        request.data.get("scenario")
        or request.query_params.get("scenario")
        or None
    )
    dry_run_raw = (
        request.data.get("dry_run")
        if hasattr(request, "data") and "dry_run" in request.data
        else request.query_params.get("dry_run")
    )
    dry_run = parse_bool(dry_run_raw, param="dry_run") if dry_run_raw is not None else False
    body = run_simulator_once(scenario_code, dry_run=dry_run)
    body["can_control"] = True
    return _simulator_response(body)


# ── Phase 7, Task 4 — Simulator profile endpoints ─────────────────────────
#
# A "profile" is a thin alias over :class:`SimulatorScenario` plus its
# attached device + metric configuration. The dashboard simulator
# workspace consumes these endpoints to render the profile selector,
# the per-metric editor, and to save metric-level overrides.
#
# Read access is intentionally permissive (anyone authenticated to view
# the dashboard can browse profiles) so the workspace page renders for
# everyone with the same semantics as the simulator status endpoint.
# Write access (POST/PUT/PATCH) requires the same
# ``simulator.can_control_simulator`` permission as Start/Stop/Run-once.


def _profile_denied_response(*, authenticated: bool) -> Response:
    """Stable JSON denial body for simulator profile writes."""
    if authenticated:
        return Response(
            {
                "ok": False,
                "status": "forbidden",
                "message": "Lietotājam nav tiesību rediģēt simulatora profilu.",
                "field_errors": {},
            },
            status=403,
        )
    return Response(
        {
            "ok": False,
            "status": "unauthenticated",
            "message": (
                "Lai rediģētu simulatora profilu, lietotājam jābūt "
                "pierakstītam sistēmā."
            ),
            "field_errors": {},
        },
        status=401,
    )


def _check_profile_write_permission(request) -> Optional[Response]:
    """Reuse the simulator-control permission for profile writes."""
    if CanControlSimulator().has_permission(request, None):
        return None
    return _profile_denied_response(
        authenticated=bool(getattr(request.user, "is_authenticated", False)),
    )


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def simulator_profile_list_view(request):
    """
    ``GET``: list all simulator profiles (public read).
    ``POST``: create a new profile; requires ``can_control_simulator``.
    """
    from apps.simulator.services.profiles import (
        create_profile, list_profiles, serialise_profile,
    )

    if request.method == "GET":
        return Response({
            "ok": True,
            "profiles": list_profiles(),
            "can_control": user_can_control_simulator(getattr(request, "user", None)),
        })

    denied = _check_profile_write_permission(request)
    if denied is not None:
        return denied

    scenario, validation = create_profile(request.data or {})
    if scenario is None:
        body = validation.as_response()
        return Response(body, status=400)
    return Response(
        {
            "ok": True,
            "status": "created",
            "message": f"Profils '{scenario.code}' ir izveidots.",
            "profile": serialise_profile(scenario),
        },
        status=201,
    )


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([AllowAny])
def simulator_profile_detail_view(request, code: str):
    """
    ``GET`` (public): return one profile by code.
    ``PUT`` / ``PATCH``: update fields + per-metric overrides; requires
    ``can_control_simulator``. ``PUT`` is treated as a full replacement
    of the editable surface (top-level fields + metrics list); ``PATCH``
    only touches the supplied keys.
    """
    from apps.simulator.services.profiles import (
        get_profile, serialise_profile, update_profile, validate_profile_payload,
    )

    scenario = SimulatorScenario.objects.filter(code=code).first()
    if scenario is None:
        return Response(
            {
                "ok": False,
                "status": "not_found",
                "message": f"Profils '{code}' nav atrasts.",
                "field_errors": {},
            },
            status=404,
        )

    if request.method == "GET":
        return Response({
            "ok": True,
            "profile": get_profile(code),
            "can_control": user_can_control_simulator(getattr(request, "user", None)),
        })

    denied = _check_profile_write_permission(request)
    if denied is not None:
        return denied

    partial = request.method == "PATCH"
    validation = validate_profile_payload(
        request.data or {}, instance=scenario, partial=partial,
    )
    if not validation.ok:
        return Response(validation.as_response(), status=400)

    profile = update_profile(scenario, request.data or {}, partial=partial)
    return Response(
        {
            "ok": True,
            "status": "updated",
            "message": f"Profils '{scenario.code}' ir saglabāts.",
            "profile": profile,
        },
        status=200,
    )
