"""
Dashboard WebSocket consumers.

Two consumer classes back the live update channel for the dashboard:

* :class:`DashboardOverviewConsumer` — joins the system-wide
  ``dashboard.overview`` group. Used by ``/dashboard/`` so the simulator
  panel, asset table, and event list refresh as soon as something changes.
* :class:`AssetDetailConsumer` — joins the ``dashboard.overview`` group
  AND a per-asset group (``dashboard.asset.<safe_id>``). Used by
  ``/dashboard/assets/<id-or-code>/``; the asset identifier in the URL
  is sanitised the same way the publisher sanitises asset IDs / codes,
  so the consumer never has to do an ORM lookup.

Both consumers stay deliberately tiny: messages from the channel layer
are forwarded to the browser as JSON without per-event business logic.
The browser is then responsible for re-fetching API data.
"""

from __future__ import annotations

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

from apps.dashboard.live_updates import (
    ASSET_GROUP_PREFIX,
    OVERVIEW_GROUP,
    SIMULATOR_GROUP,
    _safe_group_segment,
)

logger = logging.getLogger(__name__)


# Wire-format helpers ─────────────────────────────────────────────────────────


async def _send_json(consumer: AsyncWebsocketConsumer, data: dict) -> None:
    """Send a JSON-encoded payload through ``consumer``."""
    try:
        await consumer.send(text_data=json.dumps(data))
    except Exception as exc:  # noqa: BLE001
        # Logging and swallowing is correct here: a closed socket should
        # not raise back through the channel layer.
        logger.debug("Consumer send failed: %s", exc)


# Overview consumer ──────────────────────────────────────────────────────────


class DashboardOverviewConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for the overview page."""

    groups_joined: list[str] = []

    async def connect(self):
        self.groups_joined = [OVERVIEW_GROUP]
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        await _send_json(self, {
            "event_type": "connection_ack",
            "page": "overview",
            "groups": list(self.groups_joined),
        })

    async def disconnect(self, code):
        for group in self.groups_joined:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("group_discard failed: %s", exc)
        self.groups_joined = []

    async def receive(self, text_data=None, bytes_data=None):
        """
        Only one client-initiated message is supported: ``{"type":"ping"}``.
        Any other input is acknowledged with a generic ``error`` envelope
        so a stray client doesn't keep the consumer guessing.
        """
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            await _send_json(self, {"event_type": "error", "reason": "invalid_json"})
            return
        if data.get("type") == "ping":
            await _send_json(self, {"event_type": "pong"})

    async def dashboard_event(self, message):
        """Handler for messages dispatched by the live-update publisher."""
        try:
            payload = message.get("payload") or {}
            await _send_json(self, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("dashboard_event forward failed: %s", exc)


# Asset detail consumer ──────────────────────────────────────────────────────


class AssetDetailConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for a single asset detail page."""

    groups_joined: list[str] = []

    async def connect(self):
        identifier = self.scope.get("url_route", {}).get("kwargs", {}).get(
            "asset_identifier", "",
        )
        safe = _safe_group_segment(identifier)
        # Always subscribe to the overview group too — global events
        # (simulator status, system-wide telemetry summaries) should
        # still reach a single-asset page.
        self.groups_joined = [OVERVIEW_GROUP]
        if safe:
            self.groups_joined.append(ASSET_GROUP_PREFIX + safe)
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        await _send_json(self, {
            "event_type": "connection_ack",
            "page": "asset-detail",
            "asset_identifier": identifier,
            "groups": list(self.groups_joined),
        })

    async def disconnect(self, code):
        for group in self.groups_joined:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("group_discard failed: %s", exc)
        self.groups_joined = []

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            await _send_json(self, {"event_type": "error", "reason": "invalid_json"})
            return
        if data.get("type") == "ping":
            await _send_json(self, {"event_type": "pong"})

    async def dashboard_event(self, message):
        try:
            payload = message.get("payload") or {}
            await _send_json(self, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("dashboard_event forward failed: %s", exc)


# Simulator workspace consumer (Phase 7, Task 4) ─────────────────────────────


class SimulatorWorkspaceConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for the dedicated simulator workspace page at
    ``/dashboard/simulator/``.

    Joins the focused :data:`SIMULATOR_GROUP` channel layer group so it
    only receives ``simulator_*`` events plus telemetry/asset-state
    events that come from a simulator-driven publish. Subscribing to the
    overview group as well keeps the workspace honest about system-wide
    events (e.g. an anomaly raised by the simulator-fed ingestion
    pipeline).
    """

    groups_joined: list[str] = []

    async def connect(self):
        self.groups_joined = [SIMULATOR_GROUP, OVERVIEW_GROUP]
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        await _send_json(self, {
            "event_type": "connection_ack",
            "page": "simulator",
            "groups": list(self.groups_joined),
        })

    async def disconnect(self, code):
        for group in self.groups_joined:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("group_discard failed: %s", exc)
        self.groups_joined = []

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            await _send_json(self, {"event_type": "error", "reason": "invalid_json"})
            return
        if data.get("type") == "ping":
            await _send_json(self, {"event_type": "pong"})

    async def dashboard_event(self, message):
        try:
            payload = message.get("payload") or {}
            await _send_json(self, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("dashboard_event forward failed: %s", exc)
