"""
Tests for the simulator app.

All tests run against the SQLite test database:
    python manage.py test apps.simulator --settings=config.settings.test

No live MQTT broker is required. paho is never imported in these tests.
"""

import json
import threading
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.assets.models import Asset, AssetType, Device, Site
from apps.iot_config.models import DeviceProfile, MetricDefinition
from apps.simulator.models import (
    SimulatorMetricProfile,
    SimulatorRun,
    SimulatorScenario,
    SimulatorScenarioDevice,
)
from apps.simulator.services.mqtt_publisher import (
    DEFAULT_PUBLISH_TIMEOUT_SECONDS,
    SimulatorPublishError,
    publish_message,
)
from apps.simulator.services.payload_generator import generate_payload, _generate_value
from apps.simulator.services.topic_builder import SimulatorConfigError, build_telemetry_topic


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_site(code="default_demo"):
    return Site.objects.create(code=code, name=f"Site {code}")


def _make_asset(site, code="charger-001", asset_type=AssetType.CHARGER):
    return Asset.objects.create(
        site=site, code=code, name=f"Asset {code}", asset_type=asset_type
    )


def _make_device(site, asset, uid="charger-001", firmware_version="1.0.0"):
    return Device.objects.create(
        site=site,
        asset=asset,
        device_uid=uid,
        name=f"Device {uid}",
        device_type="charger",
        is_simulated=True,
        firmware_version=firmware_version,
    )


def _make_metric(key="voltage_v", unit="V"):
    return MetricDefinition.objects.create(key=key, display_name=key, unit=unit)


def _make_profile(code="demo_charger_profile"):
    return DeviceProfile.objects.create(
        code=code, name="Demo Profile", device_type="charger"
    )


def _make_scenario(site, code="default_demo"):
    return SimulatorScenario.objects.create(
        code=code,
        name=f"Scenario {code}",
        site=site,
        default_status="charging",
        interval_seconds=60,
    )


def _make_scenario_device(scenario, device, profile=None):
    return SimulatorScenarioDevice.objects.create(
        scenario=scenario,
        device=device,
        device_profile=profile,
        is_enabled=True,
        sort_order=1,
    )


def _make_metric_profile(scenario_device, metric, base_value=50.0, noise=0.0, mode="constant"):
    return SimulatorMetricProfile.objects.create(
        scenario_device=scenario_device,
        metric=metric,
        base_value=base_value,
        noise_amplitude=noise,
        generation_mode=mode,
        is_enabled=True,
        sort_order=1,
    )


# ── Model creation tests ───────────────────────────────────────────────────────

class SimulatorScenarioModelTest(TestCase):

    def setUp(self):
        self.site = _make_site()

    def test_create_scenario(self):
        s = _make_scenario(self.site)
        self.assertEqual(s.code, "default_demo")
        self.assertEqual(s.site, self.site)
        self.assertEqual(s.interval_seconds, 60)
        self.assertIsNone(s.last_run_at)
        self.assertTrue(s.is_active)

    def test_str_representation(self):
        s = _make_scenario(self.site)
        self.assertIn("default_demo", str(s))
        self.assertIn("Scenario default_demo", str(s))

    def test_code_unique_constraint(self):
        _make_scenario(self.site, code="unique_code")
        with self.assertRaises(Exception):
            _make_scenario(self.site, code="unique_code")


class SimulatorScenarioDeviceModelTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.device = _make_device(self.site, self.asset)
        self.scenario = _make_scenario(self.site)

    def test_create_scenario_device(self):
        sd = _make_scenario_device(self.scenario, self.device)
        self.assertEqual(sd.scenario, self.scenario)
        self.assertEqual(sd.device, self.device)
        self.assertTrue(sd.is_enabled)
        self.assertEqual(sd.sort_order, 1)

    def test_str_representation(self):
        sd = _make_scenario_device(self.scenario, self.device)
        self.assertIn("default_demo", str(sd))
        self.assertIn("charger-001", str(sd))

    def test_unique_scenario_device_constraint(self):
        _make_scenario_device(self.scenario, self.device)
        with self.assertRaises(Exception):
            SimulatorScenarioDevice.objects.create(
                scenario=self.scenario, device=self.device, sort_order=2
            )


class SimulatorMetricProfileModelTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.asset = _make_asset(self.site)
        self.device = _make_device(self.site, self.asset)
        self.scenario = _make_scenario(self.site)
        self.sd = _make_scenario_device(self.scenario, self.device)
        self.metric = _make_metric()

    def test_create_metric_profile(self):
        mp = _make_metric_profile(self.sd, self.metric, base_value=52.0, noise=0.5)
        self.assertEqual(mp.base_value, 52.0)
        self.assertEqual(mp.noise_amplitude, 0.5)
        self.assertEqual(mp.generation_mode, "constant")
        self.assertTrue(mp.is_enabled)

    def test_str_representation(self):
        mp = _make_metric_profile(self.sd, self.metric)
        self.assertIn("voltage_v", str(mp))

    def test_unique_scenario_device_metric_constraint(self):
        _make_metric_profile(self.sd, self.metric)
        with self.assertRaises(Exception):
            SimulatorMetricProfile.objects.create(
                scenario_device=self.sd,
                metric=self.metric,
                base_value=60.0,
            )


class SimulatorRunModelTest(TestCase):

    def setUp(self):
        self.site = _make_site()
        self.scenario = _make_scenario(self.site)

    def test_create_run(self):
        run = SimulatorRun.objects.create(scenario=self.scenario, status="running")
        self.assertEqual(run.scenario, self.scenario)
        self.assertEqual(run.status, "running")
        self.assertEqual(run.messages_published, 0)
        self.assertIsNotNone(run.started_at)
        self.assertIsNone(run.finished_at)

    def test_str_representation(self):
        run = SimulatorRun.objects.create(scenario=self.scenario, status="completed")
        s = str(run)
        self.assertIn("default_demo", s)
        self.assertIn("completed", s)


# ── seed_demo_data idempotency tests ──────────────────────────────────────────

class SeedDemoDataSimulatorTest(TestCase):

    def test_seed_creates_simulator_records(self):
        call_command("seed_demo_data", verbosity=0)
        self.assertTrue(SimulatorScenario.objects.filter(code="default_demo").exists())
        self.assertTrue(
            SimulatorScenarioDevice.objects.filter(
                scenario__code="default_demo",
                device__device_uid="charger-001",
            ).exists()
        )
        self.assertEqual(
            SimulatorMetricProfile.objects.filter(
                scenario_device__scenario__code="default_demo"
            ).count(),
            5,
        )

    def test_seed_is_idempotent(self):
        call_command("seed_demo_data", verbosity=0)
        call_command("seed_demo_data", verbosity=0)
        self.assertEqual(SimulatorScenario.objects.filter(code="default_demo").count(), 1)
        self.assertEqual(
            SimulatorMetricProfile.objects.filter(
                scenario_device__scenario__code="default_demo"
            ).count(),
            5,
        )


# ── Topic builder tests ────────────────────────────────────────────────────────

class TopicBuilderTest(TestCase):

    def setUp(self):
        self.site = _make_site(code="default_demo")
        self.asset = _make_asset(self.site, code="charger-001", asset_type=AssetType.CHARGER)
        self.device = _make_device(self.site, self.asset, uid="charger-001")

    @override_settings(SMT_ENV="dev")
    def test_builds_correct_topic_dev(self):
        topic = build_telemetry_topic(self.device)
        self.assertEqual(topic, "smt/dev/default_demo/charger/charger-001/telemetry")

    @override_settings(SMT_ENV="prod")
    def test_builds_correct_topic_prod(self):
        topic = build_telemetry_topic(self.device)
        self.assertEqual(topic, "smt/prod/default_demo/charger/charger-001/telemetry")

    @override_settings(SMT_ENV="staging")
    def test_topic_uses_settings_smt_env_not_hardcoded(self):
        topic = build_telemetry_topic(self.device)
        self.assertTrue(topic.startswith("smt/staging/"))

    @override_settings(SMT_ENV="dev")
    def test_raises_when_device_has_no_asset(self):
        self.device.asset = None
        self.device.save()
        with self.assertRaises(SimulatorConfigError):
            build_telemetry_topic(self.device)

    @override_settings(SMT_ENV="dev")
    def test_topic_contains_asset_type(self):
        topic = build_telemetry_topic(self.device)
        self.assertIn("charger", topic)

    @override_settings(SMT_ENV="dev")
    def test_topic_contains_device_uid(self):
        topic = build_telemetry_topic(self.device)
        self.assertIn("charger-001", topic)


# ── Payload generator tests ───────────────────────────────────────────────────

class PayloadGeneratorTest(TestCase):

    @override_settings(SMT_ENV="dev")
    def setUp(self):
        self.site = _make_site(code="default_demo")
        self.asset = _make_asset(self.site, code="charger-001", asset_type=AssetType.CHARGER)
        self.device = _make_device(self.site, self.asset, uid="charger-001", firmware_version="1.2.3")
        self.scenario = _make_scenario(self.site)
        self.sd = _make_scenario_device(self.scenario, self.device)
        self.metric_v = _make_metric(key="voltage_v", unit="V")
        self.metric_t = _make_metric(key="temperature_c", unit="°C")
        _make_metric_profile(self.sd, self.metric_v, base_value=52.0)
        _make_metric_profile(self.sd, self.metric_t, base_value=30.0)

    @override_settings(SMT_ENV="dev")
    def test_generates_valid_payload_structure(self):
        topic, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(topic, "smt/dev/default_demo/charger/charger-001/telemetry")
        self.assertIn("message_id", payload)
        self.assertIn("device_id", payload)
        self.assertIn("asset_id", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("metrics", payload)
        self.assertIn("status", payload)

    @override_settings(SMT_ENV="dev")
    def test_payload_device_id_matches_device_uid(self):
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(payload["device_id"], "charger-001")

    @override_settings(SMT_ENV="dev")
    def test_payload_asset_id_matches_asset_code(self):
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(payload["asset_id"], "charger-001")

    @override_settings(SMT_ENV="dev")
    def test_payload_includes_all_enabled_metrics(self):
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertIn("voltage_v", payload["metrics"])
        self.assertIn("temperature_c", payload["metrics"])

    @override_settings(SMT_ENV="dev")
    def test_disabled_metric_is_excluded(self):
        disabled_metric = _make_metric(key="power_w", unit="W")
        SimulatorMetricProfile.objects.create(
            scenario_device=self.sd,
            metric=disabled_metric,
            base_value=100.0,
            is_enabled=False,
            sort_order=3,
        )
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertNotIn("power_w", payload["metrics"])

    @override_settings(SMT_ENV="dev")
    def test_payload_status_uses_scenario_default_status(self):
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(payload["status"], "charging")

    @override_settings(SMT_ENV="dev")
    def test_payload_status_uses_device_status_override(self):
        self.sd.status_override = "warning"
        self.sd.save()
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(payload["status"], "warning")

    @override_settings(SMT_ENV="dev")
    def test_payload_firmware_version_from_device(self):
        _, payload = generate_payload(self.sd, message_id="test-001")
        self.assertEqual(payload["firmware_version"], "1.2.3")

    @override_settings(SMT_ENV="dev")
    def test_message_id_override(self):
        _, payload = generate_payload(self.sd, message_id="fixed-id-123")
        self.assertEqual(payload["message_id"], "fixed-id-123")

    @override_settings(SMT_ENV="dev")
    def test_constant_mode_returns_base_value(self):
        import random
        rng = random.Random(42)
        mp = SimulatorMetricProfile(
            base_value=52.0,
            noise_amplitude=5.0,
            generation_mode="constant",
            min_value=None,
            max_value=None,
        )
        value = _generate_value(mp, rng)
        self.assertEqual(value, 52.0)

    @override_settings(SMT_ENV="dev")
    def test_random_noise_stays_within_bounds(self):
        import random
        rng = random.Random(0)
        mp = SimulatorMetricProfile(
            base_value=50.0,
            noise_amplitude=10.0,
            generation_mode="random_noise",
            min_value=0.0,
            max_value=60.0,
        )
        for _ in range(100):
            v = _generate_value(mp, rng)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 60.0)

    @override_settings(SMT_ENV="dev")
    def test_min_value_clamps_result(self):
        import random
        rng = random.Random(0)
        mp = SimulatorMetricProfile(
            base_value=5.0,
            noise_amplitude=10.0,
            generation_mode="random_noise",
            min_value=3.0,
            max_value=None,
        )
        for _ in range(50):
            v = _generate_value(mp, rng)
            self.assertGreaterEqual(v, 3.0)

    @override_settings(SMT_ENV="dev")
    def test_max_value_clamps_result(self):
        import random
        rng = random.Random(0)
        mp = SimulatorMetricProfile(
            base_value=95.0,
            noise_amplitude=10.0,
            generation_mode="random_noise",
            min_value=None,
            max_value=100.0,
        )
        for _ in range(50):
            v = _generate_value(mp, rng)
            self.assertLessEqual(v, 100.0)


# ── Management command tests ──────────────────────────────────────────────────

class _StubPublish:
    """Captures publish_message calls without touching paho."""

    def __init__(self):
        self.calls = []

    def __call__(self, topic, payload, **kwargs):
        self.calls.append((topic, payload))


class RunSimulatorCommandTest(TestCase):

    @override_settings(SMT_ENV="dev")
    def setUp(self):
        self.site = _make_site(code="default_demo")
        self.asset = _make_asset(self.site, code="charger-001", asset_type=AssetType.CHARGER)
        self.device = _make_device(self.site, self.asset, uid="charger-001")
        self.scenario = _make_scenario(self.site, code="default_demo")
        self.sd = _make_scenario_device(self.scenario, self.device)
        self.metric = _make_metric(key="voltage_v")
        _make_metric_profile(self.sd, self.metric, base_value=52.0)

    @override_settings(SMT_ENV="dev")
    def test_dry_run_does_not_call_publish(self):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", dry_run=True, verbosity=0)
        self.assertEqual(len(stub.calls), 0)

    @override_settings(SMT_ENV="dev")
    def test_dry_run_writes_topic_to_stdout(self):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                dry_run=True, stdout=out, verbosity=0,
            )
        output = out.getvalue()
        self.assertIn("[dry-run]", output)
        self.assertIn("smt/dev/default_demo/charger/charger-001/telemetry", output)

    @override_settings(SMT_ENV="dev")
    def test_once_calls_publish_with_correct_topic(self):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", once=True, verbosity=0)
        self.assertEqual(len(stub.calls), 1)
        topic, payload_str = stub.calls[0]
        self.assertEqual(topic, "smt/dev/default_demo/charger/charger-001/telemetry")

    @override_settings(SMT_ENV="dev")
    def test_publish_payload_is_valid_json_with_required_fields(self):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", verbosity=0)
        self.assertEqual(len(stub.calls), 1)
        topic, payload_dict = stub.calls[0]
        self.assertIsInstance(payload_dict, dict)
        for field in ("message_id", "device_id", "asset_id", "timestamp", "metrics", "status"):
            self.assertIn(field, payload_dict, f"Missing field: {field}")

    @override_settings(SMT_ENV="dev")
    def test_creates_and_completes_simulator_run(self):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", verbosity=0)
        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.messages_published, 1)
        self.assertIsNotNone(run.finished_at)

    @override_settings(SMT_ENV="dev")
    def test_updates_scenario_last_run_at(self):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", verbosity=0)
        self.scenario.refresh_from_db()
        self.assertIsNotNone(self.scenario.last_run_at)

    @override_settings(SMT_ENV="dev")
    def test_missing_scenario_raises_command_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("run_simulator", scenario="nonexistent_scenario", verbosity=0)

    @override_settings(SMT_ENV="dev")
    def test_error_records_failed_simulator_run(self):
        def _boom(topic, payload, **kwargs):
            raise RuntimeError("MQTT connection refused")

        from django.core.management.base import CommandError
        with patch("apps.simulator.management.commands.run_simulator.publish_message", _boom):
            with self.assertRaises(CommandError):
                call_command("run_simulator", scenario="default_demo", verbosity=0)

        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.status, "failed")
        self.assertIn("MQTT connection refused", run.error_message)
        self.assertIsNotNone(run.finished_at)

    @override_settings(SMT_ENV="dev")
    def test_disabled_scenario_device_is_skipped(self):
        self.sd.is_enabled = False
        self.sd.save()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", verbosity=0)
        self.assertEqual(len(stub.calls), 0)
        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.messages_published, 0)
        self.assertEqual(run.status, "completed")

    @override_settings(SMT_ENV="dev")
    def test_multiple_scenario_devices_each_publish_once(self):
        device2 = Device.objects.create(
            site=self.site,
            asset=self.asset,
            device_uid="charger-002",
            name="Device charger-002",
            device_type="charger",
            is_simulated=True,
        )
        sd2 = SimulatorScenarioDevice.objects.create(
            scenario=self.scenario,
            device=device2,
            is_enabled=True,
            sort_order=2,
        )
        _make_metric_profile(sd2, self.metric, base_value=50.0)

        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", verbosity=0)
        self.assertEqual(len(stub.calls), 2)
        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.messages_published, 2)

    @override_settings(SMT_ENV="dev")
    def test_publish_failure_does_not_print_success(self):
        """When publish_message raises, run_simulator must not announce success."""
        from django.core.management.base import CommandError

        def _boom(topic, payload, **kwargs):
            raise SimulatorPublishError("not acknowledged within 10.0s")

        out = StringIO()
        err = StringIO()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", _boom):
            with self.assertRaises(CommandError):
                call_command(
                    "run_simulator",
                    scenario="default_demo",
                    stdout=out,
                    stderr=err,
                    verbosity=0,
                )
        self.assertNotIn("published", out.getvalue().lower())


# ── Repeated-execution mode tests ─────────────────────────────────────────────

class RunSimulatorRepeatedModeTest(TestCase):
    """Tests for --iterations, --duration-seconds, and --sleep-seconds modes."""

    @override_settings(SMT_ENV="dev")
    def setUp(self):
        self.site = _make_site(code="default_demo")
        self.asset = _make_asset(self.site, code="charger-001", asset_type=AssetType.CHARGER)
        self.device = _make_device(self.site, self.asset, uid="charger-001")
        self.scenario = _make_scenario(self.site, code="default_demo")
        self.scenario.interval_seconds = 30  # fixed reference for sleep tests
        self.scenario.save()
        self.sd = _make_scenario_device(self.scenario, self.device)
        self.metric = _make_metric(key="voltage_v")
        _make_metric_profile(self.sd, self.metric, base_value=52.0)

    # ── --once still works exactly as before ─────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_once_runs_exactly_one_cycle(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command("run_simulator", scenario="default_demo", once=True, verbosity=0)
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(mock_sleep.call_count, 0)

    # ── --iterations ─────────────────────────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_runs_n_cycles(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=3, sleep_seconds=0, verbosity=0,
            )
        self.assertEqual(len(stub.calls), 3)
        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.messages_published, 3)
        self.assertEqual(run.status, "completed")

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_does_not_sleep_after_final_cycle(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=3, sleep_seconds=10, verbosity=0,
            )
        # 3 iterations → 2 sleeps (between 1↔2 and 2↔3, NOT after 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_zero_raises_command_error(self, mock_sleep):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=0, verbosity=0,
            )

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_negative_raises_command_error(self, mock_sleep):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=-1, verbosity=0,
            )

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_uses_sleep_seconds_override(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=2, sleep_seconds=7, verbosity=0,
            )
        # Exactly one sleep between two cycles, with the override value.
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(mock_sleep.call_args.args[0], 7.0)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_uses_scenario_interval_when_no_sleep_override(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=2, verbosity=0,
            )
        # Scenario.interval_seconds was set to 30 in setUp.
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(mock_sleep.call_args.args[0], 30.0)

    # ── --duration-seconds ───────────────────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    @patch("apps.simulator.management.commands.run_simulator.time.monotonic")
    def test_duration_runs_until_deadline_reached_after_first_cycle(
        self, mock_monotonic, mock_sleep
    ):
        # deadline = 0 + 5 = 5; post-cycle check returns 100 → break after 1 cycle.
        mock_monotonic.side_effect = [0.0, 100.0]
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                duration_seconds=5, sleep_seconds=1, verbosity=0,
            )
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(mock_sleep.call_count, 0)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    @patch("apps.simulator.management.commands.run_simulator.time.monotonic")
    def test_duration_runs_multiple_cycles_until_deadline(
        self, mock_monotonic, mock_sleep
    ):
        # deadline = 0 + 10 = 10
        # cycle 1, post-check 1, post-sleep-check 1, cycle 2, post-check 2,
        # post-sleep-check 2, cycle 3, post-check 100 → break (3 cycles).
        mock_monotonic.side_effect = [0.0, 1.0, 1.0, 2.0, 2.0, 100.0]
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                duration_seconds=10, sleep_seconds=1, verbosity=0,
            )
        self.assertEqual(len(stub.calls), 3)
        # Sleeps between cycles 1-2 and 2-3, none after cycle 3.
        self.assertEqual(mock_sleep.call_count, 2)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_duration_zero_raises_command_error(self, mock_sleep):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "run_simulator", scenario="default_demo",
                duration_seconds=0, verbosity=0,
            )

    # ── --sleep-seconds validation ───────────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    def test_negative_sleep_seconds_raises_command_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "run_simulator", scenario="default_demo",
                once=True, sleep_seconds=-5, verbosity=0,
            )

    # ── Mode mutual-exclusion (argparse) ─────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_once_and_iterations_are_mutually_exclusive(self, mock_sleep):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "run_simulator", scenario="default_demo",
                once=True, iterations=3, verbosity=0,
            )
        self.assertIn("Mutually exclusive", str(ctx.exception))

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_iterations_and_duration_are_mutually_exclusive(self, mock_sleep):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=3, duration_seconds=10, verbosity=0,
            )

    # ── SimulatorRun accounting across cycles ────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_simulator_run_records_total_published_across_cycles(self, mock_sleep):
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=4, sleep_seconds=0, verbosity=0,
            )
        # Exactly one SimulatorRun per command invocation, not one per cycle.
        runs = SimulatorRun.objects.filter(scenario=self.scenario)
        self.assertEqual(runs.count(), 1)
        run = runs.first()
        self.assertEqual(run.messages_published, 4)
        self.assertEqual(run.status, "completed")

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_simulator_run_marked_failed_when_publish_raises_mid_iteration(
        self, mock_sleep
    ):
        from django.core.management.base import CommandError

        # Fail on the SECOND publish call; the first should succeed.
        call_count = {"n": 0}

        def _fail_second(topic, payload, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise SimulatorPublishError("broker unreachable")

        with patch(
            "apps.simulator.management.commands.run_simulator.publish_message",
            _fail_second,
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "run_simulator", scenario="default_demo",
                    iterations=5, sleep_seconds=0, verbosity=0,
                )

        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.status, "failed")
        self.assertIn("broker unreachable", run.error_message)
        # First cycle published one message before the second cycle blew up.
        self.assertEqual(run.messages_published, 1)

    # ── Disabled devices in repeated runs ────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_disabled_device_stays_skipped_across_iterations(self, mock_sleep):
        self.sd.is_enabled = False
        self.sd.save()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=3, sleep_seconds=0, verbosity=0,
            )
        self.assertEqual(len(stub.calls), 0)
        run = SimulatorRun.objects.filter(scenario=self.scenario).latest("started_at")
        self.assertEqual(run.messages_published, 0)
        self.assertEqual(run.status, "completed")

    # ── Output wording ───────────────────────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_dry_run_summary_says_generated_not_published(self, mock_sleep):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                once=True, dry_run=True, stdout=out, verbosity=0,
            )
        text = out.getvalue()
        self.assertIn("generated", text)
        self.assertIn("[dry-run, not published]", text)
        # No raw "published N message(s)" success line in dry-run.
        self.assertNotIn("published 1 message", text)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_normal_iterations_summary_includes_cycle_count(self, mock_sleep):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=3, sleep_seconds=0, stdout=out, verbosity=0,
            )
        text = out.getvalue()
        self.assertIn("published 3 message(s)", text)
        self.assertIn("3 cycle(s)", text)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_verbosity_2_includes_topic_and_message_id(self, mock_sleep):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=2, sleep_seconds=0, stdout=out, verbosity=2,
            )
        text = out.getvalue()
        self.assertIn("cycle=1", text)
        self.assertIn("cycle=2", text)
        self.assertIn("smt/dev/default_demo/charger/charger-001/telemetry", text)
        self.assertIn("message_id=", text)

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_verbosity_2_logs_sleep_interval(self, mock_sleep):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                iterations=2, sleep_seconds=4, stdout=out, verbosity=2,
            )
        text = out.getvalue()
        self.assertIn("sleeping 4.0s before next cycle", text)

    # ── Default mode behaviour (no flags) ────────────────────────────────────

    @override_settings(SMT_ENV="dev")
    @patch("apps.simulator.management.commands.run_simulator.time.sleep")
    def test_no_mode_flag_runs_once_and_warns(self, mock_sleep):
        out = StringIO()
        stub = _StubPublish()
        with patch("apps.simulator.management.commands.run_simulator.publish_message", stub):
            call_command(
                "run_simulator", scenario="default_demo",
                stdout=out, verbosity=1,
            )
        self.assertEqual(len(stub.calls), 1)
        self.assertIn("No --once / --iterations / --duration-seconds", out.getvalue())


# ── MQTT publisher lifecycle tests ────────────────────────────────────────────

class _StubMqttPublishInfo:
    """Imitates paho-mqtt's MQTTMessageInfo for publisher unit tests."""

    def __init__(
        self,
        rc: int = 0,
        ack_published: bool = True,
        wait_exc: Exception | None = None,
    ):
        self.rc = rc
        self._published = ack_published
        self._wait_exc = wait_exc
        self.wait_called = False
        self.wait_timeout = None

    def wait_for_publish(self, timeout=None):
        self.wait_called = True
        self.wait_timeout = timeout
        if self._wait_exc is not None:
            raise self._wait_exc

    def is_published(self) -> bool:
        return self._published


class _StubMqttClient:
    """Imitates the paho-mqtt Client surface used by ``publish_message``.

    Mirrors paho's lifecycle: when ``loop_start()`` is called, the stub
    schedules the registered ``on_connect`` callback to fire in a background
    thread (just like paho's network loop delivers CONNACK).
    """

    def __init__(
        self,
        publish_info: _StubMqttPublishInfo | None = None,
        connect_exc: Exception | None = None,
        connack_reason_code: int = 0,
        delay_connack: bool = False,
        suppress_connack: bool = False,
    ):
        self._publish_info = publish_info or _StubMqttPublishInfo()
        self._connect_exc = connect_exc
        self._connack_reason_code = connack_reason_code
        self._delay_connack = delay_connack
        self._suppress_connack = suppress_connack
        self.on_connect = None
        self.calls: list = []
        self.username = None
        self.password = None
        self.connect_args = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def username_pw_set(self, username, password=None):
        self.username = username
        self.password = password
        self.calls.append(("username_pw_set", username, password))

    def connect(self, host, port, keepalive):
        self.connect_args = (host, port, keepalive)
        self.calls.append(("connect", host, port, keepalive))
        if self._connect_exc is not None:
            raise self._connect_exc

    def loop_start(self):
        self.loop_started = True
        self.calls.append("loop_start")
        if self._suppress_connack:
            return
        delay = 0.05 if self._delay_connack else 0.0

        def _fire():
            if self.on_connect is None:
                return
            self.on_connect(self, None, {}, self._connack_reason_code)

        if delay:
            threading.Timer(delay, _fire).start()
        else:
            _fire()

    def publish(self, topic, payload, qos=0):
        self.calls.append(("publish", topic, payload, qos))
        return self._publish_info

    def loop_stop(self):
        self.loop_stopped = True
        self.calls.append("loop_stop")

    def disconnect(self):
        self.disconnected = True
        self.calls.append("disconnect")


def _call_names(stub_client: _StubMqttClient) -> list:
    """Return only the call names (string or first element of tuple) for ordering checks."""
    return [c if isinstance(c, str) else c[0] for c in stub_client.calls]


class MqttPublisherTest(TestCase):

    @override_settings(
        MQTT_HOST="test-host",
        MQTT_PORT=1999,
        MQTT_KEEPALIVE_SECONDS=42,
        MQTT_SIMULATOR_USERNAME="sim_user",
        MQTT_SIMULATOR_PASSWORD="sim_pwd",
    )
    def test_full_lifecycle_call_order(self):
        client = _StubMqttClient()
        publish_message(
            "smt/dev/default_demo/charger/charger-001/telemetry",
            {"hello": "world"},
            client_factory=lambda: client,
        )
        # Required ordering: connect → loop_start → publish → loop_stop → disconnect
        names = _call_names(client)
        self.assertEqual(
            [n for n in names if n != "username_pw_set"],
            ["connect", "loop_start", "publish", "loop_stop", "disconnect"],
        )

    @override_settings(MQTT_HOST="broker", MQTT_PORT=2000, MQTT_KEEPALIVE_SECONDS=33)
    def test_connect_uses_settings_host_port_keepalive(self):
        client = _StubMqttClient()
        publish_message("t", {}, client_factory=lambda: client)
        self.assertEqual(client.connect_args, ("broker", 2000, 33))

    @override_settings(MQTT_SIMULATOR_USERNAME="sim_user", MQTT_SIMULATOR_PASSWORD="sim_pwd")
    def test_uses_simulator_credentials(self):
        client = _StubMqttClient()
        publish_message("t", {}, client_factory=lambda: client)
        self.assertEqual(client.username, "sim_user")
        self.assertEqual(client.password, "sim_pwd")

    @override_settings(MQTT_SIMULATOR_USERNAME="", MQTT_SIMULATOR_PASSWORD="")
    def test_skips_auth_when_no_username_configured(self):
        client = _StubMqttClient()
        publish_message("t", {}, client_factory=lambda: client)
        self.assertIsNone(client.username)

    @override_settings(
        MQTT_USERNAME="ingest_user",
        MQTT_PASSWORD="ingest_pwd",
        MQTT_SIMULATOR_USERNAME="sim_user",
        MQTT_SIMULATOR_PASSWORD="sim_pwd",
    )
    def test_does_not_use_ingestion_worker_credentials(self):
        """Simulator must use MQTT_SIMULATOR_* and never the ingestion worker creds."""
        client = _StubMqttClient()
        publish_message("t", {}, client_factory=lambda: client)
        self.assertEqual(client.username, "sim_user")
        self.assertNotEqual(client.username, "ingest_user")

    def test_publish_uses_qos_1_by_default(self):
        client = _StubMqttClient()
        publish_message("t", {"a": 1}, client_factory=lambda: client)
        publish_call = next(c for c in client.calls if isinstance(c, tuple) and c[0] == "publish")
        self.assertEqual(publish_call[3], 1)

    def test_payload_is_json_encoded(self):
        client = _StubMqttClient()
        publish_message("t", {"a": 1, "b": "two"}, client_factory=lambda: client)
        publish_call = next(c for c in client.calls if isinstance(c, tuple) and c[0] == "publish")
        self.assertEqual(json.loads(publish_call[2]), {"a": 1, "b": "two"})

    def test_calls_wait_for_publish_with_timeout(self):
        info = _StubMqttPublishInfo()
        client = _StubMqttClient(publish_info=info)
        publish_message("t", {}, client_factory=lambda: client, timeout_seconds=7.0)
        self.assertTrue(info.wait_called)
        self.assertEqual(info.wait_timeout, 7.0)

    def test_default_timeout_is_used_when_not_overridden(self):
        info = _StubMqttPublishInfo()
        client = _StubMqttClient(publish_info=info)
        publish_message("t", {}, client_factory=lambda: client)
        self.assertEqual(info.wait_timeout, DEFAULT_PUBLISH_TIMEOUT_SECONDS)

    def test_raises_publish_error_when_not_acknowledged(self):
        info = _StubMqttPublishInfo(ack_published=False)
        client = _StubMqttClient(publish_info=info)
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client, timeout_seconds=0.1)

    def test_raises_publish_error_on_non_zero_rc(self):
        info = _StubMqttPublishInfo(rc=4)
        client = _StubMqttClient(publish_info=info)
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client)

    def test_raises_publish_error_when_wait_for_publish_raises(self):
        info = _StubMqttPublishInfo(wait_exc=RuntimeError("disconnected"))
        client = _StubMqttClient(publish_info=info)
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client)

    def test_loop_stop_and_disconnect_called_on_publish_failure(self):
        info = _StubMqttPublishInfo(ack_published=False)
        client = _StubMqttClient(publish_info=info)
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client)
        self.assertTrue(client.loop_stopped, "loop_stop() must be called in finally")
        self.assertTrue(client.disconnected, "disconnect() must be called in finally")

    def test_connect_failure_is_wrapped_as_publish_error(self):
        client = _StubMqttClient(connect_exc=OSError("Connection refused"))
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client)
        # loop never started, but disconnect cleanup still attempted
        self.assertFalse(client.loop_stopped)
        self.assertTrue(client.disconnected)

    def test_password_omitted_when_username_set_but_password_empty(self):
        with override_settings(MQTT_SIMULATOR_USERNAME="u1", MQTT_SIMULATOR_PASSWORD=""):
            client = _StubMqttClient()
            publish_message("t", {}, client_factory=lambda: client)
        self.assertEqual(client.username, "u1")
        self.assertIsNone(client.password)

    def test_waits_for_connack_before_publishing(self):
        """Publish must only happen AFTER on_connect has fired (paho rc=4 protection)."""
        client = _StubMqttClient(delay_connack=True)
        publish_message("t", {}, client_factory=lambda: client)
        names = [c if isinstance(c, str) else c[0] for c in client.calls]
        connect_idx = names.index("loop_start")
        publish_idx = names.index("publish")
        self.assertLess(connect_idx, publish_idx)

    def test_raises_when_broker_rejects_connection(self):
        """A non-zero CONNACK reason_code (e.g. bad credentials) must abort."""
        client = _StubMqttClient(connack_reason_code=5)  # 5 = not authorised
        with self.assertRaises(SimulatorPublishError) as ctx:
            publish_message("t", {}, client_factory=lambda: client)
        self.assertIn("reason_code=5", str(ctx.exception))
        self.assertIn("MQTT_SIMULATOR_USERNAME", str(ctx.exception))

    def test_raises_when_broker_does_not_send_connack(self):
        """A silent broker (no CONNACK) must surface a clear timeout error."""
        client = _StubMqttClient(suppress_connack=True)
        with self.assertRaises(SimulatorPublishError) as ctx:
            publish_message(
                "t", {},
                client_factory=lambda: client,
                connect_timeout_seconds=0.1,
            )
        self.assertIn("CONNACK", str(ctx.exception))

    def test_does_not_publish_when_broker_rejects_connection(self):
        """publish() must not be called when the broker rejects CONNECT."""
        client = _StubMqttClient(connack_reason_code=5)
        with self.assertRaises(SimulatorPublishError):
            publish_message("t", {}, client_factory=lambda: client)
        names = [c if isinstance(c, str) else c[0] for c in client.calls]
        self.assertNotIn("publish", names)
        # cleanup still runs
        self.assertTrue(client.loop_stopped)
        self.assertTrue(client.disconnected)
