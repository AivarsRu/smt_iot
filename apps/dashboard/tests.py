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
