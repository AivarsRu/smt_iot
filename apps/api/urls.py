"""
URL routing for the read-only SMT API. Mounted under ``/api/`` from
``config/urls.py``. All routes here are read-only (HTTP GET); writes are
intentionally not exposed.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.api import overview, views

router = DefaultRouter()
router.register(r"sites", views.SiteViewSet, basename="site")
router.register(r"assets", views.AssetViewSet, basename="asset")
router.register(r"devices", views.DeviceViewSet, basename="device")
router.register(r"sensors", views.SensorViewSet, basename="sensor")
router.register(r"sensor-metrics", views.SensorMetricViewSet, basename="sensor-metric")
router.register(r"metrics", views.MetricDefinitionViewSet, basename="metric")
router.register(r"asset-states", views.AssetStateViewSet, basename="asset-state")
router.register(r"measurements", views.MeasurementViewSet, basename="measurement")
router.register(r"events", views.EventViewSet, basename="event")
router.register(r"raw-messages", views.RawMessageViewSet, basename="raw-message")
router.register(r"threshold-rules", views.ThresholdRuleViewSet, basename="threshold-rule")
router.register(
    r"simulator-scenarios", views.SimulatorScenarioViewSet, basename="simulator-scenario",
)
router.register(r"simulator-runs", views.SimulatorRunViewSet, basename="simulator-run")


urlpatterns = [
    path("health/", views.health_view, name="api-health"),
    # Dashboard summary endpoints (Phase 6, Task 2). Registered before the
    # router include so explicit paths win over any future router collisions.
    path("overview/", overview.overview_view, name="api-overview"),
    path("overview/assets/", overview.overview_assets_view, name="api-overview-assets"),
    path("overview/events/", overview.overview_events_view, name="api-overview-events"),
    path(
        "overview/telemetry/", overview.overview_telemetry_view,
        name="api-overview-telemetry",
    ),
    path(
        "overview/simulator/", overview.overview_simulator_view,
        name="api-overview-simulator",
    ),
    # Simulator control (Phase 7, Task 3A). The single ``write`` exception to
    # the otherwise read-only API; see ``apps/api/views.py`` for the auth
    # rationale and the planned replacement.
    path(
        "simulator/status/", views.simulator_status_view,
        name="api-simulator-status",
    ),
    path(
        "simulator/start/", views.simulator_start_view,
        name="api-simulator-start",
    ),
    path(
        "simulator/stop/", views.simulator_stop_view,
        name="api-simulator-stop",
    ),
    path(
        "simulator/run-once/", views.simulator_run_once_view,
        name="api-simulator-run-once",
    ),
    # Phase 7, Task 4 — simulator profile editor endpoints.
    path(
        "simulator/profiles/", views.simulator_profile_list_view,
        name="api-simulator-profile-list",
    ),
    path(
        "simulator/profiles/<str:code>/", views.simulator_profile_detail_view,
        name="api-simulator-profile-detail",
    ),
    path("", include(router.urls)),
]
