"""
Tests for the Phase 7 dashboard shell. The dashboard is a thin server-
rendered template — these tests assert routing, template selection, and
that the page exposes the expected API endpoint URLs and static asset
references. Real browser-side rendering is out of scope.

Run with:
    python manage.py test apps.dashboard --settings=config.settings.test
"""

from __future__ import annotations

import json
import uuid

from django.test import TestCase
from django.urls import resolve, reverse


class DashboardRoutingTest(TestCase):

    def test_overview_url_resolves(self):
        match = resolve("/dashboard/")
        self.assertEqual(match.view_name, "dashboard:overview")

    def test_health_url_resolves(self):
        match = resolve("/dashboard/health/")
        self.assertEqual(match.view_name, "dashboard:health")

    def test_overview_reverse_returns_root_dashboard(self):
        self.assertEqual(reverse("dashboard:overview"), "/dashboard/")


class DashboardOverviewPageTest(TestCase):

    def setUp(self):
        self.response = self.client.get("/dashboard/")

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_uses_overview_template(self):
        templates = [t.name for t in self.response.templates if t.name]
        self.assertIn("dashboard/overview.html", templates)
        self.assertIn("dashboard/base.html", templates)

    def test_page_contains_project_title(self):
        self.assertContains(self.response, "SMT Digital Solution")
        self.assertContains(
            self.response,
            "IoT infrastructure monitoring and digital twin prototype",
        )

    def test_page_contains_refresh_button(self):
        self.assertContains(self.response, 'data-role="refresh-btn"')
        self.assertContains(self.response, 'data-testid="refresh-btn"')

    def test_page_references_dashboard_static_assets(self):
        # The compiled HTML should reference both the CSS and the JS file.
        self.assertContains(self.response, "dashboard/dashboard.css")
        self.assertContains(self.response, "dashboard/dashboard.js")

    def test_page_contains_required_api_endpoints(self):
        for path in (
            "/api/overview/",
            "/api/overview/assets/",
            "/api/overview/events/",
            "/api/overview/telemetry/",
            "/api/overview/simulator/",
        ):
            self.assertContains(self.response, path)

    def test_page_contains_asset_summary_url_template(self):
        # The placeholder must appear so dashboard.js can substitute the
        # real asset code at render time.
        self.assertContains(self.response, "/api/assets/__CODE__/summary/")

    def test_dashboard_config_is_valid_json(self):
        # The json_script tag emits a <script id="dashboard-config" ...>
        # block with the endpoints + URL template; assert it parses.
        content = self.response.content.decode("utf-8")
        marker = '<script id="dashboard-config" type="application/json">'
        idx = content.find(marker)
        self.assertNotEqual(idx, -1, "dashboard-config script block missing")
        body_start = idx + len(marker)
        body_end = content.find("</script>", body_start)
        payload = content[body_start:body_end].strip()
        data = json.loads(payload)
        for required in (
            "overview", "overviewAssets", "overviewEvents",
            "overviewTelemetry", "overviewSimulator",
        ):
            self.assertIn(required, data["endpoints"])
        self.assertIn("__CODE__", data["assetSummaryUrlTemplate"])

    def test_does_not_hardcode_demo_asset_code(self):
        # The dashboard shell must not embed seeded demo identifiers.
        self.assertNotContains(self.response, "charger-001")

    def test_post_is_not_allowed(self):
        resp = self.client.post("/dashboard/", data={})
        self.assertEqual(resp.status_code, 405)


class DashboardHealthPageTest(TestCase):

    def test_returns_200_and_ok_text(self):
        resp = self.client.get("/dashboard/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ok", resp.content.decode("utf-8").lower())


# ── Phase 7, Task 2: asset detail page ───────────────────────────────────────


def _read_dashboard_config(content: str, script_id: str) -> dict:
    """Pull a json_script block out of the rendered HTML and parse it."""
    marker = f'<script id="{script_id}" type="application/json">'
    idx = content.find(marker)
    assert idx != -1, f"missing #{script_id} script block"
    body_start = idx + len(marker)
    body_end = content.find("</script>", body_start)
    return json.loads(content[body_start:body_end].strip())


class AssetDetailRoutingTest(TestCase):

    def test_route_resolves(self):
        match = resolve("/dashboard/assets/charger-001/")
        self.assertEqual(match.view_name, "dashboard:asset-detail")
        self.assertEqual(
            match.kwargs,
            {"asset_identifier": "charger-001"},
        )

    def test_reverse_with_code(self):
        url = reverse(
            "dashboard:asset-detail",
            kwargs={"asset_identifier": "charger-001"},
        )
        self.assertEqual(url, "/dashboard/assets/charger-001/")


class AssetDetailPageTest(TestCase):

    URL = "/dashboard/assets/charger-001/"

    def setUp(self):
        self.response = self.client.get(self.URL)

    def test_returns_200(self):
        # We chose the "200 + page-level error in JS" design: the shell
        # always renders, JS surfaces "Asset not found" if the API 404s.
        self.assertEqual(self.response.status_code, 200)

    def test_unknown_asset_code_also_returns_200_shell(self):
        resp = self.client.get("/dashboard/assets/does-not-exist/")
        self.assertEqual(resp.status_code, 200)
        # The shell still renders; the data-role error banner is present
        # so JS can show "Asset not found".
        self.assertContains(resp, 'data-role="page-error"')

    def test_uuid_route_returns_200(self):
        random_uuid = uuid.uuid4()
        resp = self.client.get(f"/dashboard/assets/{random_uuid}/")
        self.assertEqual(resp.status_code, 200)

    def test_uses_expected_template(self):
        templates = [t.name for t in self.response.templates if t.name]
        self.assertIn("dashboard/asset_detail.html", templates)
        self.assertIn("dashboard/base.html", templates)

    def test_page_contains_project_title(self):
        self.assertContains(self.response, "SMT Digital Solution")

    def test_page_references_static_assets(self):
        self.assertContains(self.response, "dashboard/dashboard.css")
        self.assertContains(self.response, "dashboard/dashboard.js")

    def test_page_contains_back_link_to_overview(self):
        self.assertContains(self.response, 'href="/dashboard/"')

    def test_post_is_not_allowed(self):
        resp = self.client.post(self.URL, data={})
        self.assertEqual(resp.status_code, 405)

    def test_config_block_carries_asset_identifier(self):
        cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"),
            "asset-detail-config",
        )
        self.assertEqual(cfg["assetIdentifier"], "charger-001")

    def test_config_block_contains_required_api_urls(self):
        cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"),
            "asset-detail-config",
        )
        self.assertEqual(
            cfg["summaryUrl"], "/api/assets/charger-001/summary/",
        )
        self.assertTrue(
            cfg["measurementsUrl"].startswith("/api/assets/charger-001/measurements/")
        )
        self.assertTrue(
            cfg["eventsUrl"].startswith("/api/assets/charger-001/events/")
        )
        self.assertIn("__METRIC__", cfg["chartUrlTemplate"])

    def test_config_block_contains_all_chart_metric_keys(self):
        cfg = _read_dashboard_config(
            self.response.content.decode("utf-8"),
            "asset-detail-config",
        )
        self.assertEqual(
            sorted(cfg["chartMetrics"]),
            sorted(["temperature_c", "voltage_v", "power_w", "battery_soc_pct"]),
        )
        # Also verify the metric keys are present in the raw HTML so a
        # template-only scan would catch a regression.
        for metric in ("temperature_c", "voltage_v", "power_w", "battery_soc_pct"):
            self.assertContains(self.response, metric)


class OverviewLinksToAssetDetailTest(TestCase):

    def test_overview_config_includes_asset_detail_url_template(self):
        resp = self.client.get("/dashboard/")
        cfg = _read_dashboard_config(
            resp.content.decode("utf-8"),
            "dashboard-config",
        )
        self.assertEqual(
            cfg["assetDetailUrlTemplate"],
            "/dashboard/assets/__CODE__/",
        )

    def test_overview_html_contains_asset_detail_url_template(self):
        # Belt + suspenders: also assert via plain string contains so a
        # JSON-shape change is caught by template-level tests too.
        resp = self.client.get("/dashboard/")
        self.assertContains(resp, "/dashboard/assets/__CODE__/")
