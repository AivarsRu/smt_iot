from django.test import TestCase

from apps.assets.models import Asset, AssetType, Device, Site
from apps.core.models import OperationalStatus
from apps.digital_twin.models import AssetState


def make_site(code="ds1"):
    return Site.objects.create(code=code, name=f"Site {code}")


def make_asset(site, code="da1"):
    return Asset.objects.create(site=site, code=code, name=f"Asset {code}", asset_type=AssetType.CHARGER)


class AssetStateTest(TestCase):
    def setUp(self):
        self.site = make_site()
        self.asset = make_asset(self.site)

    def test_create_asset_state(self):
        state = AssetState.objects.create(
            asset=self.asset,
            site=self.site,
            status=OperationalStatus.ACTIVE,
        )
        self.assertEqual(state.status, OperationalStatus.ACTIVE)
        self.assertFalse(state.has_active_anomaly)
        self.assertEqual(state.active_anomaly_count, 0)
        self.assertIn("active", str(state))

    def test_asset_state_is_one_to_one(self):
        AssetState.objects.create(asset=self.asset, site=self.site)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            AssetState.objects.create(asset=self.asset, site=self.site)

    def test_asset_state_str(self):
        state = AssetState.objects.create(
            asset=self.asset,
            site=self.site,
            status=OperationalStatus.OFFLINE,
        )
        self.assertIn("offline", str(state))

    def test_state_payload_defaults_to_dict(self):
        state = AssetState.objects.create(asset=self.asset, site=self.site)
        self.assertEqual(state.state_payload, {})
