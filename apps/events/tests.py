from django.test import TestCase

from apps.assets.models import Asset, AssetType, Device, Site
from apps.events.models import Event, EventStatus, EventType, Severity


def make_site(code="es1"):
    return Site.objects.create(code=code, name=f"Site {code}")


def make_asset(site, code="ea1"):
    return Asset.objects.create(site=site, code=code, name=f"Asset {code}", asset_type=AssetType.CHARGER)


class EventTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.asset = make_asset(self.site)

    def test_create_event(self):
        event = Event.objects.create(
            event_type=EventType.SYSTEM,
            severity=Severity.INFO,
            status=EventStatus.OPEN,
            site=self.site,
            asset=self.asset,
            title="Test system event",
        )
        self.assertEqual(event.event_type, EventType.SYSTEM)
        self.assertEqual(event.status, EventStatus.OPEN)
        self.assertIsNotNone(event.detected_at)

    def test_event_str(self):
        event = Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING,
            status=EventStatus.OPEN,
            title="High temperature",
        )
        s = str(event)
        self.assertIn("threshold_anomaly", s)
        self.assertIn("warning", s)
        self.assertIn("High temperature", s)

    def test_event_without_asset(self):
        event = Event.objects.create(
            event_type=EventType.INGESTION_ERROR,
            severity=Severity.ERROR,
            title="Parse failure",
        )
        self.assertIsNone(event.asset)
        self.assertIsNone(event.device)

    def test_event_payload_defaults_to_dict(self):
        event = Event.objects.create(title="Empty payload event")
        self.assertEqual(event.payload, {})

    def test_event_types_exist(self):
        for et in [
            EventType.SYSTEM,
            EventType.VALIDATION_ERROR,
            EventType.DEVICE_STATUS,
            EventType.THRESHOLD_ANOMALY,
            EventType.COMMUNICATION_TIMEOUT,
            EventType.INGESTION_ERROR,
            EventType.SIMULATOR_EVENT,
        ]:
            event = Event.objects.create(event_type=et, title=f"Test {et}")
            self.assertEqual(event.event_type, et)
