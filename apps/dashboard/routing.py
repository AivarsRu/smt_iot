"""
Dashboard WebSocket URL routing.

Mounted under ``/ws/`` from ``config/asgi.py``. The URL patterns mirror
the HTTP dashboard URL structure so a quick "the asset detail page is at
``/dashboard/assets/X/`` so the WebSocket is at ``/ws/dashboard/assets/X/``"
heuristic works for operators reading the network panel.
"""

from __future__ import annotations

from django.urls import path

from apps.dashboard import consumers


websocket_urlpatterns = [
    path(
        "ws/dashboard/",
        consumers.DashboardOverviewConsumer.as_asgi(),
        name="ws-dashboard-overview",
    ),
    # Phase 7, Task 4 — dedicated stream for /dashboard/simulator/.
    # Anchored before the ``/assets/<id>/`` route because Django path
    # routers use prefix matching but explicit static segments win
    # over ``<str:...>`` captures only when listed first.
    path(
        "ws/dashboard/simulator/",
        consumers.SimulatorWorkspaceConsumer.as_asgi(),
        name="ws-dashboard-simulator",
    ),
    path(
        "ws/dashboard/assets/<str:asset_identifier>/",
        consumers.AssetDetailConsumer.as_asgi(),
        name="ws-dashboard-asset-detail",
    ),
]
