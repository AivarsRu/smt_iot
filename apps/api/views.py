"""
Read-only DRF ViewSets and a tiny health endpoint for the SMT Digital
Solution prototype API. Phase 6 Task 1 keeps everything read-only.

ViewSets share a small ``LimitedListMixin`` that applies a default and
maximum ``?limit=N`` slice on list responses; ``retrieve`` is unaffected.
List queries always pass through ``select_related`` to avoid N+1 fan-out
when the serializer dereferences related fields.
"""

from __future__ import annotations

from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
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
    SensorSerializer,
    SimulatorRunSerializer,
    SimulatorScenarioSerializer,
    SiteSerializer,
    ThresholdRuleSerializer,
)
from apps.assets.models import Asset, Device, Sensor, Site
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
    queryset = Sensor.objects.select_related("device").order_by("device__device_uid", "code")
    serializer_class = SensorSerializer


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
    """Apply Measurement-style query parameters to ``qs``."""
    if restrict_to_asset:
        raw_asset = request.query_params.get("asset")
        qs = filter_by_id_or_code(qs, raw_asset, code_field="asset__code", id_field="asset__id", param="asset")

    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(qs, raw_device, code_field="device__device_uid", id_field="device__id", param="device")

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
    """Apply Event-style query parameters to ``qs``."""
    if restrict_to_asset:
        raw_asset = request.query_params.get("asset")
        qs = filter_by_id_or_code(qs, raw_asset, code_field="asset__code", id_field="asset__id", param="asset")

    raw_device = request.query_params.get("device")
    qs = filter_by_id_or_code(qs, raw_device, code_field="device__device_uid", id_field="device__id", param="device")

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
        .select_related("metric", "site", "asset", "device")
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
