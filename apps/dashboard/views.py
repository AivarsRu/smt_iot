"""
Dashboard shell views.

The dashboard is a thin server-rendered shell that delegates all data
loading to the Phase 6 read-only API. Server-side views NEVER call the
local HTTP API — they only render the template and pass endpoint URLs
into a JSON config block, which ``dashboard.js`` reads at runtime.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import TemplateView


# Charts shown on the asset detail page. Kept here (not in the template)
# so the test suite can assert exactly which metrics the page advertises
# without scraping JavaScript.
ASSET_DETAIL_CHART_METRICS = (
    "temperature_c",
    "voltage_v",
    "power_w",
    "battery_soc_pct",
)


class OverviewView(TemplateView):
    """Render the main dashboard overview shell."""

    template_name = "dashboard/overview.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The dashboard JS reads everything from a single json_script
        # block; ``__CODE__`` is a literal placeholder that ``dashboard.js``
        # substitutes per-row when building per-asset links.
        context["dashboard_config"] = {
            "endpoints": {
                "overview": reverse("api-overview"),
                "overviewAssets": reverse("api-overview-assets"),
                "overviewEvents": reverse("api-overview-events"),
                "overviewTelemetry": reverse("api-overview-telemetry"),
                "overviewSimulator": reverse("api-overview-simulator"),
                "health": reverse("api-health"),
            },
            "assetSummaryUrlTemplate": reverse(
                "asset-summary", kwargs={"pk": "__CODE__"},
            ),
            "assetDetailUrlTemplate": reverse(
                "dashboard:asset-detail",
                kwargs={"asset_identifier": "__CODE__"},
            ),
            "autoRefreshIntervalSeconds": 30,
        }
        return context


class AssetDetailView(TemplateView):
    """
    Render the per-asset dashboard shell.

    The view does not validate that the asset exists — it simply embeds
    the API endpoint URLs and lets ``dashboard.js`` render a clear page-
    level "Asset not found" message if the summary endpoint returns 404.
    This keeps the view free of database calls and matches the existing
    "API-driven shell" pattern used for the overview page.
    """

    template_name = "dashboard/asset_detail.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        identifier = kwargs.get("asset_identifier", "")
        context["asset_identifier"] = identifier
        # Build per-asset API URLs once so the template is dumb. We use
        # the existing ``IdOrCodeLookupMixin`` route names which accept
        # both UUID and human-readable code in the path segment.
        summary_url = reverse(
            "asset-summary", kwargs={"pk": identifier},
        )
        measurements_url = reverse(
            "asset-measurements", kwargs={"pk": identifier},
        )
        events_url = reverse(
            "asset-events", kwargs={"pk": identifier},
        )
        # Chart URL template uses ``__METRIC__`` as a literal placeholder
        # that ``dashboard.js`` substitutes per chart. The path component
        # has to come from ``reverse`` so we don't hardcode ``/api/...``.
        chart_url_template = (
            measurements_url + "?metric=__METRIC__&limit=100"
        )
        context["asset_detail_config"] = {
            "assetIdentifier": identifier,
            "summaryUrl": summary_url,
            "measurementsUrl": measurements_url + "?limit=20",
            "eventsUrl": events_url + "?limit=20",
            "chartUrlTemplate": chart_url_template,
            "chartMetrics": list(ASSET_DETAIL_CHART_METRICS),
            "dashboardOverviewUrl": reverse("dashboard:overview"),
            "autoRefreshIntervalSeconds": 30,
        }
        return context


def health_view(request):
    """Tiny dashboard liveness probe — independent of the data API."""
    return HttpResponse("ok", content_type="text/plain")
