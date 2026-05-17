"""
Tests for the analytics threshold rule model and evaluation service.

All tests run against the SQLite test database:
    python manage.py test apps.analytics --settings=config.settings.test

No live MQTT broker is required.
"""

import datetime

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import ThresholdRule
from apps.analytics.services.thresholds import (
    ANALYTICS_SOURCE,
    evaluate_measurement_thresholds,
    evaluate_measurements_thresholds,
)
from apps.assets.models import Asset, AssetType, Device, Sensor, Site
from apps.core.models import DataType
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.iot_config.models import MetricDefinition
from apps.telemetry.models import Measurement, MeasurementQuality, RawMessage, SourceType


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _make_site(code="default_demo"):
    return Site.objects.create(code=code, name=f"Site {code}")


def _make_asset(site, code="charger-001", asset_type=AssetType.CHARGER):
    return Asset.objects.create(
        site=site, code=code, name=f"Asset {code}", asset_type=asset_type
    )


def _make_device(site, asset, uid="charger-001"):
    return Device.objects.create(
        site=site,
        asset=asset,
        device_uid=uid,
        name=f"Device {uid}",
        device_type="charger",
        is_simulated=True,
    )


def _make_sensor(device, code="main"):
    return Sensor.objects.create(device=device, code=code, name="Main Sensor")


def _make_metric(key="temperature_c", unit="°C", data_type=DataType.FLOAT):
    return MetricDefinition.objects.create(
        key=key, display_name=key, unit=unit, data_type=data_type,
    )


def _make_raw_message(site, asset, device, message_id="raw-1"):
    return RawMessage.objects.create(
        source_type=SourceType.MQTT,
        topic="smt/dev/default_demo/charger/charger-001/telemetry",
        payload={"message_id": message_id},
        message_id=message_id,
        device_uid=device.device_uid,
        site=site,
        asset=asset,
        device=device,
        received_at=timezone.now(),
    )


def _make_measurement(
    *,
    site,
    asset,
    device,
    metric,
    raw_message=None,
    value_float=None,
    value_int=None,
    value_bool=None,
    value_text="",
    sensor=None,
    timestamp=None,
):
    return Measurement.objects.create(
        site=site,
        asset=asset,
        device=device,
        sensor=sensor,
        metric=metric,
        raw_message=raw_message,
        timestamp=timestamp or timezone.now(),
        value_float=value_float,
        value_int=value_int,
        value_bool=value_bool,
        value_text=value_text,
        unit=metric.unit,
        quality=MeasurementQuality.GOOD,
    )


def _make_rule(metric, *, code="t_high", upper=None, lower=None, **kwargs):
    rule_kwargs = {
        "code": code,
        "name": code,
        "metric": metric,
        "lower_bound": lower,
        "upper_bound": upper,
        "severity": Severity.WARNING,
        "is_enabled": True,
        "close_when_normal": True,
    }
    rule_kwargs.update(kwargs)
    return ThresholdRule.objects.create(**rule_kwargs)


# ── Model tests ───────────────────────────────────────────────────────────────

class ThresholdRuleModelTest(TestCase):

    def setUp(self):
        self.metric = _make_metric()

    def test_create_rule(self):
        rule = _make_rule(self.metric, code="r1", upper=60.0)
        self.assertEqual(rule.code, "r1")
        self.assertEqual(rule.metric, self.metric)
        self.assertEqual(rule.upper_bound, 60.0)
        self.assertIsNone(rule.lower_bound)
        self.assertTrue(rule.is_enabled)
        self.assertTrue(rule.close_when_normal)

    def test_str_includes_code_and_metric_key(self):
        rule = _make_rule(self.metric, code="r1", upper=60.0)
        s = str(rule)
        self.assertIn("r1", s)
        self.assertIn("temperature_c", s)

    def test_rule_requires_at_least_one_bound(self):
        with self.assertRaises(ValidationError):
            ThresholdRule.objects.create(
                code="r_no_bounds",
                name="no bounds",
                metric=self.metric,
                lower_bound=None,
                upper_bound=None,
                severity=Severity.WARNING,
            )

    def test_rule_rejects_inverted_bounds(self):
        with self.assertRaises(ValidationError):
            ThresholdRule.objects.create(
                code="r_inverted",
                name="inverted",
                metric=self.metric,
                lower_bound=80.0,
                upper_bound=20.0,
                severity=Severity.WARNING,
            )

    def test_unique_code(self):
        _make_rule(self.metric, code="dup", upper=60.0)
        with self.assertRaises(Exception):
            _make_rule(self.metric, code="dup", upper=70.0)


# ── Service tests: rule applicability filtering ──────────────────────────────

class ThresholdServiceApplicabilityTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.other_site = _make_site(code="other_site")
        self.asset = _make_asset(self.site)
        self.other_asset = _make_asset(self.other_site, code="charger-002")
        self.device = _make_device(self.site, self.asset, uid="charger-001")
        self.other_device = _make_device(self.other_site, self.other_asset, uid="charger-002")
        self.metric = _make_metric()
        self._rm_counter = 0

    def _next_raw_message(self, site, asset, device):
        self._rm_counter += 1
        return _make_raw_message(
            site, asset, device, message_id=f"app-rm-{self._rm_counter}",
        )

    def _make_measurement_for(self, site, asset, device):
        rm = self._next_raw_message(site, asset, device)
        return _make_measurement(
            site=site, asset=asset, device=device,
            metric=self.metric, raw_message=rm, value_float=99.0,
        )

    def test_global_rule_applies_to_any_matching_metric(self):
        _make_rule(self.metric, code="g", upper=60.0)
        m = self._make_measurement_for(self.site, self.asset, self.device)
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.rules_checked, 1)
        self.assertEqual(result.events_created, 1)

    def test_site_specific_rule_only_applies_to_matching_site(self):
        _make_rule(self.metric, code="s", upper=60.0, site=self.site)
        # Measurement on the OTHER site — rule should not apply.
        m_other = self._make_measurement_for(
            self.other_site, self.other_asset, self.other_device,
        )
        result = evaluate_measurement_thresholds(m_other)
        self.assertEqual(result.rules_checked, 0)
        self.assertEqual(result.events_created, 0)

    def test_asset_specific_rule_only_applies_to_matching_asset(self):
        _make_rule(self.metric, code="a", upper=60.0, asset=self.asset)
        m_other = self._make_measurement_for(
            self.other_site, self.other_asset, self.other_device,
        )
        self.assertEqual(evaluate_measurement_thresholds(m_other).rules_checked, 0)

        m_match = self._make_measurement_for(self.site, self.asset, self.device)
        self.assertEqual(evaluate_measurement_thresholds(m_match).events_created, 1)

    def test_device_specific_rule_only_applies_to_matching_device(self):
        _make_rule(self.metric, code="d", upper=60.0, device=self.device)
        m_other = self._make_measurement_for(
            self.other_site, self.other_asset, self.other_device,
        )
        self.assertEqual(evaluate_measurement_thresholds(m_other).rules_checked, 0)

        m_match = self._make_measurement_for(self.site, self.asset, self.device)
        self.assertEqual(evaluate_measurement_thresholds(m_match).events_created, 1)

    def test_disabled_rule_is_not_evaluated(self):
        _make_rule(self.metric, code="off", upper=60.0, is_enabled=False)
        m = self._make_measurement_for(self.site, self.asset, self.device)
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.rules_checked, 0)
        self.assertEqual(result.events_created, 0)


# ── Service tests: violation, normal, dedup, close ───────────────────────────

class ThresholdServiceEvaluationTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.device = _make_device(self.site, self.asset)
        self.sensor = _make_sensor(self.device)
        self.metric_temp = _make_metric(key="temperature_c", unit="°C")
        self.metric_soc = _make_metric(key="battery_soc_pct", unit="%")
        self.rm = _make_raw_message(self.site, self.asset, self.device)

    def test_value_above_upper_bound_creates_open_event(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.events_created, 1)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        self.assertEqual(ev.status, EventStatus.OPEN)
        self.assertEqual(ev.severity, Severity.WARNING)
        self.assertEqual(ev.source, ANALYTICS_SOURCE)
        self.assertEqual(ev.metric, self.metric_temp)
        self.assertEqual(ev.asset, self.asset)
        self.assertEqual(ev.device, self.device)
        self.assertEqual(ev.measurement, m)
        self.assertEqual(ev.raw_message, self.rm)

    def test_value_below_lower_bound_creates_open_event(self):
        _make_rule(self.metric_soc, code="soc_low", lower=20.0)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_soc, raw_message=self.rm, value_float=15.0,
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.events_created, 1)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        self.assertEqual(ev.status, EventStatus.OPEN)

    def test_value_within_bounds_creates_no_event(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=30.0,
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.events_created, 0)
        self.assertEqual(Event.objects.count(), 0)

    def test_boolean_measurement_is_skipped_safely(self):
        bool_metric = _make_metric(key="charging_flag", data_type=DataType.BOOLEAN)
        _make_rule(bool_metric, code="b", upper=0.5)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=bool_metric, raw_message=self.rm, value_bool=True,
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.rules_checked, 0)
        self.assertEqual(result.events_created, 0)

    def test_text_measurement_is_skipped_safely(self):
        text_metric = _make_metric(key="state_text", data_type=DataType.STRING)
        _make_rule(text_metric, code="s", upper=0.5)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=text_metric, raw_message=self.rm, value_text="charging",
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.rules_checked, 0)
        self.assertEqual(result.events_created, 0)

    def test_missing_value_is_skipped_safely(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm,
            # no value_float / value_int / value_bool / value_text
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.rules_checked, 0)
        self.assertEqual(result.events_created, 0)

    def test_int_measurement_is_evaluated(self):
        int_metric = _make_metric(key="cell_count", data_type=DataType.INTEGER)
        _make_rule(int_metric, code="cells_low", lower=4)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=int_metric, raw_message=self.rm, value_int=2,
        )
        result = evaluate_measurement_thresholds(m)
        self.assertEqual(result.events_created, 1)

    # ── De-duplication ───────────────────────────────────────────────────────

    def test_repeated_violation_does_not_create_duplicate_open_event(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m1 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
        )
        evaluate_measurement_thresholds(m1)

        rm2 = _make_raw_message(
            self.site, self.asset, self.device, message_id="raw-2",
        )
        m2 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=rm2, value_float=80.0,
        )
        result = evaluate_measurement_thresholds(m2)

        self.assertEqual(result.events_created, 0)
        self.assertEqual(result.events_updated, 1)
        self.assertEqual(
            Event.objects.filter(
                event_type=EventType.THRESHOLD_ANOMALY,
                status=EventStatus.OPEN,
            ).count(),
            1,
        )

    def test_repeated_violation_updates_open_event_in_place(self):
        rule = _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m1 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
        )
        evaluate_measurement_thresholds(m1)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        original_detected_at = ev.detected_at

        rm2 = _make_raw_message(
            self.site, self.asset, self.device, message_id="raw-2",
        )
        m2 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=rm2, value_float=82.0,
        )
        evaluate_measurement_thresholds(m2)

        ev.refresh_from_db()
        # detected_at preserved.
        self.assertEqual(ev.detected_at, original_detected_at)
        # Latest measurement and value reflected in the event.
        self.assertEqual(ev.measurement, m2)
        self.assertEqual(ev.payload["value"], 82.0)
        self.assertEqual(ev.payload["measurement_id"], str(m2.id))
        self.assertEqual(ev.payload["rule_code"], rule.code)

    # ── Closing on return-to-normal ──────────────────────────────────────────

    def test_open_event_closes_when_value_returns_to_normal(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        m1 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
        )
        evaluate_measurement_thresholds(m1)
        self.assertEqual(
            Event.objects.filter(status=EventStatus.OPEN).count(), 1,
        )

        rm2 = _make_raw_message(
            self.site, self.asset, self.device, message_id="raw-2",
        )
        m2 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=rm2, value_float=30.0,
        )
        result = evaluate_measurement_thresholds(m2)

        self.assertEqual(result.events_closed, 1)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        self.assertEqual(ev.status, EventStatus.CLOSED)
        self.assertIsNotNone(ev.closed_at)

    def test_open_event_is_not_closed_when_close_when_normal_false(self):
        _make_rule(
            self.metric_temp, code="t_high", upper=60.0,
            close_when_normal=False,
        )
        m1 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
        )
        evaluate_measurement_thresholds(m1)

        rm2 = _make_raw_message(
            self.site, self.asset, self.device, message_id="raw-2",
        )
        m2 = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=rm2, value_float=30.0,
        )
        result = evaluate_measurement_thresholds(m2)

        self.assertEqual(result.events_closed, 0)
        self.assertEqual(
            Event.objects.filter(status=EventStatus.OPEN).count(), 1,
        )

    # ── Payload contents ─────────────────────────────────────────────────────

    def test_event_payload_contains_required_diagnostic_fields(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0, lower=10.0)
        m = _make_measurement(
            site=self.site, asset=self.asset, device=self.device,
            metric=self.metric_temp, raw_message=self.rm, value_float=99.0,
        )
        evaluate_measurement_thresholds(m)
        ev = Event.objects.get(event_type=EventType.THRESHOLD_ANOMALY)
        for field in (
            "rule_code", "metric_key", "value", "lower_bound",
            "upper_bound", "measurement_id",
        ):
            self.assertIn(field, ev.payload)
        self.assertEqual(ev.payload["rule_code"], "t_high")
        self.assertEqual(ev.payload["metric_key"], "temperature_c")
        self.assertEqual(ev.payload["value"], 99.0)
        self.assertEqual(ev.payload["upper_bound"], 60.0)
        self.assertEqual(ev.payload["lower_bound"], 10.0)
        self.assertEqual(ev.payload["measurement_id"], str(m.id))

    def test_evaluate_measurements_plural_aggregates_results(self):
        _make_rule(self.metric_temp, code="t_high", upper=60.0)
        rm2 = _make_raw_message(self.site, self.asset, self.device, message_id="r2")
        rm3 = _make_raw_message(self.site, self.asset, self.device, message_id="r3")
        ms = [
            _make_measurement(  # violates → creates
                site=self.site, asset=self.asset, device=self.device,
                metric=self.metric_temp, raw_message=self.rm, value_float=75.0,
            ),
            _make_measurement(  # violates again → updates
                site=self.site, asset=self.asset, device=self.device,
                metric=self.metric_temp, raw_message=rm2, value_float=80.0,
            ),
            _make_measurement(  # normal → closes
                site=self.site, asset=self.asset, device=self.device,
                metric=self.metric_temp, raw_message=rm3, value_float=30.0,
            ),
        ]
        result = evaluate_measurements_thresholds(ms)
        self.assertEqual(result.events_created, 1)
        self.assertEqual(result.events_updated, 1)
        self.assertEqual(result.events_closed, 1)


# ── seed_demo_data idempotency ───────────────────────────────────────────────

class SeedDemoDataThresholdRuleTest(TestCase):

    def test_seed_creates_demo_threshold_rules(self):
        call_command("seed_demo_data", verbosity=0)
        self.assertTrue(
            ThresholdRule.objects.filter(code="temperature_c_high_warning").exists()
        )
        self.assertTrue(
            ThresholdRule.objects.filter(code="temperature_c_high_error").exists()
        )
        self.assertTrue(
            ThresholdRule.objects.filter(code="battery_soc_low_warning").exists()
        )

    def test_seed_threshold_rules_are_idempotent(self):
        call_command("seed_demo_data", verbosity=0)
        call_command("seed_demo_data", verbosity=0)
        self.assertEqual(
            ThresholdRule.objects.filter(code="temperature_c_high_warning").count(), 1,
        )
        self.assertEqual(
            ThresholdRule.objects.filter(code__startswith="temperature_c_high").count(),
            2,
        )


# ── Communication-timeout fixtures and helpers ───────────────────────────────

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import override_settings

from apps.analytics.services.communication_timeouts import (
    DEVICE_STATUS_NEVER_SEEN,
    DEVICE_STATUS_OK,
    DEVICE_STATUS_SKIPPED,
    DEVICE_STATUS_TIMED_OUT,
    check_all_device_communication_timeouts,
    check_device_communication_timeout,
    close_communication_timeout_for_device,
)
from apps.core.models import OperationalStatus
from apps.digital_twin.models import AssetState


def _make_device_with_interval(
    site, asset, *, uid="charger-001", interval=60, last_seen_at=None, is_active=True,
):
    return Device.objects.create(
        site=site,
        asset=asset,
        device_uid=uid,
        name=f"Device {uid}",
        device_type="charger",
        is_simulated=True,
        is_active=is_active,
        expected_interval_seconds=interval,
        last_seen_at=last_seen_at,
    )


def _make_assetstate(asset, site, device, **overrides):
    defaults = dict(
        asset=asset, site=site, device=device,
        status=OperationalStatus.UNKNOWN,
        last_seen_at=None,
        active_anomaly_count=0,
        has_active_anomaly=False,
    )
    defaults.update(overrides)
    return AssetState.objects.create(**defaults)


# ── Service: timeout detection ───────────────────────────────────────────────

class CommunicationTimeoutServiceTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.now = timezone.now()

    def test_recent_last_seen_creates_no_event(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(seconds=30),
        )
        result = check_device_communication_timeout(device, now=self.now)

        self.assertEqual(result.devices_checked, 1)
        self.assertEqual(result.timeouts_created, 0)
        self.assertEqual(result.devices_ok, 1)
        self.assertEqual(result.device_records[0].status, DEVICE_STATUS_OK)
        self.assertEqual(
            Event.objects.filter(event_type=EventType.COMMUNICATION_TIMEOUT).count(), 0,
        )

    def test_old_last_seen_creates_open_event(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )
        result = check_device_communication_timeout(device, now=self.now)

        self.assertEqual(result.timeouts_created, 1)
        ev = Event.objects.get(event_type=EventType.COMMUNICATION_TIMEOUT)
        self.assertEqual(ev.status, EventStatus.OPEN)
        self.assertEqual(ev.severity, Severity.WARNING)
        self.assertEqual(ev.source, "analytics")
        self.assertEqual(ev.device, device)
        self.assertEqual(ev.asset, self.asset)
        self.assertEqual(ev.site, self.site)
        self.assertIn("device_uid", ev.payload)
        self.assertEqual(ev.payload["device_uid"], device.device_uid)
        self.assertEqual(ev.payload["expected_interval_seconds"], 60)
        self.assertIn("timeout_seconds", ev.payload)
        self.assertIn("checked_at", ev.payload)

    def test_repeated_check_updates_open_event_in_place(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )
        check_device_communication_timeout(device, now=self.now)
        ev = Event.objects.get(event_type=EventType.COMMUNICATION_TIMEOUT)
        original_detected_at = ev.detected_at

        later = self.now + timedelta(minutes=5)
        result = check_device_communication_timeout(device, now=later)

        self.assertEqual(result.timeouts_created, 0)
        self.assertEqual(result.timeouts_updated, 1)
        ev.refresh_from_db()
        self.assertEqual(ev.detected_at, original_detected_at)
        self.assertEqual(
            Event.objects.filter(
                event_type=EventType.COMMUNICATION_TIMEOUT,
                status=EventStatus.OPEN,
            ).count(),
            1,
        )

    def test_recovery_closes_open_event(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )
        check_device_communication_timeout(device, now=self.now)

        device.last_seen_at = self.now + timedelta(seconds=10)
        device.save(update_fields=["last_seen_at"])

        result = check_device_communication_timeout(
            device, now=self.now + timedelta(seconds=15),
        )
        self.assertEqual(result.timeouts_closed, 1)
        ev = Event.objects.get(event_type=EventType.COMMUNICATION_TIMEOUT)
        self.assertEqual(ev.status, EventStatus.CLOSED)
        self.assertIsNotNone(ev.closed_at)

    def test_inactive_device_is_skipped(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30), is_active=False,
        )
        result = check_device_communication_timeout(device, now=self.now)
        self.assertEqual(result.devices_skipped, 1)
        self.assertEqual(result.timeouts_created, 0)
        self.assertEqual(result.device_records[0].skip_reason, "device_inactive")

    def test_device_without_asset_is_skipped(self):
        device = Device.objects.create(
            site=self.site, asset=None,
            device_uid="orphan-1", name="orphan",
            expected_interval_seconds=60,
            last_seen_at=self.now - timedelta(minutes=30),
        )
        result = check_device_communication_timeout(device, now=self.now)
        self.assertEqual(result.devices_skipped, 1)
        self.assertEqual(result.timeouts_created, 0)

    def test_never_seen_active_device_creates_open_event(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=None,
        )
        result = check_device_communication_timeout(device, now=self.now)

        self.assertEqual(result.timeouts_created, 1)
        self.assertEqual(result.device_records[0].status, DEVICE_STATUS_NEVER_SEEN)
        ev = Event.objects.get(event_type=EventType.COMMUNICATION_TIMEOUT)
        self.assertIsNone(ev.payload["last_seen_at"])

    def test_assetstate_last_seen_at_is_used_as_fallback(self):
        # Device.last_seen_at is None but AssetState.last_seen_at is recent.
        device = _make_device_with_interval(
            self.site, self.asset, interval=60, last_seen_at=None,
        )
        _make_assetstate(
            self.asset, self.site, device,
            last_seen_at=self.now - timedelta(seconds=15),
        )
        result = check_device_communication_timeout(device, now=self.now)
        self.assertEqual(result.devices_ok, 1)
        self.assertEqual(result.timeouts_created, 0)

    def test_dry_run_creates_no_event_or_state_change(self):
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )
        state = _make_assetstate(
            self.asset, self.site, device,
            status=OperationalStatus.ACTIVE, has_active_anomaly=False,
        )
        result = check_device_communication_timeout(
            device, now=self.now, dry_run=True,
        )

        self.assertEqual(result.timeouts_created, 1)  # counted, not persisted
        self.assertEqual(
            Event.objects.filter(event_type=EventType.COMMUNICATION_TIMEOUT).count(), 0,
        )
        state.refresh_from_db()
        self.assertEqual(state.status, OperationalStatus.ACTIVE)
        self.assertFalse(state.has_active_anomaly)

    def test_grace_multiplier_overrides_threshold(self):
        # last_seen_at = 90s ago, interval = 60s.
        # multiplier=3 → threshold=180 → ok.
        # multiplier=1 → threshold=60 → timeout.
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(seconds=90),
        )
        ok_result = check_device_communication_timeout(
            device, now=self.now, grace_multiplier=3.0,
        )
        self.assertEqual(ok_result.devices_ok, 1)

        Event.objects.all().delete()  # reset for the second pass
        timed_out_result = check_device_communication_timeout(
            device, now=self.now, grace_multiplier=1.0,
        )
        self.assertEqual(timed_out_result.timeouts_created, 1)

    def test_default_seconds_used_when_expected_interval_missing(self):
        # expected_interval_seconds=0 → use COMMUNICATION_TIMEOUT_DEFAULT_SECONDS (300).
        # multiplier=3 → threshold=900s. last_seen_at 1000s ago → timed_out.
        device = _make_device_with_interval(
            self.site, self.asset,
            interval=0, last_seen_at=self.now - timedelta(seconds=1000),
        )
        result = check_device_communication_timeout(device, now=self.now)
        self.assertEqual(result.timeouts_created, 1)


# ── Service: AssetState updates ──────────────────────────────────────────────

class CommunicationTimeoutAssetStateTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.now = timezone.now()
        self.device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )
        self.state = _make_assetstate(
            self.asset, self.site, self.device, status=OperationalStatus.ACTIVE,
        )

    def test_assetstate_becomes_offline_on_timeout(self):
        check_device_communication_timeout(self.device, now=self.now)
        self.state.refresh_from_db()
        self.assertEqual(self.state.status, OperationalStatus.OFFLINE)
        self.assertTrue(self.state.has_active_anomaly)
        self.assertEqual(self.state.active_anomaly_count, 1)

    def test_assetstate_recovers_when_no_other_open_events(self):
        check_device_communication_timeout(self.device, now=self.now)

        self.device.last_seen_at = self.now + timedelta(seconds=10)
        self.device.save(update_fields=["last_seen_at"])

        check_device_communication_timeout(
            self.device, now=self.now + timedelta(seconds=15),
        )
        self.state.refresh_from_db()
        self.assertEqual(self.state.status, OperationalStatus.ACTIVE)
        self.assertFalse(self.state.has_active_anomaly)
        self.assertEqual(self.state.active_anomaly_count, 0)

    def test_assetstate_does_not_recover_when_other_open_events_remain(self):
        # First produce a timeout, then create an unrelated open threshold event.
        check_device_communication_timeout(self.device, now=self.now)
        Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING,
            status=EventStatus.OPEN,
            site=self.site, asset=self.asset, device=self.device,
            title="Unrelated open event",
            source="analytics",
            payload={"rule_code": "x"},
        )

        self.device.last_seen_at = self.now + timedelta(seconds=10)
        self.device.save(update_fields=["last_seen_at"])
        check_device_communication_timeout(
            self.device, now=self.now + timedelta(seconds=15),
        )

        self.state.refresh_from_db()
        # Conservative: status stays OFFLINE because another open event remains.
        self.assertEqual(self.state.status, OperationalStatus.OFFLINE)
        self.assertTrue(self.state.has_active_anomaly)
        self.assertEqual(self.state.active_anomaly_count, 1)


# ── Service: bulk filters ────────────────────────────────────────────────────

class CommunicationTimeoutBulkFiltersTest(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.site_a = _make_site(code="site_a")
        self.site_b = _make_site(code="site_b")
        self.asset_a = _make_asset(self.site_a, code="asset-a")
        self.asset_b = _make_asset(self.site_b, code="asset-b")
        self.device_a = _make_device_with_interval(
            self.site_a, self.asset_a, uid="device-a", interval=60,
            last_seen_at=self.now - timedelta(minutes=30),
        )
        self.device_b = _make_device_with_interval(
            self.site_b, self.asset_b, uid="device-b", interval=60,
            last_seen_at=self.now - timedelta(seconds=10),
        )

    def test_no_filter_checks_all_devices(self):
        result = check_all_device_communication_timeouts(now=self.now)
        self.assertEqual(result.devices_checked, 2)
        self.assertEqual(result.timeouts_created, 1)
        self.assertEqual(result.devices_ok, 1)

    def test_site_filter_restricts_to_site(self):
        result = check_all_device_communication_timeouts(
            now=self.now, site=self.site_b,
        )
        self.assertEqual(result.devices_checked, 1)
        self.assertEqual(result.devices_ok, 1)
        self.assertEqual(result.timeouts_created, 0)

    def test_device_filter_restricts_to_device(self):
        result = check_all_device_communication_timeouts(
            now=self.now, device=self.device_a,
        )
        self.assertEqual(result.devices_checked, 1)
        self.assertEqual(result.timeouts_created, 1)


# ── Management command ───────────────────────────────────────────────────────

class CheckCommunicationTimeoutsCommandTest(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=self.now - timedelta(minutes=30),
        )

    def test_summary_is_printed(self):
        out = StringIO()
        call_command("check_communication_timeouts", stdout=out)
        text = out.getvalue()
        self.assertIn("devices_checked = 1", text)
        self.assertIn("timeouts_created = 1", text)

    def test_dry_run_creates_no_event(self):
        out = StringIO()
        call_command("check_communication_timeouts", "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())
        self.assertEqual(
            Event.objects.filter(event_type=EventType.COMMUNICATION_TIMEOUT).count(), 0,
        )

    def test_verbose_prints_per_device_lines(self):
        out = StringIO()
        call_command(
            "check_communication_timeouts", "--dry-run", "--verbosity=2",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("per-device details:", text)
        self.assertIn(self.device.device_uid, text)
        self.assertIn("status_counts:", text)

    def test_invalid_site_raises_command_error(self):
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "check_communication_timeouts", "--site", "missing_site",
                stdout=StringIO(),
            )
        self.assertIn("missing_site", str(ctx.exception))

    def test_invalid_device_raises_command_error(self):
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "check_communication_timeouts", "--device", "missing_uid",
                stdout=StringIO(),
            )
        self.assertIn("missing_uid", str(ctx.exception))

    def test_site_filter_passed_through(self):
        # Add a device on a second site with recent last_seen_at — must be excluded.
        other_site = _make_site(code="other_site")
        other_asset = _make_asset(other_site, code="other-asset")
        _make_device_with_interval(
            other_site, other_asset, uid="other-device", interval=60,
            last_seen_at=self.now - timedelta(seconds=10),
        )
        out = StringIO()
        call_command(
            "check_communication_timeouts", "--site", self.site.code,
            "--verbosity=2", stdout=out,
        )
        text = out.getvalue()
        self.assertIn(self.device.device_uid, text)
        self.assertNotIn("other-device", text)

    def test_device_filter_passed_through(self):
        out = StringIO()
        call_command(
            "check_communication_timeouts", "--device", self.device.device_uid,
            "--verbosity=2", stdout=out,
        )
        text = out.getvalue()
        self.assertIn("devices_checked = 1", text)
        self.assertIn(self.device.device_uid, text)


# ── Ingestion close-on-recovery hook ─────────────────────────────────────────

class IngestionCloseTimeoutHookTest(TestCase):
    """
    The recovery hook in ``apps.mqtt_ingestion.services.ingestion_service``
    closes any open communication_timeout event for the device that has just
    communicated. Telemetry persistence is independent of the hook's success.
    """

    def setUp(self):
        from apps.iot_config.models import MetricDefinition  # local: avoid cycles
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.device = _make_device_with_interval(
            self.site, self.asset,
            interval=60, last_seen_at=timezone.now() - timedelta(minutes=30),
        )
        # Pre-create an open timeout event for the device.
        self.timeout_event = Event.objects.create(
            event_type=EventType.COMMUNICATION_TIMEOUT,
            severity=Severity.WARNING,
            status=EventStatus.OPEN,
            site=self.site, asset=self.asset, device=self.device,
            title="Communication timeout: charger-001",
            source="analytics",
            payload={"device_uid": self.device.device_uid},
        )
        # Voltage metric for telemetry.
        self.metric = MetricDefinition.objects.create(
            key="voltage_v", display_name="voltage_v",
            unit="V", data_type=DataType.FLOAT,
        )

    def _payload(self, message_id="recovery-1"):
        return {
            "message_id": message_id,
            "device_id": self.device.device_uid,
            "asset_id": self.asset.code,
            "timestamp": "2026-05-17T10:00:00Z",
            "metrics": {"voltage_v": 52.3},
            "status": "charging",
            "firmware_version": "0.1.0",
        }

    def test_close_helper_closes_open_timeout_directly(self):
        closed = close_communication_timeout_for_device(self.device)
        self.assertEqual(closed, 1)
        self.timeout_event.refresh_from_db()
        self.assertEqual(self.timeout_event.status, EventStatus.CLOSED)

    def test_telemetry_message_closes_open_timeout(self):
        from apps.mqtt_ingestion.services import process_mqtt_message
        topic = "smt/dev/default_demo/charger/charger-001/telemetry"
        result = process_mqtt_message(topic, self._payload())

        self.assertTrue(result.success)
        self.timeout_event.refresh_from_db()
        self.assertEqual(self.timeout_event.status, EventStatus.CLOSED)

    def test_telemetry_persists_even_if_close_helper_fails(self):
        from apps.mqtt_ingestion.services import process_mqtt_message
        topic = "smt/dev/default_demo/charger/charger-001/telemetry"

        with patch(
            "apps.analytics.services.communication_timeouts."
            "close_communication_timeout_for_device",
            side_effect=RuntimeError("close hook blew up"),
        ):
            result = process_mqtt_message(topic, self._payload())

        self.assertTrue(result.success)
        self.assertTrue(any("close hook blew up" in e for e in result.errors))
        # Telemetry committed despite the hook failure.
        self.assertEqual(Measurement.objects.count(), 1)
        # The pre-existing timeout event was NOT closed because the hook failed.
        self.timeout_event.refresh_from_db()
        self.assertEqual(self.timeout_event.status, EventStatus.OPEN)
        # The hook recorded an ingestion_error event.
        self.assertEqual(
            Event.objects.filter(event_type=EventType.INGESTION_ERROR).count(), 1,
        )
