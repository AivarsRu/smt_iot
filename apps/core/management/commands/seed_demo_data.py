import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assets.models import Asset, AssetType, Device, Sensor, SensorMetric, Site
from apps.core.models import MqttTopicType, OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.iot_config.models import (
    DeviceProfile,
    DeviceProfileMetric,
    MetricDefinition,
    MqttTopicTemplate,
    SensorMetricPreset,
)
from apps.telemetry.models import Measurement, MeasurementQuality, ProcessingStatus, RawMessage, SourceType


METRICS = [
    {
        "key": "voltage_v",
        "display_name": "Voltage",
        "unit": "V",
        "normal_min": 45.0,
        "normal_max": 58.0,
        "warning_min": 40.0,
        "warning_max": 60.0,
        "is_required": True,
        "sort_order": 1,
    },
    {
        "key": "current_a",
        "display_name": "Current",
        "unit": "A",
        "normal_min": 0.0,
        "normal_max": 20.0,
        "warning_min": None,
        "warning_max": 25.0,
        "is_required": True,
        "sort_order": 2,
    },
    {
        "key": "power_w",
        "display_name": "Power",
        "unit": "W",
        "normal_min": 0.0,
        "normal_max": 1200.0,
        "warning_min": None,
        "warning_max": 1500.0,
        "is_required": True,
        "sort_order": 3,
    },
    {
        "key": "temperature_c",
        "display_name": "Temperature",
        "unit": "°C",
        "normal_min": -10.0,
        "normal_max": 45.0,
        "warning_min": -20.0,
        "warning_max": 55.0,
        "is_required": True,
        "sort_order": 4,
    },
    {
        "key": "battery_soc_pct",
        "display_name": "Battery State of Charge",
        "unit": "%",
        "normal_min": 10.0,
        "normal_max": 100.0,
        "warning_min": 5.0,
        "warning_max": None,
        "is_required": False,
        "sort_order": 5,
    },
]

TOPIC_TEMPLATES = [
    {
        "name": "default_telemetry",
        "topic_type": MqttTopicType.TELEMETRY,
        "template": "smt/{environment}/{site_id}/{asset_type}/{device_id}/telemetry",
        "description": "Standard telemetry topic template.",
    },
    {
        "name": "default_status",
        "topic_type": MqttTopicType.STATUS,
        "template": "smt/{environment}/{site_id}/{asset_type}/{device_id}/status",
        "description": "Standard status topic template.",
    },
    {
        "name": "default_event",
        "topic_type": MqttTopicType.EVENT,
        "template": "smt/{environment}/{site_id}/{asset_type}/{device_id}/event",
        "description": "Standard event topic template.",
    },
]

# Fixed demo values — stable across repeated seed runs
DEMO_MESSAGE_ID = "demo-seed-rawmessage-001"
DEMO_TIMESTAMP = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
DEMO_METRIC_VALUES = {
    "voltage_v": 52.3,
    "current_a": 1.8,
    "power_w": 94.1,
    "temperature_c": 31.5,
    "battery_soc_pct": 78.0,
}


class Command(BaseCommand):
    help = "Create or update minimal demonstration data (idempotent)."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        def track(created):
            nonlocal created_count, updated_count
            if created:
                created_count += 1
            else:
                updated_count += 1

        # ── Infrastructure ────────────────────────────────────────────────────

        site, created = Site.objects.update_or_create(
            code="default_demo",
            defaults={
                "name": "Demo Site",
                "description": "Default demonstration site.",
                "timezone": "Europe/Riga",
                "is_demo": True,
            },
        )
        track(created)

        asset, created = Asset.objects.update_or_create(
            site=site,
            code="charger-001",
            defaults={
                "name": "Demo Charger 001",
                "asset_type": AssetType.CHARGER,
                "status": OperationalStatus.ACTIVE,
                "description": "Demonstration EV charger unit.",
            },
        )
        track(created)

        device, created = Device.objects.update_or_create(
            device_uid="charger-001",
            defaults={
                "site": site,
                "asset": asset,
                "name": "Charger 001 Controller",
                "device_type": "charger",
                "is_simulated": True,
                "expected_interval_seconds": 60,
                "status": OperationalStatus.ACTIVE,
            },
        )
        track(created)

        sensor, created = Sensor.objects.update_or_create(
            device=device,
            code="main",
            defaults={
                "name": "Main Sensor",
                "sensor_type": "composite",
                "description": "Primary telemetry sensor on charger-001.",
            },
        )
        track(created)

        # ── IoT configuration ─────────────────────────────────────────────────

        metric_objects = {}
        for data in METRICS:
            metric, created = MetricDefinition.objects.update_or_create(
                key=data["key"],
                defaults={
                    "display_name": data["display_name"],
                    "unit": data["unit"],
                    "normal_min": data.get("normal_min"),
                    "normal_max": data.get("normal_max"),
                    "warning_min": data.get("warning_min"),
                    "warning_max": data.get("warning_max"),
                    "is_required": data["is_required"],
                    "sort_order": data["sort_order"],
                },
            )
            metric_objects[data["key"]] = (metric, data["is_required"])
            track(created)

        for data in TOPIC_TEMPLATES:
            _, created = MqttTopicTemplate.objects.update_or_create(
                topic_type=data["topic_type"],
                name=data["name"],
                defaults={
                    "template": data["template"],
                    "description": data["description"],
                },
            )
            track(created)

        profile, created = DeviceProfile.objects.update_or_create(
            code="demo_charger_profile",
            defaults={
                "name": "Demo Charger Profile",
                "device_type": "charger",
                "description": "Default device profile for demonstration charger devices.",
                "default_expected_interval_seconds": 60,
            },
        )
        track(created)

        for sort_idx, (key, (metric, is_required)) in enumerate(metric_objects.items(), start=1):
            _, created = DeviceProfileMetric.objects.update_or_create(
                profile=profile,
                metric=metric,
                defaults={"is_required": is_required, "sort_order": sort_idx},
            )
            track(created)

        # ── Sensor metric capability ──────────────────────────────────────────
        # DeviceProfileMetric remains a template-level catalogue; the live
        # capability mapping per Sensor lives in SensorMetric.

        for sort_idx, (key, (metric, is_required)) in enumerate(metric_objects.items(), start=1):
            _, created = SensorMetric.objects.update_or_create(
                sensor=sensor,
                metric=metric,
                defaults={"is_required": is_required, "sort_order": sort_idx},
            )
            track(created)

        # ── Raw telemetry message ─────────────────────────────────────────────

        demo_payload = {
            "message_id": DEMO_MESSAGE_ID,
            "device_id": "charger-001",
            "asset_id": "asset-001",
            "timestamp": DEMO_TIMESTAMP.isoformat(),
            "metrics": DEMO_METRIC_VALUES,
            "status": "charging",
            "firmware_version": "0.1.0",
        }

        raw_message, created = RawMessage.objects.update_or_create(
            message_id=DEMO_MESSAGE_ID,
            defaults={
                "source_type": SourceType.SIMULATOR,
                "topic": "smt/local/default_demo/charger/charger-001/telemetry",
                "payload": demo_payload,
                "device_uid": "charger-001",
                "device": device,
                "site": site,
                "asset": asset,
                "payload_timestamp": DEMO_TIMESTAMP,
                "processing_status": ProcessingStatus.PARSED,
                "parser_version": "1.0",
            },
        )
        track(created)

        # ── Measurements ──────────────────────────────────────────────────────

        for key, (metric, _) in metric_objects.items():
            raw_value = DEMO_METRIC_VALUES.get(key)
            _, created = Measurement.objects.update_or_create(
                raw_message=raw_message,
                metric=metric,
                defaults={
                    "site": site,
                    "asset": asset,
                    "device": device,
                    "sensor": sensor,
                    "timestamp": DEMO_TIMESTAMP,
                    "value_float": raw_value,
                    "unit": metric.unit,
                    "quality": MeasurementQuality.GOOD,
                },
            )
            track(created)

        # ── Digital twin state ────────────────────────────────────────────────

        asset_state, created = AssetState.objects.update_or_create(
            asset=asset,
            defaults={
                "site": site,
                "device": device,
                "status": OperationalStatus.ACTIVE,
                "last_seen_at": DEMO_TIMESTAMP,
                "last_measurement_at": DEMO_TIMESTAMP,
                "last_raw_message": raw_message,
                "last_voltage_v": DEMO_METRIC_VALUES["voltage_v"],
                "last_current_a": DEMO_METRIC_VALUES["current_a"],
                "last_power_w": DEMO_METRIC_VALUES["power_w"],
                "last_temperature_c": DEMO_METRIC_VALUES["temperature_c"],
                "last_battery_soc_pct": DEMO_METRIC_VALUES["battery_soc_pct"],
                "active_anomaly_count": 0,
                "has_active_anomaly": False,
                "state_payload": DEMO_METRIC_VALUES,
            },
        )
        track(created)

        # ── Demo event ────────────────────────────────────────────────────────

        event, created = Event.objects.update_or_create(
            source="seed_demo_data",
            event_type=EventType.SYSTEM,
            asset=asset,
            defaults={
                "severity": Severity.INFO,
                "status": EventStatus.CLOSED,
                "site": site,
                "device": device,
                "title": "Demo system initialisation",
                "description": "Automatically created during seed_demo_data.",
                "detected_at": DEMO_TIMESTAMP,
                "closed_at": DEMO_TIMESTAMP,
                "payload": {"seed_version": "2.0"},
            },
        )
        track(created)

        # ── Simulator configuration ───────────────────────────────────────────

        from apps.simulator.models import SimulatorMetricProfile, SimulatorScenario, SimulatorScenarioDevice

        scenario, created = SimulatorScenario.objects.update_or_create(
            code="default_demo",
            defaults={
                "name": "Default Demo Scenario",
                "description": "Demonstration simulator scenario for charger-001.",
                "site": site,
                "default_status": "charging",
                "interval_seconds": 60,
                "is_active": True,
            },
        )
        track(created)

        scenario_device, created = SimulatorScenarioDevice.objects.update_or_create(
            scenario=scenario,
            device=device,
            defaults={
                "device_profile": profile,
                "is_enabled": True,
                "sort_order": 1,
            },
        )
        track(created)

        DEMO_METRIC_PROFILES = [
            {"key": "voltage_v",       "base": 52.0, "min": 48.0,  "max": 58.0,  "noise": 0.5},
            {"key": "current_a",       "base": 1.8,  "min": 0.0,   "max": 5.0,   "noise": 0.2},
            {"key": "power_w",         "base": 90.0, "min": 0.0,   "max": 150.0, "noise": 5.0},
            {"key": "temperature_c",   "base": 30.0, "min": -20.0, "max": 70.0,  "noise": 2.0},
            {"key": "battery_soc_pct", "base": 80.0, "min": 0.0,   "max": 100.0, "noise": 1.5},
        ]

        for sort_idx, mp_data in enumerate(DEMO_METRIC_PROFILES, start=1):
            metric_obj, _ = metric_objects[mp_data["key"]]
            # Sensor-centric: every simulator profile points at the sensor
            # that produces the metric. Match on (scenario_device, sensor,
            # metric) so re-runs update the existing row instead of
            # producing duplicates.
            _, created = SimulatorMetricProfile.objects.update_or_create(
                scenario_device=scenario_device,
                sensor=sensor,
                metric=metric_obj,
                defaults={
                    "base_value": mp_data["base"],
                    "min_value": mp_data["min"],
                    "max_value": mp_data["max"],
                    "noise_amplitude": mp_data["noise"],
                    "generation_mode": "random_noise",
                    "is_enabled": True,
                    "sort_order": sort_idx,
                },
            )
            track(created)

        # Migrate any legacy SimulatorMetricProfile rows that the
        # ``simulator.0002_simulatormetricprofile_sensor`` data migration
        # could not auto-assign (e.g., seeded before the demo sensor
        # existed) onto the demo sensor.
        legacy_profiles = SimulatorMetricProfile.objects.filter(
            scenario_device=scenario_device, sensor__isnull=True,
        )
        if legacy_profiles.exists():
            updated = legacy_profiles.update(sensor=sensor)
            updated_count += updated

        # ── Analytics threshold rules ─────────────────────────────────────────
        # Demo bounds chosen to be OUTSIDE the simulator's normal operating
        # range, so a normal simulator run does NOT trigger them. They exist
        # as anchors for manual anomaly demonstrations and analytics tests.

        from apps.analytics.models import ThresholdRule, ThresholdRuleScope

        # Demo rules are deliberately **sensor-scoped** to the demo charger's
        # ``main`` sensor. The previous broad-NULL semantics caused one MQTT
        # message to fire three "temperature_c" rules at once on the demo
        # sensor *and* would have fired on any other unrelated sensor that
        # produced temperature_c. With explicit scope_level=SENSOR each rule
        # is bound to the sensor it is meant for and stays out of unrelated
        # sensors' way.
        DEMO_THRESHOLD_RULES = [
            {
                "code": "temperature_c_high_warning",
                "name": "Charger 'main' sensor temperature high (warning)",
                "metric_key": "temperature_c",
                "lower_bound": None,
                "upper_bound": 60.0,
                "severity": Severity.WARNING,
                "description": (
                    "Warn when the 'main' sensor of charger-001 reports "
                    "a temperature above 60°C."
                ),
                "sort_order": 10,
                "scope_level": ThresholdRuleScope.SENSOR,
            },
            {
                "code": "temperature_c_high_error",
                "name": "Charger 'main' sensor temperature critical (error)",
                "metric_key": "temperature_c",
                "lower_bound": None,
                "upper_bound": 70.0,
                "severity": Severity.ERROR,
                "description": (
                    "Error when the 'main' sensor of charger-001 reports "
                    "a temperature above 70°C."
                ),
                "sort_order": 11,
                "scope_level": ThresholdRuleScope.SENSOR,
            },
            {
                "code": "battery_soc_low_warning",
                "name": "Charger 'main' battery state of charge low (warning)",
                "metric_key": "battery_soc_pct",
                "lower_bound": 20.0,
                "upper_bound": None,
                "severity": Severity.WARNING,
                "description": (
                    "Warn when the 'main' sensor of charger-001 reports a "
                    "battery state of charge below 20 %."
                ),
                "sort_order": 20,
                "scope_level": ThresholdRuleScope.SENSOR,
            },
        ]

        for rule_data in DEMO_THRESHOLD_RULES:
            metric_obj, _ = metric_objects[rule_data["metric_key"]]
            scope = rule_data["scope_level"]
            defaults = {
                "name": rule_data["name"],
                "description": rule_data["description"],
                "metric": metric_obj,
                "scope_level": scope,
                "site": (
                    sensor.device.site
                    if scope == ThresholdRuleScope.SENSOR else None
                ),
                "asset": (
                    sensor.device.asset
                    if scope == ThresholdRuleScope.SENSOR else None
                ),
                "device": (
                    sensor.device
                    if scope == ThresholdRuleScope.SENSOR else None
                ),
                "sensor": (
                    sensor if scope == ThresholdRuleScope.SENSOR else None
                ),
                "is_enabled": True,
                "lower_bound": rule_data["lower_bound"],
                "upper_bound": rule_data["upper_bound"],
                "severity": rule_data["severity"],
                "close_when_normal": True,
                "sort_order": rule_data["sort_order"],
            }
            _, created = ThresholdRule.objects.update_or_create(
                code=rule_data["code"], defaults=defaults,
            )
            track(created)

        # ── Operator workflow presets (Phase 7, Task 3B) ────────────
        # SensorMetricPreset: pairs a common sensor "shape" with the
        # metric it typically produces. The Stage 3/4 forms use these
        # to fast-track repeated sensor configuration.

        DEMO_SENSOR_PRESETS = [
            {
                "code": "temperature_sensor_preset",
                "name": "Temperatūras sensors",
                "description": (
                    "Universāls temperatūras sensors, kas raksta "
                    "vērtības metrikā 'temperature_c'."
                ),
                "sensor_type": "temperature",
                "metric_key": "temperature_c",
                "default_sensor_name": "Temperatūras sensors",
                "is_required": True,
                "sort_order": 10,
            },
            {
                "code": "voltage_sensor_preset",
                "name": "Sprieguma sensors",
                "description": "Sprieguma sensors metrikai 'voltage_v'.",
                "sensor_type": "voltage",
                "metric_key": "voltage_v",
                "default_sensor_name": "Sprieguma sensors",
                "is_required": True,
                "sort_order": 20,
            },
            {
                "code": "power_sensor_preset",
                "name": "Jaudas sensors",
                "description": "Jaudas sensors metrikai 'power_w'.",
                "sensor_type": "power",
                "metric_key": "power_w",
                "default_sensor_name": "Jaudas sensors",
                "is_required": True,
                "sort_order": 30,
            },
            {
                "code": "battery_soc_sensor_preset",
                "name": "Baterijas SoC sensors",
                "description": (
                    "Baterijas uzlādes līmeņa sensors metrikai "
                    "'battery_soc_pct'."
                ),
                "sensor_type": "battery_soc",
                "metric_key": "battery_soc_pct",
                "default_sensor_name": "Baterijas SoC sensors",
                "is_required": False,
                "sort_order": 40,
            },
        ]

        for preset_data in DEMO_SENSOR_PRESETS:
            metric_obj, _ = metric_objects[preset_data["metric_key"]]
            _, created = SensorMetricPreset.objects.update_or_create(
                code=preset_data["code"],
                defaults={
                    "name": preset_data["name"],
                    "description": preset_data["description"],
                    "sensor_type": preset_data["sensor_type"],
                    "metric": metric_obj,
                    "default_sensor_name": preset_data["default_sensor_name"],
                    "is_required": preset_data["is_required"],
                    "sort_order": preset_data["sort_order"],
                },
            )
            track(created)

        # ThresholdRulePreset: reusable threshold definitions that the
        # Stage 4 form materialises into concrete ``ThresholdRule`` rows
        # scoped to a specific Asset/Device/Sensor/Metric.

        from apps.analytics.models import ThresholdRulePreset

        DEMO_THRESHOLD_PRESETS = [
            {
                "code": "outdoor_temperature_range",
                "name": "Āra temperatūras diapazons (-40°C…+40°C)",
                "description": (
                    "Brīdina, ja temperatūra iziet ārpus -40°C…+40°C "
                    "diapazona."
                ),
                "metric_key": "temperature_c",
                "lower_bound": -40.0,
                "upper_bound": 40.0,
                "severity": Severity.WARNING,
            },
            {
                "code": "high_temperature_warning",
                "name": "Augsta temperatūra (>60°C)",
                "description": "Brīdina, ja temperatūra pārsniedz 60°C.",
                "metric_key": "temperature_c",
                "lower_bound": None,
                "upper_bound": 60.0,
                "severity": Severity.WARNING,
            },
            {
                "code": "battery_soc_low_warning_preset",
                "name": "Baterija zem 20%",
                "description": (
                    "Brīdina, ja baterijas uzlādes līmenis kļūst zem 20%."
                ),
                "metric_key": "battery_soc_pct",
                "lower_bound": 20.0,
                "upper_bound": None,
                "severity": Severity.WARNING,
            },
        ]

        for preset_data in DEMO_THRESHOLD_PRESETS:
            metric_obj, _ = metric_objects[preset_data["metric_key"]]
            # ``update_or_create`` calls .save() which triggers .clean()
            # via the preset's own validation. Always pre-fill bounds.
            obj, created = ThresholdRulePreset.objects.update_or_create(
                code=preset_data["code"],
                defaults={
                    "name": preset_data["name"],
                    "description": preset_data["description"],
                    "metric": metric_obj,
                    "lower_bound": preset_data["lower_bound"],
                    "upper_bound": preset_data["upper_bound"],
                    "severity": preset_data["severity"],
                    "close_when_normal": True,
                },
            )
            track(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo_data complete: {created_count} created, {updated_count} updated."
            )
        )
