"""
Dashboard URL routing. Mounted under ``/dashboard/`` from
``config/urls.py``. All routes are GET-only — the dashboard is a
read-only frontend over the Phase 6 API.
"""

from __future__ import annotations

from django.urls import path

from apps.dashboard import views


app_name = "dashboard"

urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
    path("health/", views.health_view, name="health"),
    path(
        "assets/<str:asset_identifier>/",
        views.AssetDetailView.as_view(),
        name="asset-detail",
    ),
]
