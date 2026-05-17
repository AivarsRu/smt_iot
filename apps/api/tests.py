"""
Tests for the read-only SMT API. Runs without a live MQTT broker:
    python manage.py test apps.api --settings=config.settings.test

Fixtures use ``seed_demo_data`` for the integration-style cases and small
hand-built helpers for the more focused filter/limit assertions.
"""

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.assets.models import Asset, Device, Site
from apps.core.models import DataType, OperationalStatus
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.iot_config.models import MetricDefinition
from apps.simulator.models import SimulatorRun, SimulatorScenario
from apps.telemetry.models import (
    Measurement, MeasurementQuality, ProcessingStatus, RawMessage, SourceType,
)


# ── Test base ────────────────────────────────────────────────────────────────

class _ApiBase(APITestCase):
    """Loads idempotent demo data once per test class and exposes APIClient."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def setUp(self):
        self.client = APIClient()


# ── Health endpoint ──────────────────────────────────────────────────────────

class HealthEndpointTest(APITestCase):

    def test_health_returns_ok_status(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "smt-digital-solution")
        self.assertEqual(body["database"], "ok")


# ── Core list endpoints ──────────────────────────────────────────────────────

class CoreListEndpointsTest(_ApiBase):

    def test_sites_lists_demo_site(self):
        resp = self.client.get("/api/sites/")
        self.assertEqual(resp.status_code, 200)
        codes = [row["code"] for row in resp.json()]
        self.assertIn("default_demo", codes)

    def test_assets_lists_demo_asset(self):
        resp = self.client.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        codes = [row["code"] for row in resp.json()]
        self.assertIn("charger-001", codes)

    def test_devices_lists_demo_device(self):
        resp = self.client.get("/api/devices/")
        self.assertEqual(resp.status_code, 200)
        uids = [row["device_uid"] for row in resp.json()]
        self.assertIn("charger-001", uids)

    def test_sensors_endpoint_is_listable(self):
        resp = self.client.get("/api/sensors/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_sensors_expose_sensor_metrics(self):
        """The nested ``sensor_metrics`` field describes what a Sensor can produce."""
        resp = self.client.get("/api/sensors/")
        self.assertEqual(resp.status_code, 200)
        sensors = resp.json()
        self.assertGreaterEqual(len(sensors), 1)
        row = sensors[0]
        self.assertIn("sensor_metrics", row)
        self.assertIsInstance(row["sensor_metrics"], list)
        # The demo seed wires every metric onto the demo sensor.
        keys = {sm["metric_key"] for sm in row["sensor_metrics"]}
        self.assertIn("temperature_c", keys)
        self.assertIn("voltage_v", keys)

    def test_sensor_metrics_endpoint_lists_demo_rows(self):
        resp = self.client.get("/api/sensor-metrics/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 5)
        keys = {row["metric_key"] for row in rows}
        self.assertIn("temperature_c", keys)
        self.assertIn("battery_soc_pct", keys)

    def test_sensor_metrics_filter_by_metric_key(self):
        resp = self.client.get("/api/sensor-metrics/?metric=temperature_c")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["metric_key"], "temperature_c")

    def test_sensor_metrics_filter_by_device_uid(self):
        resp = self.client.get("/api/sensor-metrics/?device=charger-001")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["device_uid"], "charger-001")

    def test_metrics_lists_demo_metrics(self):
        resp = self.client.get("/api/metrics/")
        self.assertEqual(resp.status_code, 200)
        keys = [row["key"] for row in resp.json()]
        self.assertIn("temperature_c", keys)
        self.assertIn("voltage_v", keys)

    def test_asset_states_endpoint_returns_state(self):
        resp = self.client.get("/api/asset-states/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        # The demo seed creates an AssetState for charger-001.
        self.assertTrue(
            any(r["asset_code"] == "charger-001" for r in rows),
            f"expected charger-001 in {rows}",
        )

    def test_threshold_rules_endpoint_lists_seeded_rules(self):
        resp = self.client.get("/api/threshold-rules/")
        self.assertEqual(resp.status_code, 200)
        codes = [row["code"] for row in resp.json()]
        self.assertIn("temperature_c_high_warning", codes)

    def test_threshold_rules_expose_scope_level_and_sensor_code(self):
        # Phase 7 bugfix: the serializer must surface scope_level so the
        # operator UI and downstream consumers can see exactly which
        # scope each rule binds to. The seeded demo rules are sensor-
        # scoped and pin to the ``main`` sensor of ``charger-001``.
        resp = self.client.get("/api/threshold-rules/")
        self.assertEqual(resp.status_code, 200)
        row = next(
            r for r in resp.json()
            if r["code"] == "temperature_c_high_warning"
        )
        self.assertEqual(row["scope_level"], "sensor")
        self.assertEqual(row["sensor_code"], "main")

    def test_simulator_scenarios_endpoint_lists_default_demo(self):
        resp = self.client.get("/api/simulator-scenarios/")
        self.assertEqual(resp.status_code, 200)
        codes = [row["code"] for row in resp.json()]
        self.assertIn("default_demo", codes)


# ── Measurements ─────────────────────────────────────────────────────────────

class MeasurementsApiTest(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.get(code="default_demo")
        cls.asset = Asset.objects.get(site=cls.site, code="charger-001")
        cls.device = Device.objects.get(device_uid="charger-001")
        cls.m_temp = MetricDefinition.objects.get(key="temperature_c")
        cls.m_volt = MetricDefinition.objects.get(key="voltage_v")
        cls.now = timezone.now()

        # Three temperature measurements with distinct timestamps.
        for offset_min, value, msg_id in [
            (1, 30.0, "m-temp-1"),
            (2, 31.0, "m-temp-2"),
            (3, 32.0, "m-temp-3"),
        ]:
            rm = RawMessage.objects.create(
                source_type=SourceType.MQTT,
                topic="smt/dev/default_demo/charger/charger-001/telemetry",
                payload={"message_id": msg_id},
                message_id=msg_id,
                device_uid=cls.device.device_uid,
                site=cls.site, asset=cls.asset, device=cls.device,
                received_at=cls.now - timedelta(minutes=offset_min),
            )
            Measurement.objects.create(
                site=cls.site, asset=cls.asset, device=cls.device,
                metric=cls.m_temp, raw_message=rm,
                timestamp=cls.now - timedelta(minutes=offset_min),
                value_float=value, unit=cls.m_temp.unit,
                quality=MeasurementQuality.GOOD,
            )

        # One voltage measurement to test metric filtering.
        rm_v = RawMessage.objects.create(
            source_type=SourceType.MQTT,
            topic="smt/dev/default_demo/charger/charger-001/telemetry",
            payload={"message_id": "m-volt-1"}, message_id="m-volt-1",
            device_uid=cls.device.device_uid,
            site=cls.site, asset=cls.asset, device=cls.device,
        )
        Measurement.objects.create(
            site=cls.site, asset=cls.asset, device=cls.device,
            metric=cls.m_volt, raw_message=rm_v,
            timestamp=cls.now, value_float=52.3,
            unit=cls.m_volt.unit, quality=MeasurementQuality.GOOD,
        )

    def test_list_returns_records_ordered_by_newest_first(self):
        resp = self.client.get("/api/measurements/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 4)
        timestamps = [r["timestamp"] for r in rows]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_filter_by_asset_code(self):
        resp = self.client.get("/api/measurements/?asset=charger-001")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["asset_code"] == "charger-001" for r in rows))

    def test_filter_by_device_uid(self):
        resp = self.client.get("/api/measurements/?device=charger-001")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["device_uid"] == "charger-001" for r in rows))

    def test_filter_by_metric_key(self):
        resp = self.client.get("/api/measurements/?metric=voltage_v")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["metric_key"] == "voltage_v" for r in rows))

    def test_filter_from_to_datetime(self):
        # Window deliberately excludes the oldest temperature (3 min ago).
        # APIClient.get(... data=dict) URL-encodes the "+" in the offset.
        from_ts = (self.now - timedelta(seconds=130)).isoformat()
        resp = self.client.get(
            "/api/measurements/",
            data={"metric": "temperature_c", "from": from_ts},
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 2)

    def test_limit_caps_response_size(self):
        resp = self.client.get("/api/measurements/?limit=2")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 2)

    def test_value_field_uses_property(self):
        resp = self.client.get("/api/measurements/?metric=voltage_v")
        rows = resp.json()
        self.assertEqual(rows[0]["value"], 52.3)

    # ── 400 negative cases ────────────────────────────────────────────────

    def test_invalid_datetime_returns_400(self):
        resp = self.client.get("/api/measurements/?from=not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("from", resp.json())

    def test_invalid_limit_returns_400(self):
        resp = self.client.get("/api/measurements/?limit=abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit", resp.json())

    def test_limit_above_max_returns_400(self):
        resp = self.client.get("/api/measurements/?limit=99999")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit", resp.json())


# ── Events ───────────────────────────────────────────────────────────────────

class EventsApiTest(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.get(code="default_demo")
        cls.asset = Asset.objects.get(site=cls.site, code="charger-001")
        cls.device = Device.objects.get(device_uid="charger-001")

        Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING, status=EventStatus.OPEN,
            site=cls.site, asset=cls.asset, device=cls.device,
            title="Threshold anomaly: temperature_c",
            description="value high",
            source="analytics",
            payload={"rule_code": "t_high"},
        )
        Event.objects.create(
            event_type=EventType.COMMUNICATION_TIMEOUT,
            severity=Severity.WARNING, status=EventStatus.CLOSED,
            site=cls.site, asset=cls.asset, device=cls.device,
            title="Communication timeout: charger-001",
            description="recovered",
            source="analytics",
            payload={"device_uid": "charger-001"},
        )

    def test_list_returns_events_newest_first(self):
        resp = self.client.get("/api/events/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 2)
        timestamps = [r["detected_at"] for r in rows]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_filter_by_status_open(self):
        resp = self.client.get("/api/events/?status=open")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["status"] == "open" for r in rows))

    def test_filter_by_event_type(self):
        resp = self.client.get("/api/events/?event_type=threshold_anomaly")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["event_type"] == "threshold_anomaly" for r in rows))

    def test_filter_by_asset_code(self):
        resp = self.client.get("/api/events/?asset=charger-001")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["asset_code"] == "charger-001" for r in rows))

    def test_invalid_status_returns_400(self):
        resp = self.client.get("/api/events/?status=foo")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("status", resp.json())


# ── Raw messages ─────────────────────────────────────────────────────────────

class RawMessagesApiTest(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Drop any seed-created RawMessages so the assertions below count only
        # the ones we create here.
        RawMessage.objects.all().delete()
        cls.site = Site.objects.get(code="default_demo")
        cls.asset = Asset.objects.get(site=cls.site, code="charger-001")
        cls.device = Device.objects.get(device_uid="charger-001")
        for i, st in enumerate(
            [ProcessingStatus.PARSED, ProcessingStatus.FAILED, ProcessingStatus.PARSED],
            start=1,
        ):
            RawMessage.objects.create(
                source_type=SourceType.MQTT,
                topic="smt/dev/default_demo/charger/charger-001/telemetry",
                payload={"x": i}, message_id=f"raw-{i}",
                device_uid=cls.device.device_uid,
                site=cls.site, asset=cls.asset, device=cls.device,
                processing_status=st,
            )

    def test_filter_by_device_uid_and_status(self):
        resp = self.client.get(
            "/api/raw-messages/?device_uid=charger-001&processing_status=parsed",
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["device_uid"] == "charger-001" for r in rows))
        self.assertTrue(all(r["processing_status"] == "parsed" for r in rows))

    def test_invalid_processing_status_returns_400(self):
        resp = self.client.get("/api/raw-messages/?processing_status=foo")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("processing_status", resp.json())


# ── Asset detail convenience routes ─────────────────────────────────────────

class AssetDetailRoutesTest(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.get(code="default_demo")
        cls.asset = Asset.objects.get(site=cls.site, code="charger-001")
        cls.device = Device.objects.get(device_uid="charger-001")
        cls.m_temp = MetricDefinition.objects.get(key="temperature_c")
        rm = RawMessage.objects.create(
            source_type=SourceType.MQTT,
            topic="smt/dev/default_demo/charger/charger-001/telemetry",
            payload={"x": 1}, message_id="rm-detail-1",
            device_uid=cls.device.device_uid,
            site=cls.site, asset=cls.asset, device=cls.device,
        )
        cls.measurement = Measurement.objects.create(
            site=cls.site, asset=cls.asset, device=cls.device,
            metric=cls.m_temp, raw_message=rm,
            timestamp=timezone.now(),
            value_float=42.0, unit=cls.m_temp.unit,
        )
        cls.event = Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING, status=EventStatus.OPEN,
            site=cls.site, asset=cls.asset, device=cls.device,
            title="Threshold anomaly: temperature_c",
            source="analytics", payload={"rule_code": "t_high"},
        )

    def test_state_endpoint_returns_one_state(self):
        resp = self.client.get(f"/api/assets/{self.asset.id}/state/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["asset_code"], "charger-001")

    def test_state_endpoint_accepts_asset_code_in_path(self):
        resp = self.client.get("/api/assets/charger-001/state/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["asset_code"], "charger-001")

    def test_measurements_endpoint_returns_measurements_for_asset(self):
        resp = self.client.get(f"/api/assets/{self.asset.id}/measurements/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(r["asset_code"] == "charger-001" for r in rows))

    def test_events_endpoint_returns_events_for_asset(self):
        resp = self.client.get(f"/api/assets/{self.asset.id}/events/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(any(r["id"] == str(self.event.id) for r in rows))

    def test_unknown_asset_code_returns_404(self):
        resp = self.client.get("/api/assets/does-not-exist/state/")
        self.assertEqual(resp.status_code, 404)

    def test_asset_retrieve_by_code(self):
        resp = self.client.get("/api/assets/charger-001/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], "charger-001")

    def test_device_retrieve_by_device_uid(self):
        resp = self.client.get("/api/devices/charger-001/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["device_uid"], "charger-001")

    def test_site_retrieve_by_code(self):
        resp = self.client.get("/api/sites/default_demo/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], "default_demo")


# ── Simulator runs ───────────────────────────────────────────────────────────

class SimulatorRunsApiTest(_ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.scenario = SimulatorScenario.objects.get(code="default_demo")
        SimulatorRun.objects.create(scenario=cls.scenario, status="completed")
        SimulatorRun.objects.create(scenario=cls.scenario, status="failed")

    def test_filter_by_scenario_code(self):
        resp = self.client.get("/api/simulator-runs/?scenario=default_demo")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["scenario_code"] == "default_demo" for r in rows))

    def test_filter_by_status(self):
        resp = self.client.get("/api/simulator-runs/?status=failed")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["status"] == "failed" for r in rows))

    def test_invalid_status_returns_400(self):
        resp = self.client.get("/api/simulator-runs/?status=foo")
        self.assertEqual(resp.status_code, 400)


# ── Read-only enforcement ────────────────────────────────────────────────────

class ReadOnlyEnforcementTest(_ApiBase):

    LIST_PATHS = [
        "/api/sites/",
        "/api/assets/",
        "/api/devices/",
        "/api/sensors/",
        "/api/sensor-metrics/",
        "/api/metrics/",
        "/api/asset-states/",
        "/api/measurements/",
        "/api/events/",
        "/api/raw-messages/",
        "/api/threshold-rules/",
        "/api/simulator-scenarios/",
        "/api/simulator-runs/",
    ]

    def test_post_is_rejected(self):
        for path in self.LIST_PATHS:
            resp = self.client.post(path, data={}, format="json")
            self.assertEqual(
                resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
                f"POST {path} should return 405, got {resp.status_code}",
            )

    def test_put_is_rejected(self):
        # Sites detail is a stable test target — uses the demo site's UUID.
        site = Site.objects.get(code="default_demo")
        resp = self.client.put(f"/api/sites/{site.id}/", data={}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── Asset / device / asset-state filtering ──────────────────────────────────

class AssetDeviceFiltersTest(_ApiBase):

    def test_assets_filter_by_site_code(self):
        resp = self.client.get("/api/assets/?site=default_demo")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(all(r["site_code"] == "default_demo" for r in resp.json()))

    def test_assets_filter_by_invalid_status_returns_400(self):
        resp = self.client.get("/api/assets/?status=bogus")
        self.assertEqual(resp.status_code, 400)

    def test_devices_filter_by_is_simulated(self):
        resp = self.client.get("/api/devices/?is_simulated=true")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(all(r["is_simulated"] is True for r in resp.json()))

    def test_devices_invalid_is_simulated_returns_400(self):
        resp = self.client.get("/api/devices/?is_simulated=maybe")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("is_simulated", resp.json())

    def test_asset_state_filter_by_has_active_anomaly(self):
        resp = self.client.get("/api/asset-states/?has_active_anomaly=false")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(all(r["has_active_anomaly"] is False for r in rows))


# ── Phase 6, Task 2: dashboard overview tests ────────────────────────────────

class _OverviewBase(_ApiBase):
    """
    Adds enough seeded events / runs / measurements to exercise the
    dashboard summary endpoints without an MQTT broker.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.get(code="default_demo")
        cls.asset = Asset.objects.get(site=cls.site, code="charger-001")
        cls.device = Device.objects.get(device_uid="charger-001")
        cls.scenario = SimulatorScenario.objects.get(code="default_demo")
        cls.metric_temp = MetricDefinition.objects.get(key="temperature_c")
        cls.metric_volt = MetricDefinition.objects.get(key="voltage_v")
        cls.now = timezone.now()

        # A few measurements across two metrics so per-metric latest works.
        for offset_min, value, msg_id, metric in [
            (5, 30.1, "ov-temp-1", cls.metric_temp),
            (4, 30.5, "ov-temp-2", cls.metric_temp),
            (3, 31.0, "ov-temp-3", cls.metric_temp),
            (2, 52.1, "ov-volt-1", cls.metric_volt),
            (1, 52.3, "ov-volt-2", cls.metric_volt),
        ]:
            rm = RawMessage.objects.create(
                source_type=SourceType.MQTT,
                topic="smt/dev/default_demo/charger/charger-001/telemetry",
                payload={"message_id": msg_id}, message_id=msg_id,
                device_uid=cls.device.device_uid,
                site=cls.site, asset=cls.asset, device=cls.device,
                received_at=cls.now - timedelta(minutes=offset_min),
            )
            Measurement.objects.create(
                site=cls.site, asset=cls.asset, device=cls.device,
                metric=metric, raw_message=rm,
                timestamp=cls.now - timedelta(minutes=offset_min),
                value_float=value, unit=metric.unit,
                quality=MeasurementQuality.GOOD,
            )

        # One open and one closed event — exercises both buckets.
        cls.event_open = Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING, status=EventStatus.OPEN,
            site=cls.site, asset=cls.asset, device=cls.device,
            title="Threshold anomaly: temperature_c",
            source="analytics", payload={"rule_code": "t_high"},
        )
        cls.event_closed = Event.objects.create(
            event_type=EventType.COMMUNICATION_TIMEOUT,
            severity=Severity.WARNING, status=EventStatus.CLOSED,
            site=cls.site, asset=cls.asset, device=cls.device,
            title="Communication timeout: charger-001",
            source="analytics", payload={"device_uid": "charger-001"},
        )

        # Two simulator runs.
        SimulatorRun.objects.create(scenario=cls.scenario, status="completed",
                                    messages_published=3)
        SimulatorRun.objects.create(scenario=cls.scenario, status="failed")


class OverviewSystemTest(_OverviewBase):

    def test_overview_returns_all_sections(self):
        resp = self.client.get("/api/overview/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("status", "generated_at", "assets", "devices",
                    "telemetry", "events", "simulator"):
            self.assertIn(key, body, f"missing key {key} in {body.keys()}")
        self.assertEqual(body["status"], "ok")

    def test_overview_assets_counts_match_seed(self):
        resp = self.client.get("/api/overview/")
        body = resp.json()
        self.assertEqual(body["assets"]["total"], Asset.objects.count())

    def test_overview_events_counts_have_open_threshold_anomaly(self):
        resp = self.client.get("/api/overview/")
        body = resp.json()
        self.assertGreaterEqual(body["events"]["open_total"], 1)
        self.assertGreaterEqual(body["events"]["open_threshold_anomaly"], 1)

    def test_overview_simulator_reports_latest_run(self):
        resp = self.client.get("/api/overview/")
        body = resp.json()
        self.assertIsNotNone(body["simulator"]["last_run_status"])

    def test_overview_post_returns_405(self):
        resp = self.client.post("/api/overview/", data={}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class OverviewAssetsTest(_OverviewBase):

    def test_returns_counts_items_and_by_type(self):
        resp = self.client.get("/api/overview/assets/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("counts", body)
        self.assertIn("items", body)
        self.assertIn("by_type", body)
        self.assertGreaterEqual(body["counts"]["total"], 1)

    def test_filter_by_site_code(self):
        resp = self.client.get("/api/overview/assets/?site=default_demo")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(all(r["site_code"] == "default_demo" for r in items))

    def test_filter_by_status(self):
        resp = self.client.get("/api/overview/assets/?status=active")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(all(r["status"] == "active" for r in items))

    def test_filter_by_has_active_anomaly_false(self):
        resp = self.client.get("/api/overview/assets/?has_active_anomaly=false")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(all(r["has_active_anomaly"] is False for r in items))

    def test_limit_is_respected(self):
        resp = self.client.get("/api/overview/assets/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()["items"]), 1)

    def test_invalid_limit_returns_400(self):
        resp = self.client.get("/api/overview/assets/?limit=abc")
        self.assertEqual(resp.status_code, 400)


class OverviewEventsTest(_OverviewBase):

    def test_returns_counts_by_type_and_recent(self):
        resp = self.client.get("/api/overview/events/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("counts", "by_type", "recent"):
            self.assertIn(key, body)
        self.assertGreaterEqual(body["counts"]["open_total"], 1)
        self.assertGreaterEqual(body["counts"]["closed_total"], 1)

    def test_filter_by_status_open(self):
        resp = self.client.get("/api/overview/events/?status=open")
        self.assertEqual(resp.status_code, 200)
        recent = resp.json()["recent"]
        self.assertTrue(all(e["status"] == "open" for e in recent))

    def test_filter_by_event_type(self):
        resp = self.client.get(
            "/api/overview/events/?event_type=threshold_anomaly",
        )
        self.assertEqual(resp.status_code, 200)
        recent = resp.json()["recent"]
        self.assertTrue(all(e["event_type"] == "threshold_anomaly" for e in recent))

    def test_filter_by_asset_code(self):
        resp = self.client.get("/api/overview/events/?asset=charger-001")
        self.assertEqual(resp.status_code, 200)
        recent = resp.json()["recent"]
        self.assertTrue(all(e["asset_code"] == "charger-001" for e in recent))

    def test_limit_is_respected(self):
        resp = self.client.get("/api/overview/events/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()["recent"]), 1)

    def test_invalid_status_returns_400(self):
        resp = self.client.get("/api/overview/events/?status=bogus")
        self.assertEqual(resp.status_code, 400)


class OverviewTelemetryTest(_OverviewBase):

    def test_returns_raw_messages_measurements_and_recent(self):
        resp = self.client.get("/api/overview/telemetry/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("raw_messages", "measurements", "recent_measurements"):
            self.assertIn(key, body)
        # Two metrics with measurements: temperature_c and voltage_v.
        metric_keys = {m["metric_key"] for m in body["measurements"]["metrics"]}
        self.assertIn("temperature_c", metric_keys)
        self.assertIn("voltage_v", metric_keys)

    def test_recent_measurements_are_newest_first(self):
        resp = self.client.get("/api/overview/telemetry/")
        recent = resp.json()["recent_measurements"]
        timestamps = [m["timestamp"] for m in recent]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_filter_by_asset_code(self):
        resp = self.client.get("/api/overview/telemetry/?asset=charger-001")
        self.assertEqual(resp.status_code, 200)
        recent = resp.json()["recent_measurements"]
        self.assertTrue(all(m["asset_code"] == "charger-001" for m in recent))

    def test_filter_by_metric_key(self):
        resp = self.client.get("/api/overview/telemetry/?metric=temperature_c")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(
            all(m["metric_key"] == "temperature_c"
                for m in body["recent_measurements"])
        )
        # metrics list scoped down to the single filtered metric.
        keys = {m["metric_key"] for m in body["measurements"]["metrics"]}
        self.assertEqual(keys, {"temperature_c"})

    def test_limit_is_respected(self):
        resp = self.client.get("/api/overview/telemetry/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()["recent_measurements"]), 1)

    def test_invalid_datetime_returns_400(self):
        resp = self.client.get("/api/overview/telemetry/?from=not-a-date")
        self.assertEqual(resp.status_code, 400)


class OverviewSimulatorTest(_OverviewBase):

    def test_returns_scenarios_and_runs(self):
        resp = self.client.get("/api/overview/simulator/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("scenarios", "runs", "recent_runs"):
            self.assertIn(key, body)
        self.assertGreaterEqual(body["scenarios"]["total"], 1)
        self.assertGreaterEqual(body["runs"]["total"], 2)

    def test_filter_by_scenario_code(self):
        resp = self.client.get("/api/overview/simulator/?scenario=default_demo")
        self.assertEqual(resp.status_code, 200)
        runs = resp.json()["recent_runs"]
        self.assertTrue(all(r["scenario_code"] == "default_demo" for r in runs))

    def test_filter_by_status(self):
        resp = self.client.get("/api/overview/simulator/?status=completed")
        self.assertEqual(resp.status_code, 200)
        runs = resp.json()["recent_runs"]
        self.assertTrue(all(r["status"] == "completed" for r in runs))

    def test_limit_is_respected(self):
        resp = self.client.get("/api/overview/simulator/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()["recent_runs"]), 1)

    def test_invalid_status_returns_400(self):
        resp = self.client.get("/api/overview/simulator/?status=bogus")
        self.assertEqual(resp.status_code, 400)


class AssetSummaryTest(_OverviewBase):

    def test_returns_full_payload(self):
        resp = self.client.get("/api/assets/charger-001/summary/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("asset", "state", "open_events",
                    "latest_measurements", "latest_raw_message"):
            self.assertIn(key, body)
        self.assertEqual(body["asset"]["code"], "charger-001")
        self.assertGreaterEqual(len(body["open_events"]), 1)
        # Two metrics seeded — both should appear in latest_measurements.
        keys = {m["metric_key"] for m in body["latest_measurements"]}
        self.assertIn("temperature_c", keys)
        self.assertIn("voltage_v", keys)
        self.assertIsNotNone(body["latest_raw_message"])

    def test_uuid_route_still_works(self):
        resp = self.client.get(f"/api/assets/{self.asset.id}/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["asset"]["code"], "charger-001")

    def test_unknown_asset_code_returns_404(self):
        resp = self.client.get("/api/assets/does-not-exist/summary/")
        self.assertEqual(resp.status_code, 404)

    def test_metrics_limit_is_respected(self):
        resp = self.client.get(
            "/api/assets/charger-001/summary/?metrics_limit=1",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["latest_measurements"]), 1)

    def test_events_limit_is_respected(self):
        resp = self.client.get(
            "/api/assets/charger-001/summary/?events_limit=1",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()["open_events"]), 1)

    def test_invalid_metrics_limit_returns_400(self):
        resp = self.client.get(
            "/api/assets/charger-001/summary/?metrics_limit=abc",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("metrics_limit", resp.json())

    def test_post_returns_405(self):
        resp = self.client.post(
            "/api/assets/charger-001/summary/", data={}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── Phase 7, Task 4A: sensor/metric filter coverage ─────────────────────────
# Sanity checks for the new ``?sensor=`` and ``?metric=`` filters used by
# the operator Event/Anomaly review UI. We build a tiny isolated fixture
# instead of reusing the seed data so the assertions are deterministic
# (the seed creates one sensor, which would make "filter rejects wrong
# sensor" trivially true regardless of the filter being applied).

class SensorMetricFilterApiTest(APITestCase):

    @classmethod
    def setUpTestData(cls):
        from apps.assets.models import Sensor, SensorMetric

        site = Site.objects.create(code="filter-site", name="Filter Site")
        asset = Asset.objects.create(site=site, code="filter-asset", name="A")
        device = Device.objects.create(
            site=site, asset=asset, device_uid="filter-dev", name="D",
        )
        cls.sensor_a = Sensor.objects.create(
            device=device, code="sensor-aaaa", name="Sensor A",
        )
        cls.sensor_b = Sensor.objects.create(
            device=device, code="sensor-bbbb", name="Sensor B",
        )
        cls.metric_temp = MetricDefinition.objects.create(
            key="filter_temp_c", display_name="T", unit="°C",
        )
        cls.metric_volt = MetricDefinition.objects.create(
            key="filter_volt_v", display_name="V", unit="V",
        )
        SensorMetric.objects.create(sensor=cls.sensor_a, metric=cls.metric_temp)
        SensorMetric.objects.create(sensor=cls.sensor_b, metric=cls.metric_volt)

        now = timezone.now()
        cls.raw_message = RawMessage.objects.create(
            source_type=SourceType.MQTT, topic="t",
            message_id="filter-msg-001", payload={}, device=device, site=site,
            asset=asset, payload_timestamp=now,
            processing_status=ProcessingStatus.PARSED,
        )

        Measurement.objects.create(
            raw_message=cls.raw_message, site=site, asset=asset, device=device,
            sensor=cls.sensor_a, metric=cls.metric_temp,
            timestamp=now, value_float=21.5,
            quality=MeasurementQuality.GOOD,
        )
        Measurement.objects.create(
            raw_message=cls.raw_message, site=site, asset=asset, device=device,
            sensor=cls.sensor_b, metric=cls.metric_volt,
            timestamp=now, value_float=52.1,
            quality=MeasurementQuality.GOOD,
        )

        Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING, status=EventStatus.OPEN,
            site=site, asset=asset, device=device,
            sensor=cls.sensor_a, metric=cls.metric_temp,
            title="A temp warning", source="threshold_service",
            detected_at=now,
        )
        Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.ERROR, status=EventStatus.OPEN,
            site=site, asset=asset, device=device,
            sensor=cls.sensor_b, metric=cls.metric_volt,
            title="B voltage error", source="threshold_service",
            detected_at=now,
        )

    # ── /api/events/ ─────────────────────────────────────────────────────

    def test_events_filter_by_sensor_code(self):
        resp = self.client.get("/api/events/?sensor=sensor-aaaa")
        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.json()]
        self.assertIn("A temp warning", titles)
        self.assertNotIn("B voltage error", titles)

    def test_events_filter_by_sensor_uuid(self):
        resp = self.client.get(
            f"/api/events/?sensor={self.sensor_b.id}",
        )
        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.json()]
        self.assertIn("B voltage error", titles)
        self.assertNotIn("A temp warning", titles)

    def test_events_filter_by_metric_key(self):
        resp = self.client.get("/api/events/?metric=filter_temp_c")
        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.json()]
        self.assertIn("A temp warning", titles)
        self.assertNotIn("B voltage error", titles)

    def test_events_filter_by_sensor_and_metric_combined(self):
        # Combining sensor + metric must AND the predicates.
        resp = self.client.get(
            "/api/events/?sensor=sensor-aaaa&metric=filter_volt_v",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_events_serializer_exposes_sensor_and_metric_codes(self):
        resp = self.client.get("/api/events/?sensor=sensor-aaaa")
        self.assertEqual(resp.status_code, 200)
        row = resp.json()[0]
        for required in (
            "sensor", "sensor_code",
            "metric", "metric_key",
            "asset_code", "device_uid", "payload",
            "measurement", "raw_message",
        ):
            self.assertIn(required, row)

    # ── /api/measurements/ ───────────────────────────────────────────────

    def test_measurements_filter_by_sensor_code(self):
        resp = self.client.get("/api/measurements/?sensor=sensor-aaaa")
        self.assertEqual(resp.status_code, 200)
        sensor_codes = {row["sensor_code"] for row in resp.json()}
        self.assertEqual(sensor_codes, {"sensor-aaaa"})

    def test_measurements_filter_by_sensor_and_metric(self):
        resp = self.client.get(
            "/api/measurements/?sensor=sensor-aaaa&metric=filter_temp_c",
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sensor_code"], "sensor-aaaa")
        self.assertEqual(rows[0]["metric_key"], "filter_temp_c")

    def test_measurements_filter_by_asset_code(self):
        resp = self.client.get("/api/measurements/?asset=filter-asset")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["asset_code"], "filter-asset")

    def test_measurements_datetime_range_filter(self):
        # ``from`` past the data window → empty. Use UTC ``Z`` suffix so
        # the ``+`` in ``+00:00`` is not URL-decoded as a space.
        far_future = (
            (timezone.now() + timedelta(days=365))
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        resp = self.client.get(
            "/api/measurements/",
            data={"sensor": "sensor-aaaa", "from": far_future},
        )
        self.assertEqual(resp.status_code, 200, msg=resp.content[:300])
        self.assertEqual(resp.json(), [])

    def test_measurements_limit_parameter(self):
        resp = self.client.get("/api/measurements/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    # ── 400 invariants for bad input ─────────────────────────────────────

    def test_invalid_event_severity_returns_400(self):
        resp = self.client.get("/api/events/?severity=bogus")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("severity", resp.json())

    def test_invalid_event_status_returns_400(self):
        resp = self.client.get("/api/events/?status=bogus")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_from_datetime_returns_400(self):
        resp = self.client.get("/api/events/?from=not-a-datetime")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("from", resp.json())

    def test_invalid_to_datetime_returns_400(self):
        resp = self.client.get(
            "/api/measurements/?to=also-bad",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("to", resp.json())

    def test_invalid_limit_returns_400(self):
        resp = self.client.get("/api/events/?limit=99999")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("limit", resp.json())
