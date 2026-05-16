from django.db import IntegrityError
from django.test import TestCase

from apps.assets.models import Asset, AssetType, Device, Sensor, Site
from apps.core.models import OperationalStatus


class SiteModelTest(TestCase):
    def _make_site(self, code="site-001", name="Test Site"):
        return Site.objects.create(code=code, name=name, timezone="Europe/Riga")

    def test_create_site(self):
        site = self._make_site()
        self.assertEqual(site.code, "site-001")
        self.assertEqual(str(site), "site-001 — Test Site")
        self.assertTrue(site.is_active)
        self.assertIsNotNone(site.id)

    def test_site_code_unique(self):
        self._make_site(code="dup")
        with self.assertRaises(IntegrityError):
            self._make_site(code="dup")


class AssetModelTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="site-a", name="Site A")

    def test_create_asset(self):
        asset = Asset.objects.create(
            site=self.site,
            code="charger-001",
            name="Charger 001",
            asset_type=AssetType.CHARGER,
        )
        self.assertEqual(str(asset), "charger-001 — Charger 001")

    def test_asset_site_code_unique(self):
        Asset.objects.create(site=self.site, code="dup", name="First")
        with self.assertRaises(IntegrityError):
            Asset.objects.create(site=self.site, code="dup", name="Second")

    def test_asset_same_code_different_sites(self):
        site2 = Site.objects.create(code="site-b", name="Site B")
        Asset.objects.create(site=self.site, code="shared", name="Asset 1")
        asset2 = Asset.objects.create(site=site2, code="shared", name="Asset 2")
        self.assertEqual(asset2.code, "shared")


class DeviceModelTest(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="site-d", name="Site D")
        self.asset = Asset.objects.create(site=self.site, code="asset-1", name="Asset 1")

    def test_create_device(self):
        device = Device.objects.create(
            site=self.site,
            asset=self.asset,
            device_uid="dev-001",
            name="Device 001",
            is_simulated=True,
        )
        self.assertEqual(str(device), "dev-001 — Device 001")
        self.assertEqual(device.expected_interval_seconds, 60)
        self.assertEqual(device.status, OperationalStatus.UNKNOWN)

    def test_device_uid_unique(self):
        Device.objects.create(site=self.site, device_uid="dup-uid", name="First")
        with self.assertRaises(IntegrityError):
            Device.objects.create(site=self.site, device_uid="dup-uid", name="Second")

    def test_device_without_asset(self):
        device = Device.objects.create(site=self.site, device_uid="no-asset", name="No Asset")
        self.assertIsNone(device.asset)


class SensorModelTest(TestCase):
    def setUp(self):
        site = Site.objects.create(code="site-s", name="Site S")
        self.device = Device.objects.create(site=site, device_uid="dev-s", name="Device S")

    def test_create_sensor(self):
        sensor = Sensor.objects.create(device=self.device, code="temp", name="Temperature")
        self.assertEqual(str(sensor), "dev-s / temp")

    def test_sensor_device_code_unique(self):
        Sensor.objects.create(device=self.device, code="dup", name="First")
        with self.assertRaises(IntegrityError):
            Sensor.objects.create(device=self.device, code="dup", name="Second")

    def test_sensor_same_code_different_devices(self):
        site = Site.objects.create(code="site-s2", name="Site S2")
        device2 = Device.objects.create(site=site, device_uid="dev-s2", name="Device S2")
        Sensor.objects.create(device=self.device, code="shared", name="Sensor 1")
        sensor2 = Sensor.objects.create(device=device2, code="shared", name="Sensor 2")
        self.assertEqual(sensor2.code, "shared")
