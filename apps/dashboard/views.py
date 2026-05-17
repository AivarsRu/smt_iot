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


class OverviewView(TemplateView):
    """Render the main dashboard overview shell."""

    template_name = "dashboard/overview.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The dashboard JS reads everything from a single json_script
        # block; ``__CODE__`` is a literal placeholder that ``dashboard.js``
        # substitutes per-row when building asset summary links.
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
            "autoRefreshIntervalSeconds": 30,
        }
        return context


def health_view(request):
    """Tiny dashboard liveness probe — independent of the data API."""
    return HttpResponse("ok", content_type="text/plain")
