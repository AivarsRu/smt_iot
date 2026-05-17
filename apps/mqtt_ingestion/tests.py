"""
Tests for the MQTT ingestion service.

All tests run against the SQLite test database:
    python manage.py test apps.mqtt_ingestion --settings=config.settings.test

No live MQTT broker is required.
"""

import datetime

from django.test import TestCase

from apps.assets.models import Asset, AssetType, Device, Sensor, SensorMetric, Site
from apps.core.models import DataType, OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventType, Severity
from apps.iot_config.models import MetricDefinition
from apps.mqtt_ingestion.services.ingestion_service import (
    process_mqtt_message,
    resolve_sensor_for_metric,
)
from apps.mqtt_ingestion.services.payload_validator import coerce_payload, validate_telemetry_payload
from apps.mqtt_ingestion.services.topic_parser import ParsedTopic, parse_topic
from apps.mqtt_ingestion.exceptions import TopicParseError
from apps.telemetry.models import Measurement, ProcessingStatus, RawMessage


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_site(code="default_demo"):
    return Site.objects.create(code=code, name=f"Site {code}")


def _make_asset(site, code="charger-001"):
    return Asset.objects.create(
        site=site, code=code, name=f"Asset {code}", asset_type=AssetType.CHARGER
    )


def _make_device(site, asset, uid="charger-001"):
    return Device.objects.create(
        site=site,
        asset=asset,
        device_uid=uid,
        name=f"Device {uid}",
        device_type="charger",
        is_simulated=True,
        firmware_version="0.0.1",
    )


def _make_sensor(device, code="main"):
    return Sensor.objects.create(device=device, code=code, name="Main Sensor")


def _make_metric(key="voltage_v", unit="V", data_type=DataType.FLOAT):
    return MetricDefinition.objects.create(
        key=key, display_name=key, unit=unit, data_type=data_type
    )


DEMO_TOPIC = "smt/local/default_demo/charger/charger-001/telemetry"


def _demo_payload(**overrides) -> dict:
    base = {
        "message_id": "test-msg-001",
        "device_id": "charger-001",
        "asset_id": "charger-001",
        "timestamp": "2026-05-16T10:00:00Z",
        "metrics": {
            "voltage_v": 52.3,
            "temperature_c": 31.5,
        },
        "status": "charging",
        "firmware_version": "1.2.3",
    }
    base.update(overrides)
    return base


# ── Topic parser unit tests ───────────────────────────────────────────────────

class TopicParserTest(TestCase):

    def test_valid_topic_parsed(self):
        t = parse_topic("smt/local/default_demo/charger/charger-001/telemetry")
        self.assertIsInstance(t, ParsedTopic)
        self.assertEqual(t.environment, "local")
        self.assertEqual(t.site_code, "default_demo")
        self.assertEqual(t.asset_type, "charger")
        self.assertEqual(t.device_uid, "charger-001")
        self.assertEqual(t.message_type, "telemetry")

    def test_too_few_segments(self):
        with self.assertRaises(TopicParseError):
            parse_topic("smt/local/demo/charger")

    def test_wrong_prefix(self):
        with self.assertRaises(TopicParseError):
            parse_topic("bad/local/default_demo/charger/dev/telemetry")

    def test_empty_segment(self):
        with self.assertRaises(TopicParseError):
            parse_topic("smt/local//charger/dev/telemetry")

    def test_status_topic_parsed(self):
        t = parse_topic("smt/dev/site-a/charger/dev-001/status")
        self.assertEqual(t.message_type, "status")


# ── Payload validator unit tests ──────────────────────────────────────────────

class PayloadValidatorTest(TestCase):

    def test_dict_passthrough(self):
        d = {"key": "val"}
        result, text = coerce_payload(d)
        self.assertEqual(result, d)
        self.assertEqual(text, "")

    def test_valid_json_string(self):
        result, text = coerce_payload('{"a": 1}')
        self.assertEqual(result, {"a": 1})
        self.assertEqual(text, '{"a": 1}')

    def test_invalid_json_returns_none(self):
        result, text = coerce_payload("not-json{")
        self.assertIsNone(result)
        self.assertEqual(text, "not-json{")

    def test_bytes_decoded(self):
        result, _ = coerce_payload(b'{"x": 2}')
        self.assertEqual(result, {"x": 2})

    def test_valid_payload_no_errors(self):
        payload = {
            "message_id": "abc",
            "device_id": "dev",
            "timestamp": "2026-01-01T00:00:00Z",
            "metrics": {"v": 1},
        }
        self.assertEqual(validate_telemetry_payload(payload), [])

    def test_missing_message_id(self):
        errors = validate_telemetry_payload({
            "device_id": "dev",
            "timestamp": "2026-01-01T00:00:00Z",
            "metrics": {},
        })
        self.assertTrue(any("message_id" in e for e in errors))

    def test_metrics_not_dict(self):
        errors = validate_telemetry_payload({
            "message_id": "x",
            "device_id": "d",
            "timestamp": "t",
            "metrics": [1, 2, 3],
        })
        self.assertTrue(any("metrics" in e for e in errors))


# ── Integration tests (full pipeline) ────────────────────────────────────────

class IngestionIntegrationBase(TestCase):
    """Creates minimal DB fixtures shared across integration tests."""

    def setUp(self):
        self.site = _make_site("default_demo")
        self.asset = _make_asset(self.site, "charger-001")
        self.device = _make_device(self.site, self.asset, "charger-001")
        self.sensor = _make_sensor(self.device)
        self.m_voltage = _make_metric("voltage_v", "V", DataType.FLOAT)
        self.m_temp = _make_metric("temperature_c", "°C", DataType.FLOAT)
        self.m_current = _make_metric("current_a", "A", DataType.FLOAT)


class ValidTelemetryTest(IngestionIntegrationBase):

    def test_creates_raw_message(self):
        result = process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertTrue(result.success)
        self.assertFalse(result.duplicate)
        self.assertIsNotNone(result.raw_message)
        raw = RawMessage.objects.get(message_id="test-msg-001")
        self.assertEqual(raw.processing_status, ProcessingStatus.PARSED)

    def test_creates_measurements_for_known_metrics(self):
        result = process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertTrue(result.success)
        self.assertEqual(result.measurements_created, 2)  # voltage_v + temperature_c
        self.assertEqual(Measurement.objects.filter(raw_message=result.raw_message).count(), 2)

    def test_measurement_values_stored_correctly(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        m = Measurement.objects.get(
            raw_message__message_id="test-msg-001", metric__key="voltage_v"
        )
        self.assertAlmostEqual(m.value_float, 52.3)
        self.assertEqual(m.unit, "V")
        self.assertEqual(m.quality, "good")

    def test_updates_asset_state(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        state = AssetState.objects.get(asset=self.asset)
        self.assertAlmostEqual(state.last_voltage_v, 52.3)
        self.assertAlmostEqual(state.last_temperature_c, 31.5)
        self.assertEqual(state.status, OperationalStatus.ACTIVE)  # "charging" → active
        self.assertIsNotNone(state.last_seen_at)
        self.assertIsNotNone(state.last_raw_message)

    def test_updates_device_last_seen_at(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen_at)

    def test_updates_device_firmware_version(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.device.refresh_from_db()
        self.assertEqual(self.device.firmware_version, "1.2.3")

    def test_firmware_version_not_overwritten_when_absent(self):
        payload = _demo_payload()
        del payload["firmware_version"]
        process_mqtt_message(DEMO_TOPIC, payload)
        self.device.refresh_from_db()
        self.assertEqual(self.device.firmware_version, "0.0.1")

    def test_raw_message_linked_to_entities(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        raw = RawMessage.objects.get(message_id="test-msg-001")
        self.assertEqual(raw.site, self.site)
        self.assertEqual(raw.device, self.device)
        self.assertEqual(raw.asset, self.asset)

    def test_payload_timestamp_stored(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        raw = RawMessage.objects.get(message_id="test-msg-001")
        self.assertIsNotNone(raw.payload_timestamp)
        self.assertEqual(raw.payload_timestamp.year, 2026)

    def test_asset_state_status_maps_correctly(self):
        for payload_status, expected in [
            ("charging", OperationalStatus.ACTIVE),
            ("warning", OperationalStatus.WARNING),
            ("error", OperationalStatus.ERROR),
            ("offline", OperationalStatus.OFFLINE),
        ]:
            # Reset device to avoid duplicate message_id issues
            self.device.last_seen_at = None
            self.device.save()
            payload = _demo_payload(message_id=f"msg-{payload_status}", status=payload_status)
            process_mqtt_message(DEMO_TOPIC, payload)
            state = AssetState.objects.get(asset=self.asset)
            self.assertEqual(state.status, expected, f"Failed for status='{payload_status}'")

    def test_asset_resolved_via_device_when_no_asset_id_in_payload(self):
        payload = _demo_payload(message_id="msg-no-asset-id")
        del payload["asset_id"]
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(result.success)
        raw = RawMessage.objects.get(message_id="msg-no-asset-id")
        self.assertEqual(raw.asset, self.asset)

    def test_source_type_stored(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload(), source_type="simulator")
        raw = RawMessage.objects.get(message_id="test-msg-001")
        self.assertEqual(raw.source_type, "simulator")

    def test_parser_version_stored(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload(), parser_version="v2")
        raw = RawMessage.objects.get(message_id="test-msg-001")
        self.assertEqual(raw.parser_version, "v2")


class DuplicateMessageTest(IngestionIntegrationBase):

    def test_duplicate_message_id_returns_duplicate_flag(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        result = process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertTrue(result.success)
        self.assertTrue(result.duplicate)

    def test_duplicate_does_not_create_extra_raw_message(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertEqual(RawMessage.objects.filter(message_id="test-msg-001").count(), 1)

    def test_duplicate_does_not_create_extra_measurements(self):
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        count_before = Measurement.objects.count()
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertEqual(Measurement.objects.count(), count_before)


class InvalidTopicTest(IngestionIntegrationBase):

    def test_bad_topic_creates_failed_raw_message(self):
        result = process_mqtt_message("smt/bad/format", _demo_payload())
        self.assertFalse(result.success)
        self.assertIsNotNone(result.raw_message)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_bad_topic_creates_validation_error_event(self):
        process_mqtt_message("smt/bad/format", _demo_payload())
        self.assertTrue(Event.objects.filter(event_type=EventType.VALIDATION_ERROR).exists())

    def test_wrong_prefix_fails(self):
        result = process_mqtt_message("iot/local/default_demo/charger/dev/telemetry", {})
        self.assertFalse(result.success)


class InvalidJsonTest(IngestionIntegrationBase):

    def test_invalid_json_string_fails(self):
        result = process_mqtt_message(DEMO_TOPIC, "not json {{}")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.raw_message)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)
        self.assertNotEqual(result.raw_message.error_message, "")

    def test_invalid_json_creates_ingestion_error_event(self):
        process_mqtt_message(DEMO_TOPIC, "not json")
        self.assertTrue(Event.objects.filter(event_type=EventType.INGESTION_ERROR).exists())

    def test_invalid_json_payload_text_stored(self):
        process_mqtt_message(DEMO_TOPIC, "bad-payload")
        raw = RawMessage.objects.filter(processing_status=ProcessingStatus.FAILED).first()
        self.assertIn("bad-payload", raw.payload_text)


class MissingRequiredFieldTest(IngestionIntegrationBase):

    def test_missing_message_id_fails(self):
        payload = _demo_payload()
        del payload["message_id"]
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_missing_timestamp_fails(self):
        payload = _demo_payload()
        del payload["timestamp"]
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)

    def test_missing_metrics_fails(self):
        payload = _demo_payload()
        del payload["metrics"]
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)

    def test_missing_device_id_fails(self):
        payload = _demo_payload()
        del payload["device_id"]
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)

    def test_missing_required_field_creates_event(self):
        payload = _demo_payload()
        del payload["message_id"]
        process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(Event.objects.filter(event_type=EventType.VALIDATION_ERROR).exists())


class DeviceIdMismatchTest(IngestionIntegrationBase):

    def test_device_id_mismatch_fails(self):
        payload = _demo_payload(device_id="other-device")
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_device_id_mismatch_creates_validation_event(self):
        payload = _demo_payload(device_id="other-device")
        process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(
            Event.objects.filter(
                event_type=EventType.VALIDATION_ERROR,
                title__icontains="mismatch",
            ).exists()
        )


class UnknownEntityTest(IngestionIntegrationBase):

    def test_unknown_site_fails(self):
        topic = "smt/local/nonexistent_site/charger/charger-001/telemetry"
        result = process_mqtt_message(topic, _demo_payload())
        self.assertFalse(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_unknown_site_creates_event(self):
        topic = "smt/local/nonexistent_site/charger/charger-001/telemetry"
        process_mqtt_message(topic, _demo_payload())
        self.assertTrue(Event.objects.filter(event_type=EventType.VALIDATION_ERROR).exists())

    def test_unknown_device_fails(self):
        topic = "smt/local/default_demo/charger/unknown-device/telemetry"
        payload = _demo_payload(device_id="unknown-device", message_id="msg-unknown-dev")
        result = process_mqtt_message(topic, payload)
        self.assertFalse(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_unknown_device_creates_event(self):
        topic = "smt/local/default_demo/charger/unknown-device/telemetry"
        payload = _demo_payload(device_id="unknown-device", message_id="msg-unknown-dev2")
        process_mqtt_message(topic, payload)
        self.assertTrue(Event.objects.filter(event_type=EventType.VALIDATION_ERROR).exists())

    def test_unknown_asset_in_payload_fails(self):
        # Device exists but payload references a non-existent asset code,
        # and the device itself has no assigned asset
        orphan_device = Device.objects.create(
            site=self.site,
            asset=None,
            device_uid="orphan-device",
            name="Orphan Device",
        )
        topic = "smt/local/default_demo/charger/orphan-device/telemetry"
        payload = _demo_payload(
            device_id="orphan-device",
            asset_id="nonexistent-asset",
            message_id="msg-orphan",
        )
        result = process_mqtt_message(topic, payload)
        self.assertFalse(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.FAILED)

    def test_unknown_asset_creates_event(self):
        orphan_device = Device.objects.create(
            site=self.site,
            asset=None,
            device_uid="orphan-device-2",
            name="Orphan Device 2",
        )
        topic = "smt/local/default_demo/charger/orphan-device-2/telemetry"
        payload = _demo_payload(
            device_id="orphan-device-2",
            asset_id="no-such-asset",
            message_id="msg-orphan2",
        )
        process_mqtt_message(topic, payload)
        self.assertTrue(Event.objects.filter(event_type=EventType.VALIDATION_ERROR).exists())

    def test_device_with_no_asset_and_no_payload_asset_id_fails(self):
        orphan_device = Device.objects.create(
            site=self.site, asset=None, device_uid="bare-device", name="Bare"
        )
        topic = "smt/local/default_demo/charger/bare-device/telemetry"
        payload = _demo_payload(device_id="bare-device", message_id="msg-bare")
        del payload["asset_id"]
        result = process_mqtt_message(topic, payload)
        self.assertFalse(result.success)


class UnknownMetricTest(IngestionIntegrationBase):

    def test_unknown_metric_key_creates_warning_event(self):
        payload = _demo_payload(
            message_id="msg-unknown-metric",
            metrics={"voltage_v": 52.3, "unknown_key_xyz": 99.9},
        )
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(result.success)  # known metrics still processed
        self.assertGreater(result.events_created, 0)
        self.assertTrue(
            Event.objects.filter(
                event_type=EventType.VALIDATION_ERROR,
                severity=Severity.WARNING,
                title__icontains="unknown_key_xyz",
            ).exists()
        )

    def test_unknown_metric_does_not_block_known_metrics(self):
        payload = _demo_payload(
            message_id="msg-mixed-metrics",
            metrics={"voltage_v": 52.3, "totally_unknown": 1.0},
        )
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(result.success)
        self.assertEqual(result.measurements_created, 1)  # only voltage_v

    def test_all_unknown_metrics_fails(self):
        payload = _demo_payload(
            message_id="msg-all-unknown",
            metrics={"unknown_a": 1, "unknown_b": 2},
        )
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertFalse(result.success)
        raw = RawMessage.objects.get(message_id="msg-all-unknown")
        self.assertEqual(raw.processing_status, ProcessingStatus.FAILED)


class InvalidMetricValueTest(IngestionIntegrationBase):

    def test_invalid_float_value_creates_warning_event(self):
        payload = _demo_payload(
            message_id="msg-bad-value",
            metrics={"voltage_v": "not-a-number", "temperature_c": 31.5},
        )
        result = process_mqtt_message(DEMO_TOPIC, payload)
        self.assertTrue(result.success)
        self.assertEqual(result.measurements_created, 1)  # temperature_c succeeds
        self.assertTrue(
            Event.objects.filter(
                event_type=EventType.VALIDATION_ERROR,
                severity=Severity.WARNING,
                title__icontains="voltage_v",
            ).exists()
        )


class UnsupportedMessageTypeTest(IngestionIntegrationBase):

    def test_status_message_type_returns_ignored(self):
        topic = "smt/local/default_demo/charger/charger-001/status"
        result = process_mqtt_message(topic, _demo_payload())
        self.assertTrue(result.success)
        self.assertIsNotNone(result.raw_message)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.IGNORED)

    def test_event_message_type_ignored(self):
        topic = "smt/local/default_demo/charger/charger-001/event"
        result = process_mqtt_message(topic, _demo_payload())
        self.assertTrue(result.success)
        self.assertEqual(result.raw_message.processing_status, ProcessingStatus.IGNORED)
        self.assertEqual(result.measurements_created, 0)

    def test_command_message_type_ignored_no_measurements(self):
        topic = "smt/local/default_demo/charger/charger-001/command"
        result = process_mqtt_message(topic, "{}")
        self.assertTrue(result.success)
        self.assertEqual(result.measurements_created, 0)
        self.assertFalse(result.duplicate)


class MetricDataTypeTest(IngestionIntegrationBase):
    """Verify that each DataType is stored in the correct field."""

    def test_integer_metric_stored_in_value_int(self):
        _make_metric("count_n", "", DataType.INTEGER)
        payload = _demo_payload(
            message_id="msg-int",
            metrics={"count_n": 42},
        )
        process_mqtt_message(DEMO_TOPIC, payload)
        m = Measurement.objects.get(raw_message__message_id="msg-int", metric__key="count_n")
        self.assertEqual(m.value_int, 42)
        self.assertIsNone(m.value_float)

    def test_boolean_metric_stored_in_value_bool(self):
        _make_metric("is_online", "", DataType.BOOLEAN)
        payload = _demo_payload(
            message_id="msg-bool",
            metrics={"is_online": True},
        )
        process_mqtt_message(DEMO_TOPIC, payload)
        m = Measurement.objects.get(raw_message__message_id="msg-bool", metric__key="is_online")
        self.assertTrue(m.value_bool)

    def test_string_metric_stored_in_value_text(self):
        _make_metric("mode_str", "", DataType.STRING)
        payload = _demo_payload(
            message_id="msg-str",
            metrics={"mode_str": "charging_fast"},
        )
        process_mqtt_message(DEMO_TOPIC, payload)
        m = Measurement.objects.get(raw_message__message_id="msg-str", metric__key="mode_str")
        self.assertEqual(m.value_text, "charging_fast")


# ── Sensor resolution (SensorMetric) tests ────────────────────────────────────

class ResolveSensorForMetricTest(IngestionIntegrationBase):
    """Exercise ``resolve_sensor_for_metric`` directly."""

    def test_returns_single_sensor_when_one_sensormetric(self):
        SensorMetric.objects.create(sensor=self.sensor, metric=self.m_voltage)
        sensor, warning = resolve_sensor_for_metric(self.device, self.m_voltage)
        self.assertEqual(sensor, self.sensor)
        self.assertEqual(warning, "")

    def test_falls_back_to_only_sensor_with_warning(self):
        sensor, warning = resolve_sensor_for_metric(self.device, self.m_voltage)
        self.assertEqual(sensor, self.sensor)
        self.assertIn("No SensorMetric", warning)
        self.assertIn(self.m_voltage.key, warning)

    def test_no_sensors_returns_none_with_warning(self):
        # Remove the single sensor created by the base setUp.
        self.sensor.delete()
        sensor, warning = resolve_sensor_for_metric(self.device, self.m_voltage)
        self.assertIsNone(sensor)
        self.assertIn("Cannot resolve sensor", warning)

    def test_multiple_sensormetric_picks_first_with_warning(self):
        sensor_b = Sensor.objects.create(
            device=self.device, code="aux", name="Aux Sensor",
        )
        SensorMetric.objects.create(
            sensor=self.sensor, metric=self.m_voltage, sort_order=1,
        )
        SensorMetric.objects.create(
            sensor=sensor_b, metric=self.m_voltage, sort_order=2,
        )
        sensor, warning = resolve_sensor_for_metric(self.device, self.m_voltage)
        self.assertEqual(sensor, self.sensor)
        self.assertIn("Ambiguous", warning)

    def test_never_assigns_sensor_from_other_device(self):
        other_site = _make_site("other_site")
        other_asset = _make_asset(other_site, "other-001")
        other_device = _make_device(other_site, other_asset, "other-001")
        other_sensor = Sensor.objects.create(
            device=other_device, code="main", name="Other Main",
        )
        SensorMetric.objects.create(
            sensor=other_sensor, metric=self.m_voltage,
        )
        # Remove the sensor on self.device so the only SensorMetric in DB
        # belongs to other_device. resolve_sensor_for_metric must NOT use
        # it.
        self.sensor.delete()
        sensor, warning = resolve_sensor_for_metric(self.device, self.m_voltage)
        self.assertIsNone(sensor)
        self.assertNotEqual(sensor, other_sensor)


class IngestionSensorResolutionTest(IngestionIntegrationBase):
    """End-to-end checks that ingestion stores the correct ``Measurement.sensor``."""

    def test_measurement_sensor_from_sensor_metric(self):
        SensorMetric.objects.create(sensor=self.sensor, metric=self.m_voltage)
        SensorMetric.objects.create(sensor=self.sensor, metric=self.m_temp)
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        m = Measurement.objects.get(
            raw_message__message_id="test-msg-001", metric__key="voltage_v",
        )
        self.assertEqual(m.sensor, self.sensor)

    def test_ingestion_creates_sensor_warning_event_when_no_sensormetric(self):
        # No SensorMetric rows exist; single-sensor fallback applies and a
        # validation warning event is recorded so operators see the gap.
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        self.assertTrue(
            Event.objects.filter(
                event_type=EventType.VALIDATION_ERROR,
                severity=Severity.WARNING,
                title__icontains="Sensor mapping warning",
            ).exists()
        )

    def test_ambiguous_mapping_creates_warning_event(self):
        sensor_b = Sensor.objects.create(
            device=self.device, code="aux", name="Aux Sensor",
        )
        SensorMetric.objects.create(
            sensor=self.sensor, metric=self.m_voltage, sort_order=1,
        )
        SensorMetric.objects.create(
            sensor=sensor_b, metric=self.m_voltage, sort_order=2,
        )
        process_mqtt_message(DEMO_TOPIC, _demo_payload())
        warning_events = Event.objects.filter(
            event_type=EventType.VALIDATION_ERROR,
            title__icontains="Sensor mapping warning",
            description__icontains="Ambiguous",
        )
        self.assertTrue(warning_events.exists())


# ── Worker / management-command tests ─────────────────────────────────────────
#
# These tests cover the thin MQTT worker layer. The paho client is fully
# mocked — no live broker is required.

import importlib
import logging
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.mqtt_ingestion.results import IngestionResult
from apps.mqtt_ingestion.worker import MqttIngestionWorker, MqttWorkerConfig


class _StubMqttClient:
    """Stand-in for paho.mqtt.client.Client used in worker tests."""

    def __init__(self, client_id=None, **_kwargs):
        self.client_id = client_id
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.subscriptions: list = []
        self.connect_calls: list = []
        self.username = None
        self.password = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def username_pw_set(self, username, password=None):
        self.username = username
        self.password = password

    def connect(self, host, port, keepalive):
        self.connect_calls.append((host, port, keepalive))

    def subscribe(self, topic):
        self.subscriptions.append(topic)
        return (0, 1)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def loop_forever(self):
        pass

    # Test helpers (not part of paho API)
    def fire_on_connect(self, rc=0):
        self.on_connect(self, None, {}, SimpleNamespace(value=rc))

    def fire_on_message(self, topic, payload):
        msg = SimpleNamespace(topic=topic, payload=payload)
        self.on_message(self, None, msg)


def _make_config(**overrides) -> MqttWorkerConfig:
    return MqttWorkerConfig(
        host=overrides.get("host", "mqtt.local"),
        port=overrides.get("port", 1883),
        keepalive=overrides.get("keepalive", 60),
        client_id=overrides.get("client_id", "test-client"),
        topics=overrides.get("topics", ["smt/+/+/+/+/telemetry"]),
        username=overrides.get("username", ""),
        password=overrides.get("password", ""),
    )


class MqttWorkerConfigTest(SimpleTestCase):

    def test_redacted_hides_password(self):
        cfg = _make_config(username="u", password="secret")
        self.assertEqual(cfg.redacted()["password"], "***")
        self.assertNotIn("secret", str(cfg.redacted()))

    def test_redacted_blank_password_stays_blank(self):
        cfg = _make_config()
        self.assertEqual(cfg.redacted()["password"], "")

    @override_settings(
        MQTT_HOST="h", MQTT_PORT=2222, MQTT_KEEPALIVE_SECONDS=15,
        MQTT_CLIENT_ID="cid", MQTT_USERNAME="u", MQTT_PASSWORD="p",
        MQTT_SUBSCRIBE_TOPICS=["a/#"],
    )
    def test_from_settings_uses_settings(self):
        cfg = MqttWorkerConfig.from_settings()
        self.assertEqual(cfg.host, "h")
        self.assertEqual(cfg.port, 2222)
        self.assertEqual(cfg.keepalive, 15)
        self.assertEqual(cfg.client_id, "cid")
        self.assertEqual(cfg.topics, ["a/#"])
        self.assertEqual(cfg.username, "u")
        self.assertEqual(cfg.password, "p")

    @override_settings(MQTT_SUBSCRIBE_TOPICS=["default/#"])
    def test_from_settings_overrides_topics(self):
        cfg = MqttWorkerConfig.from_settings(topics=["override/#"])
        self.assertEqual(cfg.topics, ["override/#"])


class MqttWorkerConnectionTest(SimpleTestCase):

    def _build_worker(self, client, **cfg_kwargs):
        return MqttIngestionWorker(
            config=_make_config(**cfg_kwargs),
            client_factory=lambda cid: client,
            process_message=MagicMock(),
        )

    def test_connect_calls_paho_connect(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub, host="broker", port=1234, keepalive=30)
        worker.connect()
        self.assertEqual(stub.connect_calls, [("broker", 1234, 30)])

    def test_callbacks_wired(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub)
        worker.build_client()
        # Bound methods compare equal but are not the same identity object,
        # so use assertEqual not assertIs.
        self.assertEqual(stub.on_connect, worker._on_connect)
        self.assertEqual(stub.on_message, worker._on_message)
        self.assertEqual(stub.on_disconnect, worker._on_disconnect)

    def test_on_connect_subscribes_to_all_topics(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub, topics=["t/a", "t/b", "t/c"])
        worker.build_client()
        stub.fire_on_connect(rc=0)
        self.assertEqual(stub.subscriptions, ["t/a", "t/b", "t/c"])

    def test_on_connect_failure_does_not_subscribe(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub, topics=["t/a"])
        worker.build_client()
        stub.fire_on_connect(rc=4)  # bad credentials
        self.assertEqual(stub.subscriptions, [])

    def test_authentication_applied_when_username_set(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub, username="user1", password="pw1")
        worker.build_client()
        self.assertEqual(stub.username, "user1")
        self.assertEqual(stub.password, "pw1")

    def test_authentication_skipped_when_username_blank(self):
        stub = _StubMqttClient()
        worker = self._build_worker(stub, username="", password="")
        worker.build_client()
        self.assertIsNone(stub.username)


class MqttWorkerMessageHandlingTest(SimpleTestCase):

    def _make_worker(self, processor):
        stub = _StubMqttClient()
        worker = MqttIngestionWorker(
            config=_make_config(),
            client_factory=lambda cid: stub,
            process_message=processor,
        )
        worker.build_client()
        return worker, stub

    def test_on_message_calls_process_with_topic_and_decoded_payload(self):
        captured = {}
        def fake(topic, payload, *, source_type):
            captured["topic"] = topic
            captured["payload"] = payload
            captured["source_type"] = source_type
            return IngestionResult(success=True)
        worker, stub = self._make_worker(fake)
        stub.fire_on_message("smt/local/d/charger/c1/telemetry", b'{"x": 1}')
        self.assertEqual(captured["topic"], "smt/local/d/charger/c1/telemetry")
        self.assertEqual(captured["payload"], '{"x": 1}')
        self.assertEqual(captured["source_type"], "mqtt")

    def test_success_result_updates_stats(self):
        processor = MagicMock(return_value=IngestionResult(
            success=True, measurements_created=3, events_created=0
        ))
        worker, stub = self._make_worker(processor)
        stub.fire_on_message("t", b"{}")
        self.assertEqual(worker.stats.messages_processed, 1)
        self.assertEqual(worker.stats.failures, 0)
        self.assertEqual(worker.stats.duplicates, 0)

    def test_duplicate_result_counts_as_duplicate(self):
        processor = MagicMock(return_value=IngestionResult(success=True, duplicate=True))
        worker, stub = self._make_worker(processor)
        stub.fire_on_message("t", b"{}")
        self.assertEqual(worker.stats.duplicates, 1)
        self.assertEqual(worker.stats.messages_processed, 1)

    def test_failure_result_counts_as_failure(self):
        processor = MagicMock(return_value=IngestionResult(success=False, errors=["bad"]))
        worker, stub = self._make_worker(processor)
        stub.fire_on_message("t", b"{}")
        self.assertEqual(worker.stats.failures, 1)

    def test_unexpected_exception_is_caught(self):
        processor = MagicMock(side_effect=RuntimeError("boom"))
        worker, stub = self._make_worker(processor)
        # Should NOT raise
        stub.fire_on_message("t", b"{}")
        self.assertEqual(worker.stats.unexpected_exceptions, 1)

    def test_first_message_event_set_after_message(self):
        processor = MagicMock(return_value=IngestionResult(success=True))
        worker, stub = self._make_worker(processor)
        self.assertFalse(worker._first_message_event.is_set())
        stub.fire_on_message("t", b"{}")
        self.assertTrue(worker._first_message_event.is_set())

    def test_first_message_event_set_even_on_exception(self):
        processor = MagicMock(side_effect=RuntimeError("boom"))
        worker, stub = self._make_worker(processor)
        stub.fire_on_message("t", b"{}")
        self.assertTrue(worker._first_message_event.is_set())

    def test_payload_decoded_with_replacement_on_bad_utf8(self):
        captured = {}
        def fake(topic, payload, *, source_type):
            captured["payload"] = payload
            return IngestionResult(success=True)
        worker, stub = self._make_worker(fake)
        stub.fire_on_message("t", b"\xff\xfe-bad")
        # Worker should not crash; payload is a string with replacement chars
        self.assertIsInstance(captured["payload"], str)


class MqttWorkerRunOnceTest(SimpleTestCase):

    def test_run_once_returns_true_when_message_arrives(self):
        stub = _StubMqttClient()
        processor = MagicMock(return_value=IngestionResult(success=True))
        worker = MqttIngestionWorker(
            config=_make_config(),
            client_factory=lambda cid: stub,
            process_message=processor,
        )
        # Pre-set the event so run_once returns immediately
        worker._first_message_event.set()
        result = worker.run_once(timeout_seconds=0.1)
        self.assertTrue(result)
        self.assertTrue(stub.loop_started)
        self.assertTrue(stub.disconnected)

    def test_run_once_returns_false_on_timeout(self):
        stub = _StubMqttClient()
        worker = MqttIngestionWorker(
            config=_make_config(),
            client_factory=lambda cid: stub,
            process_message=MagicMock(),
        )
        result = worker.run_once(timeout_seconds=0.05)
        self.assertFalse(result)
        self.assertTrue(stub.disconnected)


class RunMqttWorkerCommandTest(SimpleTestCase):

    def test_command_module_importable(self):
        module = importlib.import_module(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker"
        )
        self.assertTrue(hasattr(module, "Command"))

    def test_topic_argument_parsing(self):
        from apps.mqtt_ingestion.management.commands.run_mqtt_worker import Command
        self.assertIsNone(Command._resolve_topics(None))
        self.assertEqual(Command._resolve_topics(["a", "b"]), ["a", "b"])
        self.assertEqual(Command._resolve_topics(["a,b,c"]), ["a", "b", "c"])
        self.assertEqual(Command._resolve_topics(["a, b", "c"]), ["a", "b", "c"])

    def test_once_mode_success(self):
        instance = MagicMock()
        instance.run_once.return_value = True
        with patch(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker.MqttIngestionWorker",
            return_value=instance,
        ):
            out = StringIO()
            call_command("run_mqtt_worker", "--once", "--timeout-seconds", "1", stdout=out)
        instance.run_once.assert_called_once_with(timeout_seconds=1.0)
        self.assertIn("message processed successfully", out.getvalue())

    def test_once_mode_timeout_raises_command_error(self):
        instance = MagicMock()
        instance.run_once.return_value = False
        with patch(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker.MqttIngestionWorker",
            return_value=instance,
        ):
            with self.assertRaises(CommandError):
                call_command("run_mqtt_worker", "--once", "--timeout-seconds", "1")

    def test_topic_override_passed_to_worker(self):
        captured = {}

        def fake_worker(*, config):
            captured["topics"] = config.topics
            instance = MagicMock()
            instance.run_once.return_value = True
            return instance

        with patch(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker.MqttIngestionWorker",
            side_effect=fake_worker,
        ):
            call_command(
                "run_mqtt_worker",
                "--once",
                "--topic", "smt/x/+/+/+/telemetry",
                "--topic", "smt/y/+/+/+/telemetry",
                "--timeout-seconds", "1",
                stdout=StringIO(),
            )
        self.assertEqual(
            captured["topics"],
            ["smt/x/+/+/+/telemetry", "smt/y/+/+/+/telemetry"],
        )

    def test_client_id_override_passed_to_worker(self):
        captured = {}

        def fake_worker(*, config):
            captured["client_id"] = config.client_id
            instance = MagicMock()
            instance.run_once.return_value = True
            return instance

        with patch(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker.MqttIngestionWorker",
            side_effect=fake_worker,
        ):
            call_command(
                "run_mqtt_worker",
                "--once",
                "--client-id", "my-custom-id",
                "--timeout-seconds", "1",
                stdout=StringIO(),
            )
        self.assertEqual(captured["client_id"], "my-custom-id")

    def test_connection_failure_raises_command_error(self):
        instance = MagicMock()
        instance.run_once.side_effect = OSError("Connection refused")
        with patch(
            "apps.mqtt_ingestion.management.commands.run_mqtt_worker.MqttIngestionWorker",
            return_value=instance,
        ):
            with self.assertRaises(CommandError):
                call_command("run_mqtt_worker", "--once", "--timeout-seconds", "1")


# ── Threshold analytics integration tests ────────────────────────────────────

class IngestionThresholdAnalyticsTest(IngestionIntegrationBase):
    """
    Verifies that process_mqtt_message triggers the analytics threshold
    service after Measurement persistence, creates threshold_anomaly Events
    on violations, and closes them when values return to normal.
    """

    def setUp(self):
        super().setUp()
        from apps.analytics.models import ThresholdRule, ThresholdRuleScope
        # Explicit global scope keeps the integration scenario focused on
        # ingestion → analytics wiring rather than scope semantics; see
        # apps.analytics.tests for per-scope coverage.
        ThresholdRule.objects.create(
            code="temperature_c_high_warning",
            name="High temperature",
            metric=self.m_temp,
            scope_level=ThresholdRuleScope.GLOBAL,
            upper_bound=60.0,
            severity="warning",
            is_enabled=True,
            close_when_normal=True,
        )

    def _payload_with_temp(self, temperature: float, *, message_id: str) -> dict:
        return {
            "message_id": message_id,
            "device_id": "charger-001",
            "asset_id": "charger-001",
            "timestamp": "2026-05-16T10:00:00Z",
            "metrics": {
                "voltage_v": 52.3,
                "temperature_c": temperature,
            },
            "status": "charging",
            "firmware_version": "1.2.3",
        }

    def test_normal_telemetry_does_not_create_threshold_anomaly(self):
        from apps.events.models import Event, EventType
        result = process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(30.0, message_id="t-normal-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.analytics_events_created, 0)
        self.assertEqual(
            Event.objects.filter(event_type=EventType.THRESHOLD_ANOMALY).count(), 0,
        )

    def test_high_temperature_creates_threshold_anomaly(self):
        from apps.events.models import Event, EventStatus, EventType
        result = process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(75.0, message_id="t-high-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.analytics_events_created, 1)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        self.assertEqual(ev.status, EventStatus.OPEN)
        self.assertEqual(ev.payload["rule_code"], "temperature_c_high_warning")
        self.assertEqual(ev.payload["value"], 75.0)
        self.assertEqual(ev.payload["upper_bound"], 60.0)

    def test_returning_to_normal_closes_open_anomaly(self):
        from apps.events.models import Event, EventStatus, EventType
        process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(75.0, message_id="t-high-1"),
        )
        self.assertEqual(
            Event.objects.filter(
                event_type=EventType.THRESHOLD_ANOMALY,
                status=EventStatus.OPEN,
            ).count(),
            1,
        )

        process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(30.0, message_id="t-normal-1"),
        )
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        self.assertEqual(ev.status, EventStatus.CLOSED)
        self.assertIsNotNone(ev.closed_at)

    def test_repeated_high_telemetry_keeps_single_open_anomaly(self):
        from apps.events.models import Event, EventStatus, EventType
        process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(75.0, message_id="t-high-1"),
        )
        process_mqtt_message(
            DEMO_TOPIC, self._payload_with_temp(80.0, message_id="t-high-2"),
        )
        self.assertEqual(
            Event.objects.filter(
                event_type=EventType.THRESHOLD_ANOMALY,
                status=EventStatus.OPEN,
            ).count(),
            1,
        )

    def test_analytics_failure_does_not_break_telemetry_persistence(self):
        """
        If the threshold service raises mid-way, telemetry must still be
        committed and the IngestionResult must report the analytics error
        in ``errors`` while keeping ``success=True``.
        """
        from apps.events.models import Event, EventType

        with patch(
            "apps.analytics.services.thresholds.evaluate_measurements_thresholds",
            side_effect=RuntimeError("analytics blew up"),
        ):
            result = process_mqtt_message(
                DEMO_TOPIC,
                self._payload_with_temp(75.0, message_id="t-analytics-fail-1"),
            )

        self.assertTrue(result.success)
        self.assertEqual(result.measurements_created, 2)
        self.assertTrue(any("analytics blew up" in e for e in result.errors))
        # No threshold_anomaly created (analytics failed) but telemetry was persisted.
        self.assertEqual(
            Event.objects.filter(event_type=EventType.THRESHOLD_ANOMALY).count(), 0,
        )
        self.assertEqual(Measurement.objects.count(), 2)
        # An ingestion_error event was recorded for the analytics failure.
        self.assertEqual(
            Event.objects.filter(event_type=EventType.INGESTION_ERROR).count(), 1,
        )
