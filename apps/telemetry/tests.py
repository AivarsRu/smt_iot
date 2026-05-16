import datetime

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.assets.models import Asset, AssetType, Device, Site
from apps.iot_config.models import MetricDefinition
from apps.telemetry.models import (
    Measurement,
    MeasurementQuality,
    ProcessingStatus,
    RawMessage,
    SourceType,
)


def make_site(code="s1"):
    return Site.objects.create(code=code, name=f"Site {code}")


def make_asset(site, code="a1"):
    return Asset.objects.create(site=site, code=code, name=f"Asset {code}", asset_type=AssetType.CHARGER)


def make_device(site, uid="dev-1"):
    return Device.objects.create(site=site, device_uid=uid, name=f"Device {uid}")


def make_metric(key="voltage_v"):
    return MetricDefinition.objects.create(key=key, display_name=key.replace("_", " ").title(), unit="V")


class RawMessageTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.device = make_device(self.site)

    def test_create_rawmessage(self):
        msg = RawMessage.objects.create(
            source_type=SourceType.MQTT,
            topic="smt/local/s1/charger/dev-1/telemetry",
            payload={"device_id": "dev-1"},
            device_uid="dev-1",
            device=self.device,
        )
        self.assertEqual(msg.source_type, SourceType.MQTT)
        self.assertEqual(msg.processing_status, ProcessingStatus.RECEIVED)
        self.assertIn("dev-1", str(msg))

    def test_rawmessage_message_id_unique(self):
        RawMessage.objects.create(message_id="uid-abc", payload={})
        with self.assertRaises(IntegrityError):
            RawMessage.objects.create(message_id="uid-abc", payload={})

    def test_rawmessage_blank_message_id_allows_duplicates(self):
        # blank message_id is excluded from the partial unique constraint
        RawMessage.objects.create(message_id="", payload={})
        msg2 = RawMessage.objects.create(message_id="", payload={})
        self.assertIsNotNone(msg2.pk)

    def test_rawmessage_str(self):
        msg = RawMessage.objects.create(
            source_type=SourceType.SIMULATOR,
            device_uid="charger-001",
            payload={},
        )
        s = str(msg)
        self.assertIn("simulator", s)
        self.assertIn("charger-001", s)


class MeasurementTest(TestCase):
    def setUp(self):
        self.site = make_site("ms")
        self.asset = make_asset(self.site)
        self.metric = make_metric("voltage_v")
        self.ts = datetime.datetime(2026, 5, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def _make_measurement(self, raw=None, **kwargs):
        return Measurement.objects.create(
            site=self.site,
            asset=self.asset,
            metric=self.metric,
            raw_message=raw,
            timestamp=self.ts,
            value_float=52.3,
            unit="V",
            **kwargs,
        )

    def test_create_measurement(self):
        m = self._make_measurement()
        self.assertEqual(m.value, 52.3)
        self.assertEqual(m.quality, MeasurementQuality.GOOD)
        self.assertFalse(m.is_anomalous)

    def test_value_property_priority(self):
        m = Measurement(value_float=None, value_int=42, value_bool=True, value_text="hi")
        self.assertEqual(m.value, 42)

        m2 = Measurement(value_float=None, value_int=None, value_bool=False, value_text="hi")
        self.assertEqual(m2.value, False)

        m3 = Measurement(value_float=None, value_int=None, value_bool=None, value_text="hi")
        self.assertEqual(m3.value, "hi")

        m4 = Measurement(value_float=None, value_int=None, value_bool=None, value_text="")
        self.assertIsNone(m4.value)

    def test_unique_raw_message_metric(self):
        raw = RawMessage.objects.create(message_id="uid-m1", payload={})
        self._make_measurement(raw=raw)
        with self.assertRaises(IntegrityError):
            self._make_measurement(raw=raw)

    def test_multiple_measurements_without_raw_message(self):
        self._make_measurement()
        m2 = self._make_measurement()
        self.assertIsNotNone(m2.pk)

    def test_measurement_str(self):
        m = self._make_measurement()
        s = str(m)
        self.assertIn("52.3", s)
