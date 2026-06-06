"""
Tests for the Phase 7 dashboard (Task 3B — staged workflow).

Covers:
  * Authenticated dashboard shell (overview, asset detail).
  * Login-required redirects for anonymous visitors.
  * Navigation menu visible only to logged-in operators.
  * Server-rendered Assets list.
  * Staged asset configuration workflow (Stage 1 → Stage 4) with
    system-generated identifiers, per-stage atomic transactions, and
    sensor/threshold presets.

Run with:
    python manage.py test apps.dashboard --settings=config.settings.test
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from apps.analytics.models import ThresholdRule, ThresholdRulePreset
from apps.assets.models import (
    Asset, AssetType, Device, Sensor, SensorMetric, Site,
)
from apps.assets.services.identifiers import (
    generate_asset_code,
    generate_device_uid,
    generate_sensor_code,
    next_code,
)
from apps.core.models import OperationalStatus
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.iot_config.models import MetricDefinition, SensorMetricPreset


User = get_user_model()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_user(username="operator", password="op-secret-123!"):
    return User.objects.create_user(username=username, password=password)


class _AuthenticatedClientMixin:
    """Provides ``self.client`` already logged in as a regular user."""

    USERNAME = "operator"
    PASSWORD = "op-secret-123!"

    def setUp(self):
        super().setUp()
        self.user = _make_user(self.USERNAME, self.PASSWORD)
        self.client.login(username=self.USERNAME, password=self.PASSWORD)


def _read_dashboard_config(content: str, script_id: str) -> dict:
    marker = f'<script id="{script_id}" type="application/json">'
    idx = content.find(marker)
    assert idx != -1, f"missing #{script_id} script block"
    body_start = idx + len(marker)
    body_end = content.find("</script>", body_start)
    return json.loads(content[body_start:body_end].strip())


# ── Routing ──────────────────────────────────────────────────────────────────

class DashboardRoutingTest(TestCase):

    def test_overview_url_resolves(self):
        self.assertEqual(resolve("/dashboard/").view_name, "dashboard:overview")

    def test_health_url_resolves(self):
        self.assertEqual(resolve("/dashboard/health/").view_name, "dashboard:health")

    def test_assets_list_url_resolves(self):
        self.assertEqual(
            resolve("/dashboard/assets/").view_name, "dashboard:assets-list",
        )

    def test_asset_create_url_resolves(self):
        # ``/dashboard/assets/new/`` must be registered before the
        # ``<str:asset_identifier>`` catch-all so "new" cannot be matched
        # as an asset code.
        self.assertEqual(
            resolve("/dashboard/assets/new/").view_name,
            "dashboard:asset-create",
        )

    def test_asset_configure_url_resolves(self):
        match = resolve("/dashboard/assets/asset-000001/configure/")
        self.assertEqual(match.view_name, "dashboard:asset-configure")
        self.assertEqual(match.kwargs, {"asset_code": "asset-000001"})

    def test_device_create_url_resolves(self):
        match = resolve("/dashboard/assets/asset-1/devices/new/")
        self.assertEqual(match.view_name, "dashboard:device-create")
        self.assertEqual(match.kwargs["asset_code"], "asset-1")

    def test_device_attach_url_resolves(self):
        match = resolve("/dashboard/assets/asset-1/devices/attach/")
        self.assertEqual(match.view_name, "dashboard:device-attach")

    def test_sensor_create_url_resolves(self):
        match = resolve(
            "/dashboard/assets/asset-1/devices/device-1/sensors/new/"
        )
        self.assertEqual(match.view_name, "dashboard:sensor-create")
        self.assertEqual(
            match.kwargs, {"asset_code": "asset-1", "device_uid": "device-1"},
        )

    def test_sensor_metric_create_url_resolves(self):
        match = resolve(
            "/dashboard/assets/a-1/devices/d-1/sensors/s-1/metrics/new/"
        )
        self.assertEqual(match.view_name, "dashboard:sensor-metric-create")
        self.assertEqual(match.kwargs, {
            "asset_code": "a-1", "device_uid": "d-1", "sensor_code": "s-1",
        })

    def test_asset_detail_url_still_resolves(self):
        match = resolve("/dashboard/assets/charger-001/")
        self.assertEqual(match.view_name, "dashboard:asset-detail")
        self.assertEqual(match.kwargs, {"asset_identifier": "charger-001"})

    def test_events_list_url_resolves(self):
        match = resolve("/dashboard/events/")
        self.assertEqual(match.view_name, "dashboard:events-list")

    def test_event_detail_url_resolves(self):
        event_id = "12345678-1234-1234-1234-1234567890ab"
        match = resolve(f"/dashboard/events/{event_id}/")
        self.assertEqual(match.view_name, "dashboard:event-detail")
        # Path converter `<uuid:event_id>` parses to a uuid.UUID object.
        self.assertEqual(str(match.kwargs["event_id"]), event_id)


# ── Identifier generation ───────────────────────────────────────────────────

class IdentifierGeneratorTest(TestCase):
    """
    The staged workflow generates ``Asset.code`` / ``Device.device_uid`` /
    ``Sensor.code`` for the operator. These tests pin down the format
    and uniqueness contract regardless of HTTP layer.
    """

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="id-site", name="Id Site")
        cls.device_parent = Asset.objects.create(
            site=cls.site, code="asset-existing", name="Existing",
            asset_type=AssetType.OTHER,
        )

    def test_asset_code_format_and_increment(self):
        first = generate_asset_code()
        self.assertEqual(first, "asset-000001")
        Asset.objects.create(
            site=self.site, code=first, name="A", asset_type=AssetType.OTHER,
        )
        self.assertEqual(generate_asset_code(), "asset-000002")

    def test_device_uid_format_and_increment(self):
        self.assertEqual(generate_device_uid(), "device-000001")
        Device.objects.create(
            site=self.site, device_uid="device-000001", name="D1",
        )
        self.assertEqual(generate_device_uid(), "device-000002")

    def test_sensor_code_format_and_increment(self):
        device = Device.objects.create(
            site=self.site, device_uid="device-id-1", name="ID Device",
        )
        self.assertEqual(generate_sensor_code(), "sensor-000001")
        Sensor.objects.create(device=device, code="sensor-000001", name="S")
        self.assertEqual(generate_sensor_code(), "sensor-000002")

    def test_next_code_ignores_non_matching_codes(self):
        # A pre-existing legacy code ("charger-001") must not derail the
        # ``asset-NNNNNN`` counter.
        Asset.objects.create(
            site=self.site, code="charger-007", name="Legacy",
            asset_type=AssetType.OTHER,
        )
        self.assertEqual(next_code(Asset, "code", "asset"), "asset-000001")


# ── Root view + auth ─────────────────────────────────────────────────────────

class RootViewTest(TestCase):

    def test_anonymous_root_renders_welcome(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SMT Digital Solution")
        self.assertContains(resp, "Pieslēgties")
        self.assertContains(resp, reverse("accounts:login"))

    def test_authenticated_root_redirects_to_dashboard(self):
        user = _make_user()
        self.client.login(username=user.username, password="op-secret-123!")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("dashboard:overview"))


class LoginFlowTest(TestCase):

    def test_login_page_renders(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pieslēgties")
        self.assertTemplateUsed(resp, "registration/login.html")

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        _make_user()
        resp = self.client.post(
            reverse("accounts:login"),
            data={"username": "operator", "password": "op-secret-123!"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("dashboard:overview"))

    def test_login_honours_next_parameter(self):
        _make_user()
        next_url = reverse("dashboard:assets-list")
        resp = self.client.post(
            f"{reverse('accounts:login')}?next={next_url}",
            data={
                "username": "operator", "password": "op-secret-123!",
                "next": next_url,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], next_url)

    def test_logout_route_works(self):
        _make_user()
        self.client.login(username="operator", password="op-secret-123!")
        resp = self.client.post(reverse("accounts:logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("core:welcome"))


class AnonymousDashboardRedirectsTest(TestCase):

    PROTECTED_PATHS = [
        "/dashboard/",
        "/dashboard/assets/",
        "/dashboard/assets/new/",
        "/dashboard/assets/charger-001/",
        "/dashboard/assets/asset-1/configure/",
        "/dashboard/assets/asset-1/devices/new/",
        "/dashboard/assets/asset-1/devices/attach/",
        "/dashboard/assets/asset-1/devices/d-1/sensors/new/",
        "/dashboard/assets/asset-1/devices/d-1/sensors/s-1/metrics/new/",
        "/dashboard/events/",
        "/dashboard/events/12345678-1234-1234-1234-1234567890ab/",
    ]

    def test_anonymous_dashboard_routes_redirect_to_login(self):
        for path in self.PROTECTED_PATHS:
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(
                    resp.status_code, 302,
                    f"{path} should redirect anonymous visitors",
                )
                self.assertIn("/accounts/login/", resp["Location"])
                self.assertIn("next=", resp["Location"])


# ── Overview / asset detail pages (authenticated) ───────────────────────────

class DashboardOverviewPageTest(_AuthenticatedClientMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.response = self.client.get("/dashboard/")

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_uses_overview_template(self):
        templates = [t.name for t in self.response.templates if t.name]
        self.assertIn("dashboard/overview.html", templates)
        self.assertIn("dashboard/base.html", templates)

    def test_page_contains_project_title(self):
        self.assertContains(self.response, "SMT Digital Solution")

    def test_page_contains_refresh_button(self):
        self.assertContains(self.response, 'data-role="refresh-btn"')

    def test_dashboard_config_is_valid_json(self):
        cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"), "dashboard-config",
        )
        # Phase 7, Task 4 — simulator endpoints have moved to the
        # dedicated /dashboard/simulator/ page; the overview only
        # advertises the strictly operational summary endpoints.
        for required in (
            "overview", "overviewAssets", "overviewEvents",
            "overviewTelemetry",
        ):
            self.assertIn(required, cfg["endpoints"])
        self.assertNotIn("overviewSimulator", cfg["endpoints"])
        self.assertNotIn("simulatorStatus", cfg["endpoints"])
        self.assertIn("__CODE__", cfg["assetSummaryUrlTemplate"])


class DashboardHealthPageTest(TestCase):

    def test_returns_200_and_ok_text(self):
        resp = self.client.get("/dashboard/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ok", resp.content.decode("utf-8").lower())


class AssetDetailPageTest(_AuthenticatedClientMixin, TestCase):

    URL = "/dashboard/assets/charger-001/"

    def setUp(self):
        super().setUp()
        self.response = self.client.get(self.URL)

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_unknown_asset_code_also_returns_200_shell(self):
        resp = self.client.get("/dashboard/assets/does-not-exist/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-role="page-error"')

    def test_uuid_route_returns_200(self):
        random_uuid = uuid.uuid4()
        resp = self.client.get(f"/dashboard/assets/{random_uuid}/")
        self.assertEqual(resp.status_code, 200)

    def test_uses_expected_template(self):
        templates = [t.name for t in self.response.templates if t.name]
        self.assertIn("dashboard/asset_detail.html", templates)

    def test_detail_page_links_to_configure_when_asset_exists(self):
        site = Site.objects.create(code="dx-site", name="Dx Site")
        Asset.objects.create(
            site=site, code="asset-detail-1", name="Detail 1",
            asset_type=AssetType.OTHER,
        )
        resp = self.client.get("/dashboard/assets/asset-detail-1/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": "asset-detail-1"}),
        )
        self.assertContains(resp, 'data-role="configure-link"')

    def test_config_block_carries_asset_identifier(self):
        cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"), "asset-detail-config",
        )
        self.assertEqual(cfg["assetIdentifier"], "charger-001")


class OverviewLinksToAssetDetailTest(_AuthenticatedClientMixin, TestCase):

    def test_overview_config_includes_asset_detail_url_template(self):
        resp = self.client.get("/dashboard/")
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "dashboard-config",
        )
        self.assertEqual(
            cfg["assetDetailUrlTemplate"], "/dashboard/assets/__CODE__/",
        )


# ── Navigation menu ──────────────────────────────────────────────────────────

class NavigationMenuTest(_AuthenticatedClientMixin, TestCase):

    def test_overview_shows_navigation_links(self):
        resp = self.client.get("/dashboard/")
        self.assertContains(resp, 'data-role="nav-dashboard"')
        self.assertContains(resp, 'data-role="nav-assets"')
        self.assertContains(resp, 'data-role="nav-asset-create"')
        self.assertContains(resp, 'data-role="nav-events"')
        # Phase 7, Task 4 — Simulators is now a top-level navigation entry.
        self.assertContains(resp, 'data-role="nav-simulator"')
        self.assertContains(resp, ">Simulators</a>")
        self.assertContains(resp, f'href="{reverse("dashboard:overview")}"')
        self.assertContains(resp, f'href="{reverse("dashboard:assets-list")}"')
        self.assertContains(resp, f'href="{reverse("dashboard:asset-create")}"')
        self.assertContains(resp, f'href="{reverse("dashboard:events-list")}"')
        self.assertContains(resp, f'href="{reverse("dashboard:simulator")}"')

    def test_logout_form_present_for_authenticated_users(self):
        resp = self.client.get("/dashboard/")
        self.assertContains(resp, 'data-role="logout-btn"')
        self.assertContains(resp, reverse("accounts:logout"))


class WelcomePageHasNoNavMenuTest(TestCase):

    def test_anonymous_welcome_page_has_no_authenticated_nav(self):
        resp = self.client.get("/")
        self.assertNotContains(resp, 'data-role="nav-assets"')
        self.assertNotContains(resp, 'data-role="logout-btn"')


# ── Assets list page ─────────────────────────────────────────────────────────

class AssetsListPageTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(code="ops-site", name="Ops Site")
        cls.asset_a = Asset.objects.create(
            site=site, code="asset-a", name="Asset A",
            asset_type=AssetType.CHARGER, status=OperationalStatus.ACTIVE,
        )
        cls.asset_b = Asset.objects.create(
            site=site, code="asset-b", name="Asset B",
            asset_type=AssetType.BATTERY, status=OperationalStatus.UNKNOWN,
        )

    def test_returns_200(self):
        resp = self.client.get(reverse("dashboard:assets-list"))
        self.assertEqual(resp.status_code, 200)

    def test_lists_existing_assets(self):
        resp = self.client.get(reverse("dashboard:assets-list"))
        self.assertContains(resp, self.asset_a.code)
        self.assertContains(resp, self.asset_b.code)

    def test_each_row_links_to_detail_and_configure(self):
        resp = self.client.get(reverse("dashboard:assets-list"))
        self.assertContains(
            resp,
            reverse("dashboard:asset-detail",
                    kwargs={"asset_identifier": self.asset_a.code}),
        )
        self.assertContains(
            resp,
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": self.asset_a.code}),
        )
        self.assertContains(resp, 'data-role="configure-link"')

    def test_contains_link_to_asset_create(self):
        resp = self.client.get(reverse("dashboard:assets-list"))
        self.assertContains(resp, 'data-role="create-asset-link"')
        self.assertContains(resp, reverse("dashboard:asset-create"))


class AssetsListEmptyTest(_AuthenticatedClientMixin, TestCase):

    def test_empty_state_links_to_create(self):
        resp = self.client.get(reverse("dashboard:assets-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "data-role=\"assets-empty\"")
        self.assertContains(resp, reverse("dashboard:asset-create"))


# ── Stage 1: Asset (+ Site) ─────────────────────────────────────────────────

class Stage1AssetCreateTest(_AuthenticatedClientMixin, TestCase):
    """The Stage 1 form creates Asset (+ optional Site) only — no Device,
    Sensor, MetricDefinition, SensorMetric, or ThresholdRule may be
    created by this POST."""

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="ops-site", name="Ops Site")

    def _base_post(self, **overrides):
        data = {
            "site_mode": "existing",
            "existing_site": str(self.site.id),
            "name": "Stage 1 Asset",
            "asset_type": AssetType.OTHER,
            "status": OperationalStatus.UNKNOWN,
        }
        data.update(overrides)
        return data

    def test_get_returns_200(self):
        resp = self.client.get(reverse("dashboard:asset-create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "1. solis")
        self.assertContains(resp, 'data-role="asset-create-form"')

    def test_get_does_not_expose_code_field(self):
        # Spec §2: Asset.code must be system-generated. The form must
        # not give the operator any way to override it.
        resp = self.client.get(reverse("dashboard:asset-create"))
        html = resp.content.decode("utf-8")
        self.assertNotIn('name="code"', html)

    def test_get_does_not_expose_device_or_sensor_fields(self):
        # Per the staged workflow, those belong to Stage 2 / 3 / 4 —
        # not to the initial Asset form.
        resp = self.client.get(reverse("dashboard:asset-create"))
        html = resp.content.decode("utf-8")
        self.assertNotIn('name="new_device_uid"', html)
        self.assertNotIn('name="device_mode"', html)
        self.assertNotIn('name="sensor_type"', html)

    def test_post_creates_asset_with_existing_site(self):
        before = Asset.objects.count()
        resp = self.client.post(
            reverse("dashboard:asset-create"), data=self._base_post(),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Asset.objects.count(), before + 1)
        asset = Asset.objects.latest("created_at")
        self.assertTrue(asset.code.startswith("asset-"))
        self.assertEqual(asset.site, self.site)
        self.assertEqual(asset.name, "Stage 1 Asset")

    def test_post_redirects_to_configure_page(self):
        resp = self.client.post(
            reverse("dashboard:asset-create"), data=self._base_post(),
        )
        asset = Asset.objects.latest("created_at")
        self.assertEqual(
            resp["Location"],
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": asset.code}),
        )

    def test_post_ignores_user_supplied_code(self):
        # Even if the operator tampers with the HTML to send a ``code``
        # field, the view must overwrite it with the generated value.
        data = self._base_post(code="evil-code")
        resp = self.client.post(reverse("dashboard:asset-create"), data=data)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Asset.objects.filter(code="evil-code").exists())
        self.assertTrue(
            Asset.objects.filter(code__startswith="asset-").exists(),
        )

    def test_post_creates_new_site_with_dropdown_timezone(self):
        data = self._base_post(
            site_mode="new", existing_site="",
            new_site_code="new-site",
            new_site_name="New Site",
            new_site_timezone="Europe/Tallinn",
        )
        resp = self.client.post(reverse("dashboard:asset-create"), data=data)
        self.assertEqual(resp.status_code, 302)
        site = Site.objects.get(code="new-site")
        self.assertEqual(site.timezone, "Europe/Tallinn")

    def test_post_rejects_arbitrary_free_text_timezone(self):
        data = self._base_post(
            site_mode="new", existing_site="",
            new_site_code="bad-tz-site",
            new_site_name="Bad TZ",
            new_site_timezone="Foo/Bar",
        )
        resp = self.client.post(reverse("dashboard:asset-create"), data=data)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Site.objects.filter(code="bad-tz-site").exists())

    def test_post_rejects_duplicate_site_code(self):
        data = self._base_post(
            site_mode="new", existing_site="",
            new_site_code=self.site.code, new_site_name="Dup",
        )
        resp = self.client.post(reverse("dashboard:asset-create"), data=data)
        self.assertEqual(resp.status_code, 400)
        # No new asset must be created either.
        self.assertEqual(
            Site.objects.filter(code=self.site.code).count(), 1,
        )

    def test_post_does_not_create_devices_or_sensors(self):
        before_d = Device.objects.count()
        before_s = Sensor.objects.count()
        self.client.post(
            reverse("dashboard:asset-create"), data=self._base_post(),
        )
        self.assertEqual(Device.objects.count(), before_d)
        self.assertEqual(Sensor.objects.count(), before_s)

    def test_generated_asset_codes_are_unique(self):
        # Two consecutive submissions must yield different codes.
        self.client.post(
            reverse("dashboard:asset-create"), data=self._base_post(),
        )
        self.client.post(
            reverse("dashboard:asset-create"),
            data=self._base_post(name="Stage 1 Asset 2"),
        )
        codes = list(
            Asset.objects.order_by("created_at").values_list("code", flat=True)
        )
        self.assertEqual(len(set(codes)), len(codes))

    def test_post_invalid_form_returns_400(self):
        # No site_mode → form invalid.
        resp = self.client.post(reverse("dashboard:asset-create"), data={
            "name": "X", "asset_type": AssetType.OTHER,
        })
        self.assertEqual(resp.status_code, 400)


# ── Configure (Stage hub) page ──────────────────────────────────────────────

class ConfigurePageTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="cfg-site", name="Cfg Site")
        cls.asset = Asset.objects.create(
            site=cls.site, code="asset-cfg-1", name="Cfg Asset",
            asset_type=AssetType.OTHER,
        )
        cls.device = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="device-cfg-1",
            name="Cfg Device",
        )
        cls.sensor = Sensor.objects.create(
            device=cls.device, code="sensor-cfg-1", name="Cfg Sensor",
        )
        cls.metric = MetricDefinition.objects.create(
            key="cfg_metric", display_name="Cfg", unit="",
        )
        cls.sensor_metric = SensorMetric.objects.create(
            sensor=cls.sensor, metric=cls.metric,
        )
        cls.rule = ThresholdRule.objects.create(
            code="rule-cfg-1", name="Cfg Rule", metric=cls.metric,
            site=cls.site, asset=cls.asset, device=cls.device,
            sensor=cls.sensor, lower_bound=1.0, upper_bound=10.0,
            severity=Severity.WARNING,
        )

    def _url(self):
        return reverse("dashboard:asset-configure",
                       kwargs={"asset_code": self.asset.code})

    def test_returns_200(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_unknown_asset_returns_404(self):
        resp = self.client.get(
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": "missing-code"})
        )
        self.assertEqual(resp.status_code, 404)

    def test_shows_asset_identity(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, self.asset.code)
        self.assertContains(resp, self.asset.name)
        self.assertContains(resp, self.site.code)

    def test_shows_devices_with_sensors_and_metrics(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, self.device.device_uid)
        self.assertContains(resp, self.sensor.code)
        self.assertContains(resp, self.metric.key)
        self.assertContains(resp, 'data-role="device-card"')
        self.assertContains(resp, 'data-role="sensor-row"')

    def test_shows_threshold_rules(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, self.rule.code)
        self.assertContains(resp, 'data-role="rule-row"')

    def test_links_to_device_create_and_attach(self):
        resp = self.client.get(self._url())
        self.assertContains(
            resp,
            reverse("dashboard:device-create",
                    kwargs={"asset_code": self.asset.code}),
        )
        self.assertContains(
            resp,
            reverse("dashboard:device-attach",
                    kwargs={"asset_code": self.asset.code}),
        )

    def test_links_to_sensor_create_for_each_device(self):
        resp = self.client.get(self._url())
        self.assertContains(
            resp,
            reverse("dashboard:sensor-create", kwargs={
                "asset_code": self.asset.code,
                "device_uid": self.device.device_uid,
            }),
        )

    def test_links_to_metric_create_for_each_sensor(self):
        resp = self.client.get(self._url())
        self.assertContains(
            resp,
            reverse("dashboard:sensor-metric-create", kwargs={
                "asset_code": self.asset.code,
                "device_uid": self.device.device_uid,
                "sensor_code": self.sensor.code,
            }),
        )

    def test_links_back_to_monitoring_detail(self):
        resp = self.client.get(self._url())
        self.assertContains(
            resp,
            reverse("dashboard:asset-detail",
                    kwargs={"asset_identifier": self.asset.code}),
        )

    def test_empty_state_when_asset_has_no_devices(self):
        empty_asset = Asset.objects.create(
            site=self.site, code="asset-cfg-empty", name="Empty",
            asset_type=AssetType.OTHER,
        )
        resp = self.client.get(
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": empty_asset.code})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-role="devices-empty"')


# ── Stage 2: Device ─────────────────────────────────────────────────────────

class Stage2DeviceCreateTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="d2-site", name="D2 Site")
        cls.asset = Asset.objects.create(
            site=cls.site, code="asset-d2-1", name="A", asset_type=AssetType.OTHER,
        )

    def _url(self):
        return reverse("dashboard:device-create",
                       kwargs={"asset_code": self.asset.code})

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_get_does_not_expose_device_uid(self):
        resp = self.client.get(self._url())
        self.assertNotIn('name="device_uid"', resp.content.decode("utf-8"))

    def test_post_creates_device_with_generated_uid(self):
        resp = self.client.post(self._url(), data={
            "name": "New D", "device_type": "charger",
            "expected_interval_seconds": 60,
        })
        self.assertEqual(resp.status_code, 302)
        device = Device.objects.get(asset=self.asset, name="New D")
        self.assertTrue(device.device_uid.startswith("device-"))
        self.assertEqual(device.site, self.site)
        self.assertEqual(
            resp["Location"],
            reverse("dashboard:asset-configure",
                    kwargs={"asset_code": self.asset.code}),
        )

    def test_post_ignores_user_supplied_device_uid(self):
        # Tamper with HTML to inject device_uid — view must drop it.
        resp = self.client.post(self._url(), data={
            "name": "Tampered",
            "device_uid": "EVIL-UID",
            "expected_interval_seconds": 60,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Device.objects.filter(device_uid="EVIL-UID").exists())

    def test_post_invalid_returns_400(self):
        resp = self.client.post(self._url(), data={})
        self.assertEqual(resp.status_code, 400)

    def test_multiple_devices_get_unique_uids(self):
        self.client.post(self._url(), data={
            "name": "D1", "expected_interval_seconds": 60,
        })
        self.client.post(self._url(), data={
            "name": "D2", "expected_interval_seconds": 60,
        })
        uids = list(
            Device.objects.filter(asset=self.asset).values_list("device_uid", flat=True)
        )
        self.assertEqual(len(set(uids)), 2)


class Stage2DeviceAttachTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="att-site", name="Attach Site")
        cls.other_site = Site.objects.create(code="att-other", name="Other")
        cls.asset = Asset.objects.create(
            site=cls.site, code="asset-att-1", name="A", asset_type=AssetType.OTHER,
        )
        cls.unassigned_same = Device.objects.create(
            site=cls.site, device_uid="device-att-free", name="Free",
        )
        cls.assigned = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="device-att-claimed",
            name="Claimed",
        )
        cls.cross_site = Device.objects.create(
            site=cls.other_site, device_uid="device-att-cross", name="Cross",
        )

    def _url(self):
        return reverse("dashboard:device-attach",
                       kwargs={"asset_code": self.asset.code})

    def test_post_attaches_unassigned_same_site(self):
        resp = self.client.post(self._url(), data={
            "existing_device": str(self.unassigned_same.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.unassigned_same.refresh_from_db()
        self.assertEqual(self.unassigned_same.asset, self.asset)

    def test_post_rejects_already_assigned_device(self):
        resp = self.client.post(self._url(), data={
            "existing_device": str(self.assigned.id),
        })
        self.assertEqual(resp.status_code, 400)
        self.assigned.refresh_from_db()
        # The already-assigned device must stay on its asset.
        self.assertEqual(self.assigned.asset, self.asset)

    def test_post_rejects_cross_site_device(self):
        resp = self.client.post(self._url(), data={
            "existing_device": str(self.cross_site.id),
        })
        self.assertEqual(resp.status_code, 400)
        self.cross_site.refresh_from_db()
        self.assertIsNone(self.cross_site.asset)


# ── Stage 3: Sensor ─────────────────────────────────────────────────────────

class Stage3SensorCreateTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="s3-site", name="S3 Site")
        cls.asset = Asset.objects.create(
            site=cls.site, code="asset-s3-1", name="A", asset_type=AssetType.OTHER,
        )
        cls.device = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="device-s3-1", name="D",
        )
        cls.metric = MetricDefinition.objects.create(
            key="s3_metric", display_name="S3", unit="",
        )
        cls.preset = SensorMetricPreset.objects.create(
            code="s3-preset", name="S3 Preset",
            sensor_type="temperature", metric=cls.metric,
            default_sensor_name="Auto Sensor",
        )

    def _url(self):
        return reverse("dashboard:sensor-create", kwargs={
            "asset_code": self.asset.code,
            "device_uid": self.device.device_uid,
        })

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_get_does_not_expose_sensor_code(self):
        # The Sensor.code is system-generated.
        resp = self.client.get(self._url())
        self.assertNotIn('name="code"', resp.content.decode("utf-8"))

    def test_post_creates_sensor_with_generated_code(self):
        resp = self.client.post(self._url(), data={
            "name": "Plain Sensor", "sensor_type": "temperature",
        })
        self.assertEqual(resp.status_code, 302)
        sensor = Sensor.objects.get(device=self.device, name="Plain Sensor")
        self.assertTrue(sensor.code.startswith("sensor-"))

    def test_post_redirects_to_stage_4(self):
        resp = self.client.post(self._url(), data={"name": "Plain"})
        sensor = Sensor.objects.get(device=self.device, name="Plain")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(
            reverse("dashboard:sensor-metric-create", kwargs={
                "asset_code": self.asset.code,
                "device_uid": self.device.device_uid,
                "sensor_code": sensor.code,
            })
        ))

    def test_post_with_preset_fills_in_blanks(self):
        resp = self.client.post(self._url(), data={"preset": str(self.preset.id)})
        self.assertEqual(resp.status_code, 302)
        sensor = Sensor.objects.get(device=self.device, name="Auto Sensor")
        self.assertEqual(sensor.sensor_type, "temperature")
        # And the redirect should include the preset code so Stage 4 can
        # pre-fill the metric.
        self.assertIn("preset=", resp["Location"])

    def test_post_requires_name_when_no_preset(self):
        resp = self.client.post(self._url(), data={"sensor_type": "temperature"})
        self.assertEqual(resp.status_code, 400)

    def test_multiple_sensors_get_unique_codes(self):
        self.client.post(self._url(), data={"name": "S1"})
        self.client.post(self._url(), data={"name": "S2"})
        codes = list(
            Sensor.objects.filter(device=self.device).values_list("code", flat=True)
        )
        self.assertEqual(len(codes), 2)
        self.assertEqual(len(set(codes)), 2)

    def test_post_ignores_user_supplied_code(self):
        self.client.post(self._url(), data={
            "name": "Plain", "code": "EVIL-CODE",
        })
        self.assertFalse(Sensor.objects.filter(code="EVIL-CODE").exists())


# ── Stage 4: SensorMetric + ThresholdRule ───────────────────────────────────

class Stage4SensorMetricCreateTest(_AuthenticatedClientMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="s4-site", name="S4 Site")
        cls.asset = Asset.objects.create(
            site=cls.site, code="asset-s4-1", name="A", asset_type=AssetType.OTHER,
        )
        cls.device = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="device-s4-1", name="D",
        )
        cls.sensor = Sensor.objects.create(
            device=cls.device, code="sensor-s4-1", name="S",
        )
        cls.metric = MetricDefinition.objects.create(
            key="existing_metric", display_name="Existing", unit="",
        )
        cls.sm_preset = SensorMetricPreset.objects.create(
            code="s4-sm-preset", name="S4 SM Preset",
            sensor_type="temperature", metric=cls.metric,
        )
        cls.tr_preset = ThresholdRulePreset.objects.create(
            code="s4-tr-preset", name="S4 TR Preset", metric=cls.metric,
            lower_bound=-10.0, upper_bound=50.0, severity=Severity.WARNING,
        )

    def _url(self, sensor=None):
        sensor = sensor or self.sensor
        return reverse("dashboard:sensor-metric-create", kwargs={
            "asset_code": self.asset.code,
            "device_uid": self.device.device_uid,
            "sensor_code": sensor.code,
        })

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_post_links_existing_metric(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "none",
        })
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.assertTrue(
            SensorMetric.objects.filter(
                sensor=self.sensor, metric=self.metric,
            ).exists()
        )

    def test_post_creates_new_metric(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "new",
            "new_metric_key": "brand_new",
            "new_metric_display_name": "Brand New",
            "new_metric_data_type": "float",
            "threshold_mode": "none",
        })
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        metric = MetricDefinition.objects.get(key="brand_new")
        self.assertTrue(SensorMetric.objects.filter(
            sensor=self.sensor, metric=metric,
        ).exists())

    def test_post_rejects_duplicate_sensor_metric(self):
        SensorMetric.objects.create(sensor=self.sensor, metric=self.metric)
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "none",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            SensorMetric.objects.filter(
                sensor=self.sensor, metric=self.metric,
            ).count(), 1,
        )

    def test_post_creates_threshold_rule_manual(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_name": "Manual Rule",
            "threshold_lower_bound": "0.0",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
            "threshold_close_when_normal": "on",
        })
        self.assertEqual(resp.status_code, 302, msg=resp.content[:2000])
        rule = ThresholdRule.objects.get(name="Manual Rule")
        self.assertTrue(rule.code.startswith("rule-"))
        self.assertEqual(rule.asset, self.asset)
        self.assertEqual(rule.device, self.device)
        self.assertEqual(rule.sensor, self.sensor)
        self.assertEqual(rule.metric, self.metric)
        self.assertEqual(rule.site, self.site)

    def test_manual_threshold_rule_is_sensor_scoped(self):
        # Phase 7 bugfix: Stage 4 must always create sensor-scoped rules
        # so a threshold "for one sensor" never silently fires on another.
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_name": "Scope Manual",
            "threshold_lower_bound": "0.0",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
            "threshold_close_when_normal": "on",
        })
        rule = ThresholdRule.objects.get(name="Scope Manual")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.SENSOR)

    def test_post_manual_threshold_requires_at_least_one_bound(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_name": "Bound-less",
            "threshold_severity": Severity.WARNING,
        })
        self.assertEqual(resp.status_code, 400)
        # No partial state should remain.
        self.assertFalse(
            SensorMetric.objects.filter(
                sensor=self.sensor, metric=self.metric,
            ).exists()
        )

    def test_post_manual_threshold_rejects_inverted_bounds(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_name": "Inverted",
            "threshold_lower_bound": "100.0",
            "threshold_upper_bound": "10.0",
            "threshold_severity": Severity.WARNING,
        })
        self.assertEqual(resp.status_code, 400)

    def test_post_creates_threshold_rule_from_preset(self):
        resp = self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "preset",
            "threshold_preset": str(self.tr_preset.id),
        })
        self.assertEqual(resp.status_code, 302, msg=resp.content[:2000])
        rule = ThresholdRule.objects.get(name=self.tr_preset.name)
        self.assertEqual(rule.lower_bound, self.tr_preset.lower_bound)
        self.assertEqual(rule.upper_bound, self.tr_preset.upper_bound)
        self.assertEqual(rule.sensor, self.sensor)

    def test_preset_threshold_rule_is_sensor_scoped(self):
        # ThresholdRulePreset itself has no scope; materialising it from a
        # sensor configuration page must always yield a sensor-scoped rule.
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "preset",
            "threshold_preset": str(self.tr_preset.id),
        })
        rule = ThresholdRule.objects.get(name=self.tr_preset.name)
        self.assertEqual(rule.scope_level, ThresholdRuleScope.SENSOR)
        self.assertEqual(rule.sensor, self.sensor)
        self.assertEqual(rule.device, self.device)
        self.assertEqual(rule.asset, self.asset)
        self.assertEqual(rule.site, self.site)

    # ── Explicit scope picker on Stage 4 (Phase 7 follow-up) ───────────

    def test_form_renders_scope_picker(self):
        # The Stage 4 page must surface a threshold_scope_level control so
        # operators can broaden the scope without dropping into admin.
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("threshold_scope_level", body)
        # All five scope choices should be available in the dropdown.
        for scope_value in ("sensor", "device", "asset", "site", "global"):
            self.assertIn(f'value="{scope_value}"', body)

    def test_manual_threshold_with_device_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_scope_level": ThresholdRuleScope.DEVICE,
            "threshold_name": "Device-wide rule",
            "threshold_lower_bound": "0.0",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
        })
        rule = ThresholdRule.objects.get(name="Device-wide rule")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.DEVICE)
        self.assertEqual(rule.device, self.device)
        self.assertIsNone(rule.sensor)
        # Auto-fill from device should still populate asset+site.
        self.assertEqual(rule.asset, self.asset)
        self.assertEqual(rule.site, self.site)

    def test_manual_threshold_with_asset_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_scope_level": ThresholdRuleScope.ASSET,
            "threshold_name": "Asset-wide rule",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
        })
        rule = ThresholdRule.objects.get(name="Asset-wide rule")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.ASSET)
        self.assertEqual(rule.asset, self.asset)
        self.assertEqual(rule.site, self.site)
        self.assertIsNone(rule.device)
        self.assertIsNone(rule.sensor)

    def test_manual_threshold_with_site_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_scope_level": ThresholdRuleScope.SITE,
            "threshold_name": "Site-wide rule",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
        })
        rule = ThresholdRule.objects.get(name="Site-wide rule")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.SITE)
        self.assertEqual(rule.site, self.site)
        self.assertIsNone(rule.asset)
        self.assertIsNone(rule.device)
        self.assertIsNone(rule.sensor)

    def test_manual_threshold_with_global_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_scope_level": ThresholdRuleScope.GLOBAL,
            "threshold_name": "Global rule",
            "threshold_upper_bound": "200.0",
            "threshold_severity": Severity.WARNING,
        })
        rule = ThresholdRule.objects.get(name="Global rule")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.GLOBAL)
        self.assertIsNone(rule.site)
        self.assertIsNone(rule.asset)
        self.assertIsNone(rule.device)
        self.assertIsNone(rule.sensor)

    def test_preset_threshold_honours_scope_picker(self):
        # Preset materialisation must also respect the operator's
        # explicit scope choice (it is no longer hardcoded to sensor).
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "preset",
            "threshold_preset": str(self.tr_preset.id),
            "threshold_scope_level": ThresholdRuleScope.DEVICE,
        })
        rule = ThresholdRule.objects.get(name=self.tr_preset.name)
        self.assertEqual(rule.scope_level, ThresholdRuleScope.DEVICE)
        self.assertEqual(rule.device, self.device)
        self.assertIsNone(rule.sensor)

    def test_default_scope_is_still_sensor(self):
        # No ``threshold_scope_level`` in POST → backwards-compatible default.
        from apps.analytics.models import ThresholdRuleScope
        self.client.post(self._url(), data={
            "metric_mode": "existing",
            "existing_metric": str(self.metric.id),
            "threshold_mode": "manual",
            "threshold_name": "Default-scope rule",
            "threshold_upper_bound": "100.0",
            "threshold_severity": Severity.WARNING,
        })
        rule = ThresholdRule.objects.get(name="Default-scope rule")
        self.assertEqual(rule.scope_level, ThresholdRuleScope.SENSOR)
        self.assertEqual(rule.sensor, self.sensor)

    def test_post_uses_sensor_metric_preset_metric(self):
        sensor2 = Sensor.objects.create(
            device=self.device, code="sensor-s4-2", name="S2",
        )
        resp = self.client.post(self._url(sensor=sensor2), data={
            "metric_mode": "preset",
            "sensor_metric_preset": str(self.sm_preset.id),
            "threshold_mode": "none",
        })
        self.assertEqual(resp.status_code, 302, msg=resp.content[:2000])
        sm = SensorMetric.objects.get(sensor=sensor2, metric=self.metric)
        self.assertEqual(sm.metric, self.sm_preset.metric)


# ── Per-stage transaction independence ──────────────────────────────────────

class PerStageTransactionTest(_AuthenticatedClientMixin, TestCase):
    """Stage N failure must not undo stages 1..N-1."""

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="tx-site", name="TX Site")

    def test_stage_4_validation_failure_keeps_asset_device_sensor(self):
        # Stage 1
        self.client.post(reverse("dashboard:asset-create"), data={
            "site_mode": "existing", "existing_site": str(self.site.id),
            "name": "TX Asset", "asset_type": AssetType.OTHER,
        })
        asset = Asset.objects.get(name="TX Asset")
        # Stage 2
        self.client.post(
            reverse("dashboard:device-create",
                    kwargs={"asset_code": asset.code}),
            data={"name": "TX Device", "expected_interval_seconds": 60},
        )
        device = Device.objects.get(name="TX Device")
        # Stage 3
        self.client.post(
            reverse("dashboard:sensor-create", kwargs={
                "asset_code": asset.code, "device_uid": device.device_uid,
            }),
            data={"name": "TX Sensor"},
        )
        sensor = Sensor.objects.get(name="TX Sensor")
        # Stage 4 — invalid (manual threshold without bounds)
        before_sm = SensorMetric.objects.count()
        before_metrics = MetricDefinition.objects.count()
        metric = MetricDefinition.objects.create(
            key="tx_metric", display_name="TX", unit="",
        )
        resp = self.client.post(
            reverse("dashboard:sensor-metric-create", kwargs={
                "asset_code": asset.code, "device_uid": device.device_uid,
                "sensor_code": sensor.code,
            }),
            data={
                "metric_mode": "existing",
                "existing_metric": str(metric.id),
                "threshold_mode": "manual",
                "threshold_name": "Bad",
                "threshold_severity": Severity.WARNING,
                # No bounds → 400.
            },
        )
        self.assertEqual(resp.status_code, 400)
        # Stages 1-3 survived.
        self.assertTrue(Asset.objects.filter(code=asset.code).exists())
        self.assertTrue(Device.objects.filter(device_uid=device.device_uid).exists())
        self.assertTrue(Sensor.objects.filter(code=sensor.code).exists())
        # Stage 4 must not have committed anything (no SensorMetric).
        self.assertEqual(SensorMetric.objects.count(), before_sm)
        # The metric was created out-of-band before the POST and survives;
        # what must not happen is the *form-driven* new metric.
        self.assertEqual(
            MetricDefinition.objects.count(), before_metrics + 1,
        )

    def test_stage_2_failure_keeps_asset(self):
        # Stage 1
        self.client.post(reverse("dashboard:asset-create"), data={
            "site_mode": "existing", "existing_site": str(self.site.id),
            "name": "Standalone", "asset_type": AssetType.OTHER,
        })
        asset = Asset.objects.get(name="Standalone")
        # Stage 2 — invalid (no name)
        resp = self.client.post(
            reverse("dashboard:device-create",
                    kwargs={"asset_code": asset.code}),
            data={"expected_interval_seconds": 60},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Asset.objects.filter(code=asset.code).exists())
        self.assertEqual(Device.objects.filter(asset=asset).count(), 0)

    def test_stage_3_failure_keeps_device(self):
        # Build asset + device
        self.client.post(reverse("dashboard:asset-create"), data={
            "site_mode": "existing", "existing_site": str(self.site.id),
            "name": "S3 Parent", "asset_type": AssetType.OTHER,
        })
        asset = Asset.objects.get(name="S3 Parent")
        self.client.post(
            reverse("dashboard:device-create",
                    kwargs={"asset_code": asset.code}),
            data={"name": "S3 D", "expected_interval_seconds": 60},
        )
        device = Device.objects.get(name="S3 D")
        # Stage 3 — invalid (no name, no preset)
        resp = self.client.post(
            reverse("dashboard:sensor-create", kwargs={
                "asset_code": asset.code, "device_uid": device.device_uid,
            }),
            data={"sensor_type": "temperature"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Device.objects.filter(device_uid=device.device_uid).exists())
        self.assertEqual(Sensor.objects.filter(device=device).count(), 0)


# ── Preset models ───────────────────────────────────────────────────────────

class SensorMetricPresetModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.metric = MetricDefinition.objects.create(
            key="p_metric", display_name="P", unit="",
        )

    def test_create_basic_preset(self):
        preset = SensorMetricPreset.objects.create(
            code="t-preset", name="T Preset", metric=self.metric,
            sensor_type="temperature",
        )
        self.assertEqual(str(preset), "t-preset → p_metric")
        self.assertTrue(preset.is_active)

    def test_unique_code(self):
        SensorMetricPreset.objects.create(
            code="dup-preset", name="P1", metric=self.metric,
        )
        with self.assertRaises(Exception):  # IntegrityError or ValidationError
            SensorMetricPreset.objects.create(
                code="dup-preset", name="P2", metric=self.metric,
            )


class ThresholdRulePresetModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.metric = MetricDefinition.objects.create(
            key="tr_metric", display_name="TR", unit="",
        )

    def test_create_with_lower_bound_only(self):
        preset = ThresholdRulePreset.objects.create(
            code="lo-only", name="Lo Only", metric=self.metric,
            lower_bound=10.0, severity=Severity.WARNING,
        )
        self.assertEqual(preset.lower_bound, 10.0)
        self.assertIsNone(preset.upper_bound)

    def test_create_with_upper_bound_only(self):
        preset = ThresholdRulePreset.objects.create(
            code="hi-only", name="Hi Only", metric=self.metric,
            upper_bound=10.0, severity=Severity.WARNING,
        )
        self.assertIsNone(preset.lower_bound)
        self.assertEqual(preset.upper_bound, 10.0)

    def test_requires_at_least_one_bound(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ThresholdRulePreset.objects.create(
                code="bad", name="Bad", metric=self.metric,
                severity=Severity.WARNING,
            )

    def test_rejects_inverted_bounds(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ThresholdRulePreset.objects.create(
                code="inv", name="Inv", metric=self.metric,
                lower_bound=100.0, upper_bound=10.0,
                severity=Severity.WARNING,
            )


# ── Phase 7, Task 4A: Event & anomaly review pages ─────────────────────────

class _EventsPageBase(_AuthenticatedClientMixin, TestCase):
    """Shared fixture for the events list + detail page tests."""

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(code="ev-site", name="Ev Site")
        cls.asset = Asset.objects.create(
            site=cls.site, code="ev-asset", name="Ev Asset",
            asset_type=AssetType.OTHER,
        )
        cls.device = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="ev-device-1", name="D",
        )
        cls.sensor = Sensor.objects.create(
            device=cls.device, code="ev-sensor-1", name="S",
        )
        cls.metric = MetricDefinition.objects.create(
            key="ev_metric_c", display_name="Ev", unit="°C",
        )
        cls.event = Event.objects.create(
            event_type=EventType.THRESHOLD_ANOMALY,
            severity=Severity.WARNING, status=EventStatus.OPEN,
            site=cls.site, asset=cls.asset, device=cls.device,
            sensor=cls.sensor, metric=cls.metric,
            title="Ev threshold anomaly",
            source="threshold_service",
            payload={"value": 75.0, "limit": 60.0},
        )


class EventsListPageTest(_EventsPageBase):

    URL = "/dashboard/events/"

    def test_get_returns_200_for_authenticated_user(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)

    def test_post_returns_405(self):
        resp = self.client.post(self.URL, data={})
        self.assertEqual(resp.status_code, 405)

    def test_uses_expected_template(self):
        resp = self.client.get(self.URL)
        names = [t.name for t in resp.templates if t.name]
        self.assertIn("dashboard/events_list.html", names)
        self.assertIn("dashboard/base.html", names)

    def test_page_contains_static_assets(self):
        resp = self.client.get(self.URL)
        self.assertContains(resp, "dashboard/dashboard.css")
        self.assertContains(resp, "dashboard/dashboard.js")

    def test_config_block_contains_events_api_endpoint(self):
        resp = self.client.get(self.URL)
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "events-list-config",
        )
        self.assertEqual(cfg["endpoints"]["events"], "/api/events/")
        self.assertEqual(cfg["defaultLimit"], 100)
        self.assertEqual(cfg["maxLimit"], 1000)

    def test_config_block_carries_detail_url_template(self):
        resp = self.client.get(self.URL)
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "events-list-config",
        )
        self.assertIn("__ID__", cfg["eventDetailUrlTemplate"])
        self.assertIn("/dashboard/events/", cfg["eventDetailUrlTemplate"])
        self.assertIn("__CODE__", cfg["assetDetailUrlTemplate"])

    def test_config_block_exposes_choice_lists(self):
        resp = self.client.get(self.URL)
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "events-list-config",
        )
        self.assertIn(EventStatus.OPEN, cfg["choices"]["status"])
        self.assertIn(EventType.THRESHOLD_ANOMALY, cfg["choices"]["event_type"])
        self.assertIn(Severity.WARNING, cfg["choices"]["severity"])

    def test_filter_controls_present(self):
        resp = self.client.get(self.URL)
        for role in (
            "filter-status", "filter-event_type", "filter-severity",
            "filter-asset", "filter-device", "filter-sensor",
            "filter-metric", "filter-from", "filter-to", "filter-limit",
            "events-apply", "events-reset", "events-refresh",
            "events-table-wrapper", "events-loading",
            "events-empty", "events-error",
        ):
            self.assertContains(resp, f'data-role="{role}"', msg_prefix=role)

    def test_filter_selects_include_documented_choices(self):
        # Choices are rendered server-side so the HTML form is functional
        # without JS. The dashboard tests can pin a subset.
        resp = self.client.get(self.URL)
        for value in (
            EventStatus.OPEN, EventType.THRESHOLD_ANOMALY,
            Severity.WARNING, Severity.ERROR,
        ):
            self.assertContains(resp, f'value="{value}"')


class EventDetailPageTest(_EventsPageBase):

    def _url(self):
        return f"/dashboard/events/{self.event.id}/"

    def test_authenticated_get_returns_200(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_unknown_event_id_returns_404(self):
        bogus = "00000000-0000-0000-0000-000000000000"
        resp = self.client.get(f"/dashboard/events/{bogus}/")
        self.assertEqual(resp.status_code, 404)

    def test_post_returns_405(self):
        resp = self.client.post(self._url(), data={})
        self.assertEqual(resp.status_code, 405)

    def test_uses_expected_template(self):
        resp = self.client.get(self._url())
        names = [t.name for t in resp.templates if t.name]
        self.assertIn("dashboard/event_detail.html", names)

    def test_config_contains_event_id(self):
        resp = self.client.get(self._url())
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "event-detail-config",
        )
        self.assertEqual(cfg["eventId"], str(self.event.id))

    def test_config_contains_event_detail_url(self):
        resp = self.client.get(self._url())
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "event-detail-config",
        )
        self.assertEqual(
            cfg["eventDetailUrl"], f"/api/events/{self.event.id}/",
        )

    def test_config_contains_measurements_url(self):
        resp = self.client.get(self._url())
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "event-detail-config",
        )
        self.assertEqual(cfg["measurementsUrl"], "/api/measurements/")

    def test_config_contains_documented_period_buttons(self):
        resp = self.client.get(self._url())
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "event-detail-config",
        )
        period_ids = [p["id"] for p in cfg["periods"]]
        for required in ("1h", "6h", "24h", "7d"):
            self.assertIn(required, period_ids)

    def test_config_contains_asset_detail_url_template(self):
        resp = self.client.get(self._url())
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "event-detail-config",
        )
        self.assertIn("__CODE__", cfg["assetDetailUrlTemplate"])

    def test_page_links_back_to_events_list(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-role="events-list-link"')
        self.assertContains(resp, "/dashboard/events/")

    def test_page_contains_required_section_roots(self):
        resp = self.client.get(self._url())
        for role in (
            "event-identity", "event-context",
            "event-measurement", "event-payload",
            "event-timeline-section", "period-buttons",
            "timeline-chart", "timeline-summary",
            "timeline-from", "timeline-to", "timeline-apply",
        ):
            self.assertContains(resp, f'data-role="{role}"', msg_prefix=role)


class SeedDemoDataPresetsTest(TestCase):
    """Seeding must create the documented presets idempotently."""

    def test_seed_creates_presets_idempotently(self):
        from django.core.management import call_command
        call_command("seed_demo_data")
        first_sm = SensorMetricPreset.objects.count()
        first_tr = ThresholdRulePreset.objects.count()
        self.assertGreaterEqual(first_sm, 4)
        self.assertGreaterEqual(first_tr, 3)
        # Re-run — count must stay the same.
        call_command("seed_demo_data")
        self.assertEqual(SensorMetricPreset.objects.count(), first_sm)
        self.assertEqual(ThresholdRulePreset.objects.count(), first_tr)
        # Spot-check a documented preset.
        self.assertTrue(
            SensorMetricPreset.objects.filter(
                code="temperature_sensor_preset",
            ).exists()
        )
        self.assertTrue(
            ThresholdRulePreset.objects.filter(
                code="outdoor_temperature_range",
            ).exists()
        )


# ── ThresholdRule edit page (Phase 7 bugfix follow-up) ──────────────────────

class ThresholdRuleEditPageTest(_AuthenticatedClientMixin, TestCase):
    """
    Per-asset operator edit page for ``ThresholdRule``. The route is
    anchored on the asset so the view rejects rules that are not
    reachable from that asset (4xx instead of silent cross-asset edit).
    """

    @classmethod
    def setUpTestData(cls):
        from apps.analytics.models import ThresholdRule, ThresholdRuleScope
        from apps.assets.models import SensorMetric

        cls.site = Site.objects.create(code="rule-edit-site", name="RES")
        cls.asset = Asset.objects.create(
            site=cls.site, code="rule-edit-asset", name="REA",
            asset_type=AssetType.OTHER,
        )
        cls.device = Device.objects.create(
            site=cls.site, asset=cls.asset, device_uid="rule-edit-dev", name="RED",
        )
        cls.sensor = Sensor.objects.create(
            device=cls.device, code="rule-edit-sensor", name="RES",
        )
        cls.other_sensor = Sensor.objects.create(
            device=cls.device, code="rule-edit-sensor-2", name="RES2",
        )
        cls.metric = MetricDefinition.objects.create(
            key="re_metric", display_name="RE", unit="",
        )
        SensorMetric.objects.create(sensor=cls.sensor, metric=cls.metric)
        SensorMetric.objects.create(sensor=cls.other_sensor, metric=cls.metric)
        cls.rule = ThresholdRule.objects.create(
            code="re-rule-001",
            name="Edit me",
            metric=cls.metric,
            scope_level=ThresholdRuleScope.SENSOR,
            sensor=cls.sensor,
            upper_bound=80.0,
            severity=Severity.WARNING,
        )

        # An unrelated asset/sensor whose rule must NOT be reachable
        # from ``self.asset`` — used to verify the cross-asset 404.
        cls.other_site = Site.objects.create(code="other-site-2", name="OS2")
        cls.other_asset = Asset.objects.create(
            site=cls.other_site, code="other-asset-2", name="OA2",
            asset_type=AssetType.OTHER,
        )
        cls.other_device = Device.objects.create(
            site=cls.other_site, asset=cls.other_asset,
            device_uid="other-dev-2", name="OD2",
        )
        cls.foreign_sensor = Sensor.objects.create(
            device=cls.other_device, code="foreign", name="F",
        )
        SensorMetric.objects.create(
            sensor=cls.foreign_sensor, metric=cls.metric,
        )
        cls.foreign_rule = ThresholdRule.objects.create(
            code="foreign-rule",
            name="Foreign",
            metric=cls.metric,
            scope_level=ThresholdRuleScope.SENSOR,
            sensor=cls.foreign_sensor,
            upper_bound=80.0,
            severity=Severity.WARNING,
        )

    def _url(self, rule=None, asset=None):
        rule = rule or self.rule
        asset = asset or self.asset
        return reverse("dashboard:threshold-rule-edit", kwargs={
            "asset_code": asset.code, "rule_code": rule.code,
        })

    # ── Authentication / authorisation ─────────────────────────────────

    def test_get_returns_200_for_authenticated_user(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_unknown_rule_returns_404(self):
        url = reverse("dashboard:threshold-rule-edit", kwargs={
            "asset_code": self.asset.code, "rule_code": "does-not-exist",
        })
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_cross_asset_rule_returns_404(self):
        # ``foreign_rule`` belongs to another asset; the URL anchored on
        # ``self.asset`` must not be able to edit it.
        url = self._url(rule=self.foreign_rule)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unknown_asset_returns_404(self):
        url = reverse("dashboard:threshold-rule-edit", kwargs={
            "asset_code": "no-such-asset", "rule_code": self.rule.code,
        })
        self.assertEqual(self.client.get(url).status_code, 404)

    # ── Listing / link wiring ──────────────────────────────────────────

    def test_configure_page_links_to_edit(self):
        # The edit link must appear in the asset-configure rule table so
        # operators can discover it without typing the URL.
        resp = self.client.get(reverse(
            "dashboard:asset-configure",
            kwargs={"asset_code": self.asset.code},
        ))
        self.assertContains(resp, self._url())
        self.assertContains(resp, "Rediģēt")

    def test_configure_page_includes_scope_badge(self):
        resp = self.client.get(reverse(
            "dashboard:asset-configure",
            kwargs={"asset_code": self.asset.code},
        ))
        self.assertContains(resp, "badge--scope-sensor")

    # ── POST: bounds / severity / name edits ──────────────────────────

    def _base_post(self, **overrides):
        data = {
            "name": "Updated name",
            "description": "",
            "scope_level": "sensor",
            "sensor": str(self.sensor.id),
            "device": "",
            "lower_bound": "",
            "upper_bound": "95",
            "severity": Severity.WARNING,
            "close_when_normal": "on",
            "is_enabled": "on",
            "sort_order": "0",
            "message_template": "",
        }
        data.update(overrides)
        return data

    def test_post_updates_name_and_bounds(self):
        resp = self.client.post(self._url(), data=self._base_post(
            name="Renamed", upper_bound="120",
        ))
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.name, "Renamed")
        self.assertEqual(self.rule.upper_bound, 120.0)

    def test_post_toggles_is_enabled(self):
        # ``is_enabled`` omitted → unchecked checkbox.
        data = self._base_post()
        data.pop("is_enabled")
        self.client.post(self._url(), data=data)
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_enabled)

    def test_disabling_rule_closes_its_open_event_via_edit_form(self):
        # End-to-end coverage of the auto-close-on-disable hook: open a
        # threshold event for the rule, POST the edit form with the
        # ``is_enabled`` checkbox unchecked, and assert the event was
        # closed with ``closed_reason='rule_disabled'``. This is the
        # exact workflow operators will use from the dashboard.
        from apps.assets.models import SensorMetric
        from apps.analytics.services.thresholds import (
            evaluate_measurement_thresholds,
        )
        from apps.events.models import Event, EventStatus
        from apps.telemetry.models import (
            Measurement, MeasurementQuality, RawMessage, SourceType,
        )
        from django.utils import timezone

        SensorMetric.objects.get_or_create(
            sensor=self.sensor, metric=self.metric,
        )
        rm = RawMessage.objects.create(
            source_type=SourceType.MQTT,
            topic="dashboard-edit-test",
            payload={"message_id": "edit-disable-test"},
            message_id="edit-disable-test",
            device_uid=self.device.device_uid,
            site=self.site, asset=self.asset, device=self.device,
            received_at=timezone.now(),
        )
        m = Measurement.objects.create(
            site=self.site, asset=self.asset, device=self.device,
            sensor=self.sensor, metric=self.metric, raw_message=rm,
            timestamp=timezone.now(), value_float=200.0, unit="",
            quality=MeasurementQuality.GOOD,
        )
        evaluate_measurement_thresholds(m)
        event = Event.objects.get(payload__rule_code=self.rule.code)
        self.assertEqual(event.status, EventStatus.OPEN)

        data = self._base_post()
        data.pop("is_enabled")  # checkbox unchecked
        resp = self.client.post(self._url(), data=data)
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])

        self.rule.refresh_from_db()
        event.refresh_from_db()
        self.assertFalse(self.rule.is_enabled)
        self.assertEqual(event.status, EventStatus.CLOSED)
        self.assertIsNotNone(event.closed_at)
        self.assertEqual(
            event.payload.get("closed_reason"), "rule_disabled",
        )

    def test_post_rejects_bounds_inverted(self):
        resp = self.client.post(self._url(), data=self._base_post(
            lower_bound="100", upper_bound="10",
        ))
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_no_bounds(self):
        resp = self.client.post(self._url(), data=self._base_post(
            lower_bound="", upper_bound="",
        ))
        self.assertEqual(resp.status_code, 400)

    # ── POST: scope promotion / demotion ──────────────────────────────

    def test_post_promotes_sensor_rule_to_device_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        resp = self.client.post(self._url(), data=self._base_post(
            scope_level="device", sensor="", device=str(self.device.id),
        ))
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scope_level, ThresholdRuleScope.DEVICE)
        self.assertEqual(self.rule.device, self.device)
        self.assertIsNone(self.rule.sensor)
        # Higher-level FKs auto-fill from the device.
        self.assertEqual(self.rule.asset, self.asset)
        self.assertEqual(self.rule.site, self.site)

    def test_post_changes_sensor_target(self):
        # Switching from sensor A to sensor B inside the same asset is
        # allowed. The asset URL anchor guarantees the new sensor is
        # also "reachable from this asset".
        resp = self.client.post(self._url(), data=self._base_post(
            sensor=str(self.other_sensor.id),
        ))
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.sensor, self.other_sensor)

    def test_post_rejects_foreign_sensor(self):
        # Submitting a sensor that lives under a different asset must
        # be rejected by the ModelChoiceField queryset.
        resp = self.client.post(self._url(), data=self._base_post(
            sensor=str(self.foreign_sensor.id),
        ))
        self.assertEqual(resp.status_code, 400)
        # Rule unchanged.
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.sensor, self.sensor)

    def test_post_promotes_to_asset_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        resp = self.client.post(self._url(), data=self._base_post(
            scope_level="asset", sensor="", device="",
        ))
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scope_level, ThresholdRuleScope.ASSET)
        self.assertEqual(self.rule.asset, self.asset)
        self.assertIsNone(self.rule.device)
        self.assertIsNone(self.rule.sensor)

    def test_post_promotes_to_site_scope(self):
        from apps.analytics.models import ThresholdRuleScope
        resp = self.client.post(self._url(), data=self._base_post(
            scope_level="site", sensor="", device="",
        ))
        self.assertEqual(resp.status_code, 302, msg=resp.content[:1000])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scope_level, ThresholdRuleScope.SITE)
        self.assertEqual(self.rule.site, self.site)
        self.assertIsNone(self.rule.asset)

    def test_edit_form_does_not_offer_global_scope(self):
        # Global promotion belongs to admin; the dashboard form must not
        # expose it. (Stage 4 create form does — that's separate.)
        resp = self.client.get(self._url())
        body = resp.content.decode("utf-8")
        # The select should contain scope choices but NOT global.
        self.assertNotIn('value="global"', body)
        self.assertIn('value="sensor"', body)
        self.assertIn('value="site"', body)

    def test_get_includes_metric_key_and_current_scope(self):
        resp = self.client.get(self._url())
        body = resp.content.decode("utf-8")
        self.assertIn("re_metric", body)
        self.assertIn(self.rule.code, body)


# ── Phase 7, Task 3A — Simulator control panel + live updates ───────────────


class OverviewSimulatorPanelRemovedTest(_AuthenticatedClientMixin, TestCase):
    """
    Phase 7, Task 4 — the overview MUST NOT render any simulator
    control / run / permission UI. Everything simulator-related has
    moved to /dashboard/simulator/. This test class guards that
    invariant so a future change cannot quietly re-introduce simulator
    chrome onto the operational dashboard.
    """

    def setUp(self):
        super().setUp()
        self.response = self.client.get("/dashboard/")
        self.body = self.response.content.decode("utf-8")

    def test_overview_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_overview_does_not_render_simulator_control_panel(self):
        self.assertNotIn('data-role="simulator-control"', self.body)
        self.assertNotIn('data-role="simulator-start-btn"', self.body)
        self.assertNotIn('data-role="simulator-stop-btn"', self.body)
        self.assertNotIn('data-role="simulator-run-once-btn"', self.body)
        self.assertNotIn('data-role="simulator-permission-notice"', self.body)

    def test_overview_does_not_render_simulator_run_table(self):
        self.assertNotIn('data-role="simulator-runs-wrapper"', self.body)
        self.assertNotIn('data-role="simulator-runs-state"', self.body)
        self.assertNotIn('data-role="simulator-counts"', self.body)

    def test_overview_does_not_render_pedejais_simulators_card(self):
        # The summary card was rendered client-side with the literal
        # "Pēdējais simulators" Latvian label by ``renderOverviewCards``;
        # ensure neither the overview API config nor the JS has any
        # remaining traces of that flow.
        self.assertNotIn("Pēdējais simulators", self.body)
        self.assertNotIn("overview/simulator", self.body)

    def test_overview_keeps_live_status_pill(self):
        # The pill stays so the overview can still surface a live
        # connection indicator even after the simulator panel moved out.
        self.assertIn('data-role="live-status-pill"', self.body)

    def test_overview_does_not_emit_unrendered_template_comments(self):
        # Django ``{# ... #}`` comments must not leak to the rendered
        # HTML; if any do, the operator would see internal markers
        # like "Phase 7, Task 3B" rendered as visible text. The
        # ``{% comment %}...{% endcomment %}`` block is the safe
        # multi-line variant and is silently stripped server-side.
        self.assertNotIn("{#", self.body)
        self.assertNotIn("Phase 7, Task", self.body)


# ── Phase 7, Task 4 — Simulator workspace page (/dashboard/simulator/) ─


class SimulatorWorkspacePageTest(_AuthenticatedClientMixin, TestCase):
    """The dedicated simulator workspace at /dashboard/simulator/."""

    URL = "/dashboard/simulator/"

    def setUp(self):
        super().setUp()
        self.response = self.client.get(self.URL)
        self.body = self.response.content.decode("utf-8")

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_uses_expected_template(self):
        templates = [t.name for t in self.response.templates if t.name]
        self.assertIn("dashboard/simulator.html", templates)
        self.assertIn("dashboard/base.html", templates)

    def test_anonymous_redirects_to_login(self):
        self.client.logout()
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 302)

    def test_route_name_resolves(self):
        from django.urls import reverse
        self.assertEqual(reverse("dashboard:simulator"), self.URL)

    def test_page_renders_status_control_panel(self):
        self.assertIn('data-role="simulator-control"', self.body)
        self.assertIn('data-role="simulator-start-btn"', self.body)
        self.assertIn('data-role="simulator-stop-btn"', self.body)
        self.assertIn('data-role="simulator-run-once-btn"', self.body)
        self.assertIn("Sākt", self.body)
        self.assertIn("Apturēt", self.body)
        self.assertIn("Palaist vienu reizi", self.body)

    def test_page_renders_profile_editor(self):
        self.assertIn('data-role="profile-editor"', self.body)
        self.assertIn('data-role="profile-select"', self.body)
        self.assertIn('data-role="profile-name"', self.body)
        self.assertIn('data-role="profile-code"', self.body)
        self.assertIn('data-role="profile-interval"', self.body)
        self.assertIn('data-role="profile-metrics-body"', self.body)
        self.assertIn('data-role="profile-save-btn"', self.body)

    def test_page_renders_chart_container(self):
        self.assertIn('data-role="simulator-charts"', self.body)

    def test_page_renders_mqtt_stream_table(self):
        self.assertIn('data-role="mqtt-stream-body"', self.body)
        self.assertIn("MQTT ziņojumu plūsma", self.body)

    def test_page_renders_permission_notice(self):
        self.assertIn('data-role="simulator-permission-notice"', self.body)


class SimulatorWorkspaceConfigTest(_AuthenticatedClientMixin, TestCase):
    """The simulator-config JSON block must carry every endpoint + flag."""

    def setUp(self):
        super().setUp()
        self.response = self.client.get("/dashboard/simulator/")
        self.cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"), "simulator-config",
        )

    def test_endpoints_present(self):
        for key in (
            "simulatorStatus", "simulatorStart",
            "simulatorStop", "simulatorRunOnce",
            "profileList", "profileDetailTemplate",
        ):
            self.assertIn(key, self.cfg["endpoints"])

    def test_websocket_path(self):
        self.assertEqual(self.cfg["websocketPath"], "/ws/dashboard/simulator/")

    def test_csrf_token_present(self):
        self.assertIn("csrfToken", self.cfg)
        self.assertIsInstance(self.cfg["csrfToken"], str)
        self.assertGreater(len(self.cfg["csrfToken"]), 0)

    def test_can_control_flag_present(self):
        self.assertIn("canControlSimulator", self.cfg)
        # Default operator has no explicit permission.
        self.assertFalse(self.cfg["canControlSimulator"])
        self.assertTrue(self.cfg["isAuthenticated"])

    def test_chart_metrics_metadata(self):
        chart = self.cfg["chartMetrics"]
        self.assertIsInstance(chart, list)
        keys = [m["key"] for m in chart]
        for required in (
            "temperature_c", "voltage_v", "power_w", "battery_soc_pct",
        ):
            self.assertIn(required, keys)


class SimulatorWorkspacePermissionTest(TestCase):
    """Permission gating + per-user can_control flag on the workspace page."""

    PASSWORD = "pw-secret-123!"

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        User = get_user_model()
        self.viewer = User.objects.create_user(
            username="viewer", password=self.PASSWORD,
        )
        self.controller = User.objects.create_user(
            username="controller", password=self.PASSWORD,
        )
        perm = Permission.objects.get(
            content_type__app_label="simulator",
            codename="can_control_simulator",
        )
        self.controller.user_permissions.add(perm)

    def _cfg_for(self, user) -> dict:
        self.client.force_login(user)
        resp = self.client.get("/dashboard/simulator/")
        self.assertEqual(resp.status_code, 200)
        return _read_dashboard_config(
            resp.content.decode("utf-8"), "simulator-config",
        )

    def test_viewer_cannot_control(self):
        cfg = self._cfg_for(self.viewer)
        self.assertFalse(cfg["canControlSimulator"])

    def test_controller_can_control(self):
        cfg = self._cfg_for(self.controller)
        self.assertTrue(cfg["canControlSimulator"])

    def test_superuser_can_control(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        root = User.objects.create_superuser(
            username="root", email="root@example.com", password=self.PASSWORD,
        )
        cfg = self._cfg_for(root)
        self.assertTrue(cfg["canControlSimulator"])


class AssetDetailWebSocketConfigTest(_AuthenticatedClientMixin, TestCase):

    def test_asset_detail_config_includes_websocket_path(self):
        resp = self.client.get("/dashboard/assets/charger-001/")
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "asset-detail-config",
        )
        self.assertEqual(
            cfg["websocketPath"], "/ws/dashboard/assets/charger-001/",
        )
        self.assertGreater(cfg["liveAutoRefreshIntervalSeconds"], 0)

    def test_asset_detail_renders_live_status_pill(self):
        resp = self.client.get("/dashboard/assets/charger-001/")
        self.assertContains(resp, 'data-role="live-status-pill"')

    def test_asset_detail_uuid_route_also_carries_websocket_path(self):
        random_uuid = uuid.uuid4()
        resp = self.client.get(f"/dashboard/assets/{random_uuid}/")
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "asset-detail-config",
        )
        self.assertEqual(
            cfg["websocketPath"],
            f"/ws/dashboard/assets/{random_uuid}/",
        )

    def test_asset_detail_chart_metrics_carry_label_and_unit(self):
        """
        Phase 7 Task 4 follow-up: the asset detail charts now use the
        same ``createSimulatorChart`` helper as the simulator workspace,
        so each chart-metric entry must carry ``key``, ``label``, and
        ``unit`` instead of being a bare metric key string.
        """
        resp = self.client.get("/dashboard/assets/charger-001/")
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"), "asset-detail-config",
        )
        chart_metrics = cfg["chartMetrics"]
        self.assertIsInstance(chart_metrics, list)
        self.assertGreater(len(chart_metrics), 0)
        keys = []
        for entry in chart_metrics:
            self.assertIsInstance(entry, dict)
            self.assertIn("key", entry)
            self.assertIn("label", entry)
            self.assertIn("unit", entry)
            keys.append(entry["key"])
        for required in (
            "temperature_c", "voltage_v", "power_w", "battery_soc_pct",
        ):
            self.assertIn(required, keys)
        # ``chartMaxPoints`` is also exposed so the JS can size its
        # rolling buffer the same way as the simulator workspace.
        self.assertGreater(cfg.get("chartMaxPoints", 0), 0)


class AssetDetailScrollableTablesTest(_AuthenticatedClientMixin, TestCase):
    """The "Pēdējie mērījumi" table must be wrapped in a scroll box."""

    def test_measurements_wrapper_has_scroll_class(self):
        resp = self.client.get("/dashboard/assets/charger-001/")
        html = resp.content.decode("utf-8")
        # Wrapper exists and carries the scroll class.
        self.assertIn(
            'class="measurements-scroll" data-role="measurements-wrapper"',
            html,
        )


class SimulatorWorkspaceScrollableTableTest(_AuthenticatedClientMixin, TestCase):
    """The MQTT message stream table must be wrapped in a scroll box."""

    def test_mqtt_stream_wrapper_has_scroll_class(self):
        resp = self.client.get("/dashboard/simulator/")
        html = resp.content.decode("utf-8")
        self.assertIn(
            'class="mqtt-stream-scroll" data-role="mqtt-stream-wrapper"',
            html,
        )


# ── WebSocket routing + consumers ───────────────────────────────────────────


class DashboardWebSocketRoutingTest(TestCase):
    """The websocket URL patterns must exist and resolve."""

    def test_overview_websocket_route_exists(self):
        from apps.dashboard.routing import websocket_urlpatterns
        names = [p.name for p in websocket_urlpatterns]
        self.assertIn("ws-dashboard-overview", names)
        self.assertIn("ws-dashboard-asset-detail", names)

    def test_simulator_websocket_route_exists(self):
        # Phase 7, Task 4 — dedicated /ws/dashboard/simulator/ route.
        from apps.dashboard.routing import websocket_urlpatterns
        names = [p.name for p in websocket_urlpatterns]
        self.assertIn("ws-dashboard-simulator", names)


class DashboardConsumerTest(TestCase):
    """
    Tests the Channels consumers using ``WebsocketCommunicator``. The
    test settings configure an in-memory channel layer so no Redis is
    required.
    """

    def test_overview_consumer_accepts_connection_and_sends_ack(self):
        import asyncio
        from channels.testing import WebsocketCommunicator
        from apps.dashboard.consumers import DashboardOverviewConsumer

        async def _run():
            communicator = WebsocketCommunicator(
                DashboardOverviewConsumer.as_asgi(), "/ws/dashboard/",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            ack = await communicator.receive_json_from()
            self.assertEqual(ack["event_type"], "connection_ack")
            self.assertEqual(ack["page"], "overview")
            await communicator.disconnect()

        asyncio.run(_run())

    def test_asset_detail_consumer_accepts_connection_and_sends_ack(self):
        import asyncio
        from channels.testing import WebsocketCommunicator
        from apps.dashboard.consumers import AssetDetailConsumer

        async def _run():
            communicator = WebsocketCommunicator(
                AssetDetailConsumer.as_asgi(),
                "/ws/dashboard/assets/charger-001/",
            )
            # WebsocketCommunicator does not parse path kwargs by itself;
            # set them explicitly so the consumer can read the asset id.
            communicator.scope["url_route"] = {
                "kwargs": {"asset_identifier": "charger-001"},
            }
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            ack = await communicator.receive_json_from()
            self.assertEqual(ack["event_type"], "connection_ack")
            self.assertEqual(ack["page"], "asset-detail")
            self.assertEqual(ack["asset_identifier"], "charger-001")
            await communicator.disconnect()

        asyncio.run(_run())

    def test_overview_consumer_forwards_group_event_to_browser(self):
        """A live-update broadcast reaches subscribers as a JSON message."""
        import asyncio
        from channels.testing import WebsocketCommunicator
        from apps.dashboard.consumers import DashboardOverviewConsumer
        from apps.dashboard import live_updates

        async def _run():
            communicator = WebsocketCommunicator(
                DashboardOverviewConsumer.as_asgi(), "/ws/dashboard/",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            # Drain the connection_ack first.
            await communicator.receive_json_from()

            # Publishing must be safe to call from sync code; channel
            # layer is set to InMemoryChannelLayer in test settings.
            from asgiref.sync import sync_to_async
            await sync_to_async(live_updates.publish_simulator_status_changed)(
                scenario=None,
                status="started",
                is_active=True,
                last_run_at=None,
                generated_messages=0,
                message="started",
            )

            event = await communicator.receive_json_from()
            self.assertEqual(event["event_type"], "simulator_status_changed")
            await communicator.disconnect()

        asyncio.run(_run())

    def test_simulator_consumer_accepts_connection_and_sends_ack(self):
        """Phase 7, Task 4 — /ws/dashboard/simulator/ accepts."""
        import asyncio
        from channels.testing import WebsocketCommunicator
        from apps.dashboard.consumers import SimulatorWorkspaceConsumer

        async def _run():
            communicator = WebsocketCommunicator(
                SimulatorWorkspaceConsumer.as_asgi(),
                "/ws/dashboard/simulator/",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            ack = await communicator.receive_json_from()
            self.assertEqual(ack["event_type"], "connection_ack")
            self.assertEqual(ack["page"], "simulator")
            self.assertIn("dashboard.simulator", ack["groups"])
            await communicator.disconnect()

        asyncio.run(_run())

    def test_simulator_consumer_forwards_mqtt_message_event(self):
        """The simulator consumer must receive the dedicated MQTT event."""
        import asyncio
        from channels.testing import WebsocketCommunicator
        from apps.dashboard.consumers import SimulatorWorkspaceConsumer
        from apps.dashboard import live_updates

        async def _run():
            communicator = WebsocketCommunicator(
                SimulatorWorkspaceConsumer.as_asgi(),
                "/ws/dashboard/simulator/",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.receive_json_from()  # ack

            from asgiref.sync import sync_to_async
            await sync_to_async(live_updates.publish_simulator_mqtt_message)(
                scenario=None, device=None, asset=None,
                topic="smt/dev/site/asset/dev-1/telemetry",
                payload_dict={
                    "message_id": "abc",
                    "metrics": {"temperature_c": 25.5, "voltage_v": 12.3},
                },
                publish_status="ok",
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["event_type"], "simulator_mqtt_message_sent")
            self.assertEqual(event["topic"], "smt/dev/site/asset/dev-1/telemetry")
            self.assertEqual(event["publish_status"], "ok")
            self.assertIn("temperature_c", event["metrics"])
            await communicator.disconnect()

        asyncio.run(_run())


# ── Live update publisher best-effort behaviour ─────────────────────────────


class LiveUpdatePublisherTest(TestCase):

    def test_publish_event_swallows_channel_layer_failure(self):
        """A broken channel layer must not raise back into business code."""
        from apps.dashboard import live_updates

        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("channel layer is down")

        with patch(
            "apps.dashboard.live_updates.get_channel_layer",
            return_value=_Boom(),
            create=True,
        ):
            try:
                live_updates.publish_event(
                    "simulator_status_changed", payload={"x": 1},
                )
            except Exception as exc:  # pragma: no cover
                self.fail(f"publish_event raised: {exc}")

    def test_publish_event_when_channels_missing_does_not_raise(self):
        """Even when ``channels`` cannot be imported the helper is silent."""
        from apps.dashboard import live_updates

        # Replace the channel layer accessor with one that returns None
        # (i.e. ``CHANNEL_LAYERS`` not configured).
        with patch(
            "apps.dashboard.live_updates.get_channel_layer",
            return_value=None,
            create=True,
        ):
            try:
                live_updates.publish_event(
                    "telemetry_received",
                    payload={"asset_code": "x"},
                )
            except Exception as exc:  # pragma: no cover
                self.fail(f"publish_event raised: {exc}")

    def test_safe_group_segment_sanitises_unsafe_chars(self):
        from apps.dashboard.live_updates import _safe_group_segment
        self.assertEqual(_safe_group_segment("charger-001"), "charger-001")
        self.assertEqual(
            _safe_group_segment("a/b c?d"), "a_b_c_d",
        )

    def test_publish_simulator_status_changed_uses_overview_group(self):
        """Verify that simulator events fan out to the overview group."""
        from apps.dashboard import live_updates

        captured: list[tuple[str, dict]] = []

        def _capture(groups, message):
            for g in groups:
                captured.append((g, message))

        with patch(
            "apps.dashboard.live_updates._send_to_groups",
            side_effect=_capture,
        ):
            live_updates.publish_simulator_status_changed(
                scenario=None, status="started", is_active=True,
                message="ok",
            )
        groups_used = [g for g, _ in captured]
        self.assertIn(live_updates.OVERVIEW_GROUP, groups_used)

    def test_publish_telemetry_received_addresses_asset_groups(self):
        """Asset-bound events fan out to BOTH the UUID and code groups."""
        from apps.dashboard import live_updates

        captured: list[str] = []

        def _capture(groups, message):
            captured.extend(groups)

        class _StubAsset:
            id = "abcd-1234"
            code = "charger-001"

        with patch(
            "apps.dashboard.live_updates._send_to_groups",
            side_effect=_capture,
        ):
            live_updates.publish_telemetry_received(
                asset=_StubAsset(),
                device=None,
                raw_message=None,
                measurements_count=2,
            )
        self.assertIn(live_updates.OVERVIEW_GROUP, captured)
        self.assertIn(
            live_updates.ASSET_GROUP_PREFIX + "abcd-1234", captured,
        )
        self.assertIn(
            live_updates.ASSET_GROUP_PREFIX + "charger-001", captured,
        )
