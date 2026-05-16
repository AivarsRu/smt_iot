from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.assets.models import Asset, Device, Sensor, Site
from apps.digital_twin.models import AssetState
from apps.events.models import Event
from apps.iot_config.models import DeviceProfile, MetricDefinition, MqttTopicTemplate
from apps.telemetry.models import Measurement, RawMessage


class SeedDemoDataCommandTest(TestCase):
    def _run_seed(self):
        out = StringIO()
        call_command("seed_demo_data", stdout=out)
        return out.getvalue()

    def test_seed_creates_infrastructure(self):
        self._run_seed()
        self.assertTrue(Site.objects.filter(code="default_demo").exists())
        self.assertTrue(Asset.objects.filter(code="charger-001").exists())
        self.assertTrue(Device.objects.filter(device_uid="charger-001").exists())
        self.assertTrue(Sensor.objects.filter(code="main").exists())

    def test_seed_creates_iot_config(self):
        self._run_seed()
        self.assertEqual(MetricDefinition.objects.count(), 5)
        self.assertEqual(MqttTopicTemplate.objects.count(), 3)
        self.assertTrue(DeviceProfile.objects.filter(code="demo_charger_profile").exists())
        profile = DeviceProfile.objects.get(code="demo_charger_profile")
        self.assertEqual(profile.metrics.count(), 5)

    def test_seed_creates_telemetry(self):
        self._run_seed()
        self.assertTrue(RawMessage.objects.filter(message_id="demo-seed-rawmessage-001").exists())
        self.assertEqual(Measurement.objects.count(), 5)

    def test_seed_creates_digital_twin(self):
        self._run_seed()
        asset = Asset.objects.get(code="charger-001")
        self.assertTrue(AssetState.objects.filter(asset=asset).exists())
        state = AssetState.objects.get(asset=asset)
        self.assertIsNotNone(state.last_voltage_v)
        self.assertIsNotNone(state.last_raw_message)

    def test_seed_creates_event(self):
        self._run_seed()
        self.assertTrue(Event.objects.filter(source="seed_demo_data").exists())

    def test_seed_is_idempotent(self):
        output1 = self._run_seed()
        self.assertIn("created", output1)

        site_count = Site.objects.count()
        raw_count = RawMessage.objects.count()
        measurement_count = Measurement.objects.count()
        state_count = AssetState.objects.count()
        event_count = Event.objects.count()

        output2 = self._run_seed()

        self.assertEqual(Site.objects.count(), site_count)
        self.assertEqual(RawMessage.objects.count(), raw_count)
        self.assertEqual(Measurement.objects.count(), measurement_count)
        self.assertEqual(AssetState.objects.count(), state_count)
        self.assertEqual(Event.objects.count(), event_count)
        self.assertIn("updated", output2)
