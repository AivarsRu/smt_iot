"""
Dashboard URL routing. Mounted under ``/dashboard/`` from
``config/urls.py``.

Phase 6 adds the read-only shell (``overview``, ``asset-detail``).
Phase 7 Task 3B replaces the one-page asset create form with a staged
operator workflow:

    GET/POST /dashboard/assets/new/                                Stage 1
    GET      /dashboard/assets/<asset_code>/configure/             hub
    GET/POST /dashboard/assets/<asset_code>/devices/new/           Stage 2a
    GET/POST /dashboard/assets/<asset_code>/devices/attach/        Stage 2b
    GET/POST /dashboard/assets/<asset_code>/devices/<uid>/sensors/new/
                                                                   Stage 3
    GET/POST /dashboard/assets/<asset_code>/devices/<uid>/sensors/<code>/metrics/new/
                                                                   Stage 4

Route ordering matters: the staged routes are registered *before* the
catch-all ``assets/<str:asset_identifier>/`` to avoid the latter
swallowing ``new`` / ``configure`` etc.
"""

from __future__ import annotations

from django.urls import path

from apps.dashboard import views


app_name = "dashboard"

urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
    path("health/", views.health_view, name="health"),

    # Phase 7, Task 4A: read-only events & anomaly review.
    path(
        "events/",
        views.EventsListView.as_view(),
        name="events-list",
    ),
    path(
        "events/<uuid:event_id>/",
        views.EventDetailView.as_view(),
        name="event-detail",
    ),

    path("assets/", views.assets_list_view, name="assets-list"),
    path(
        "assets/new/",
        views.AssetCreateStageView.as_view(),
        name="asset-create",
    ),

    # Staged configuration sub-routes — strictly above the detail route.
    path(
        "assets/<str:asset_code>/configure/",
        views.asset_configure_view,
        name="asset-configure",
    ),
    path(
        "assets/<str:asset_code>/devices/new/",
        views.DeviceCreateStageView.as_view(),
        name="device-create",
    ),
    path(
        "assets/<str:asset_code>/devices/attach/",
        views.DeviceAttachStageView.as_view(),
        name="device-attach",
    ),
    path(
        "assets/<str:asset_code>/devices/<str:device_uid>/sensors/new/",
        views.SensorCreateStageView.as_view(),
        name="sensor-create",
    ),
    path(
        "assets/<str:asset_code>/devices/<str:device_uid>/sensors/"
        "<str:sensor_code>/metrics/new/",
        views.SensorMetricStageView.as_view(),
        name="sensor-metric-create",
    ),
    # Operator-facing threshold-rule edit page. Anchored on the asset so
    # the view can enforce that the rule is actually reachable from that
    # asset before allowing any modification.
    path(
        "assets/<str:asset_code>/rules/<str:rule_code>/edit/",
        views.ThresholdRuleEditView.as_view(),
        name="threshold-rule-edit",
    ),

    # Catch-all read-only detail shell. Must remain last.
    path(
        "assets/<str:asset_identifier>/",
        views.AssetDetailView.as_view(),
        name="asset-detail",
    ),
]
