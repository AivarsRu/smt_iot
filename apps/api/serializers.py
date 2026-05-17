"""
Read-only DRF serializers for the SMT Digital Solution prototype API.

Every serializer in this module exposes domain data in a flat,
JSON-friendly shape and uses pre-fetched related objects (`source="x.y"`)
to avoid N+1 queries — the matching ViewSet must use ``select_related``.

Phase 6 Task 1 only ships read access. No write operations or input
validation is intentional here.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.analytics.models import ThresholdRule
from apps.assets.models import Asset, Device, Sensor, Site
from apps.digital_twin.models import AssetState
from apps.events.models import Event
from apps.iot_config.models import MetricDefinition
from apps.simulator.models import SimulatorRun, SimulatorScenario
from apps.telemetry.models import Measurement, RawMessage


# ── Assets ───────────────────────────────────────────────────────────────────

class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = (
            "id", "code", "name", "description",
            "address", "latitude", "longitude", "timezone", "is_demo",
            "created_at", "updated_at",
        )


class AssetSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    parent_code = serializers.CharField(source="parent.code", read_only=True, default=None)

    class Meta:
        model = Asset
        fields = (
            "id", "site", "site_code", "parent", "parent_code",
            "code", "name", "asset_type", "status", "description",
            "latitude", "longitude", "external_id",
            "created_at", "updated_at",
        )


class DeviceSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)

    class Meta:
        model = Device
        fields = (
            "id", "site", "site_code", "asset", "asset_code",
            "device_uid", "name", "device_type", "is_simulated",
            "expected_interval_seconds", "firmware_version", "status",
            "last_seen_at", "created_at", "updated_at",
        )


class SensorSerializer(serializers.ModelSerializer):
    device_uid = serializers.CharField(source="device.device_uid", read_only=True, default=None)

    class Meta:
        model = Sensor
        fields = (
            "id", "device", "device_uid", "code", "name",
            "sensor_type", "description",
            "created_at", "updated_at",
        )


# ── IoT config ───────────────────────────────────────────────────────────────

class MetricDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricDefinition
        fields = (
            "id", "key", "display_name", "description",
            "unit", "data_type",
            "normal_min", "normal_max", "warning_min", "warning_max",
            "is_required", "sort_order",
        )


# ── Digital twin ─────────────────────────────────────────────────────────────

class AssetStateSerializer(serializers.ModelSerializer):
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    device_uid = serializers.CharField(source="device.device_uid", read_only=True, default=None)

    class Meta:
        model = AssetState
        fields = (
            "id", "asset", "asset_code", "site", "site_code",
            "device", "device_uid",
            "status", "last_seen_at", "last_measurement_at",
            "last_temperature_c", "last_voltage_v", "last_current_a",
            "last_power_w", "last_battery_soc_pct",
            "active_anomaly_count", "has_active_anomaly",
            "state_payload", "updated_at",
        )


# ── Telemetry ────────────────────────────────────────────────────────────────

class MeasurementSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)
    device_uid = serializers.CharField(source="device.device_uid", read_only=True, default=None)
    sensor_code = serializers.CharField(source="sensor.code", read_only=True, default=None)
    metric_key = serializers.CharField(source="metric.key", read_only=True, default=None)
    metric_unit = serializers.CharField(source="metric.unit", read_only=True, default=None)
    value = serializers.SerializerMethodField()

    class Meta:
        model = Measurement
        fields = (
            "id",
            "site", "site_code",
            "asset", "asset_code",
            "device", "device_uid",
            "sensor", "sensor_code",
            "metric", "metric_key", "metric_unit",
            "timestamp", "value",
            "value_float", "value_int", "value_bool", "value_text",
            "unit", "quality", "is_anomalous",
            "raw_message", "created_at",
        )

    @staticmethod
    def get_value(obj) -> object:
        # Delegates to ``Measurement.value`` property (returns the first
        # non-null typed value or None). Stays JSON-serialisable for all
        # supported data types.
        return obj.value


class RawMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawMessage
        fields = (
            "id", "source_type", "topic", "message_id",
            "device_uid", "device", "site", "asset",
            "received_at", "payload_timestamp",
            "processing_status", "error_message", "parser_version",
            "payload", "payload_text",
            "created_at",
        )


# ── Events ───────────────────────────────────────────────────────────────────

class EventSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)
    device_uid = serializers.CharField(source="device.device_uid", read_only=True, default=None)
    sensor_code = serializers.CharField(source="sensor.code", read_only=True, default=None)
    metric_key = serializers.CharField(source="metric.key", read_only=True, default=None)

    class Meta:
        model = Event
        fields = (
            "id", "event_type", "severity", "status",
            "site", "site_code",
            "asset", "asset_code",
            "device", "device_uid",
            "sensor", "sensor_code",
            "metric", "metric_key",
            "measurement", "raw_message",
            "title", "description",
            "detected_at", "acknowledged_at", "closed_at",
            "source", "payload",
            "created_at", "updated_at",
        )


# ── Analytics ────────────────────────────────────────────────────────────────

class ThresholdRuleSerializer(serializers.ModelSerializer):
    metric_key = serializers.CharField(source="metric.key", read_only=True, default=None)
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)
    device_uid = serializers.CharField(source="device.device_uid", read_only=True, default=None)

    class Meta:
        model = ThresholdRule
        fields = (
            "id", "code", "name", "description",
            "metric", "metric_key",
            "site", "site_code",
            "asset", "asset_code",
            "device", "device_uid",
            "is_enabled", "lower_bound", "upper_bound", "severity",
            "message_template", "close_when_normal", "sort_order",
            "created_at", "updated_at",
        )


# ── Simulator ────────────────────────────────────────────────────────────────

class SimulatorScenarioSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True, default=None)

    class Meta:
        model = SimulatorScenario
        fields = (
            "id", "code", "name", "description",
            "site", "site_code",
            "is_active", "default_status",
            "interval_seconds", "last_run_at",
            "created_at", "updated_at",
        )


class SimulatorRunSerializer(serializers.ModelSerializer):
    scenario_code = serializers.CharField(source="scenario.code", read_only=True, default=None)

    class Meta:
        model = SimulatorRun
        fields = (
            "id", "scenario", "scenario_code",
            "started_at", "finished_at", "status",
            "messages_published", "error_message",
            "created_at", "updated_at",
        )
