"""
MQTT worker that connects to Mosquitto and forwards each received message
to ``apps.mqtt_ingestion.services.process_mqtt_message``.

The worker is intentionally thin: parsing, validation and persistence all
live in the ingestion service. This module is only responsible for the
MQTT plumbing (connect → subscribe → receive → delegate → log → reconnect).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.conf import settings

from apps.mqtt_ingestion.results import IngestionResult
from apps.mqtt_ingestion.services import process_mqtt_message

logger = logging.getLogger(__name__)


@dataclass
class MqttWorkerConfig:
    host: str
    port: int
    keepalive: int
    client_id: str
    topics: list
    username: str = ""
    password: str = ""

    @classmethod
    def from_settings(cls, **overrides) -> "MqttWorkerConfig":
        topics = overrides.pop("topics", None) or list(settings.MQTT_SUBSCRIBE_TOPICS)
        return cls(
            host=overrides.pop("host", None) or settings.MQTT_HOST,
            port=overrides.pop("port", None) or settings.MQTT_PORT,
            keepalive=overrides.pop("keepalive", None) or settings.MQTT_KEEPALIVE_SECONDS,
            client_id=overrides.pop("client_id", None) or settings.MQTT_CLIENT_ID,
            topics=topics,
            username=overrides.pop("username", None) or settings.MQTT_USERNAME,
            password=overrides.pop("password", None) or settings.MQTT_PASSWORD,
        )

    def redacted(self) -> dict:
        """Return a dict safe to log (password masked)."""
        return {
            "host": self.host,
            "port": self.port,
            "keepalive": self.keepalive,
            "client_id": self.client_id,
            "topics": self.topics,
            "username": self.username,
            "password": "***" if self.password else "",
        }


@dataclass
class WorkerStats:
    messages_received: int = 0
    messages_processed: int = 0
    duplicates: int = 0
    failures: int = 0
    unexpected_exceptions: int = 0


def _default_client_factory(client_id: str):
    """
    Build a paho-mqtt Client. Wrapped in a small factory so tests can
    inject a stub without importing paho.
    """
    import paho.mqtt.client as mqtt

    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api is not None:
        return mqtt.Client(client_id=client_id, callback_api_version=callback_api.VERSION2)
    return mqtt.Client(client_id=client_id)


class MqttIngestionWorker:
    """
    Thin MQTT subscriber that delegates each received message to
    ``process_mqtt_message``.

    Args:
        config: connection + subscription parameters.
        client_factory: callable returning a paho-style client; replaceable in tests.
        process_message: ingestion entry point (process_mqtt_message by default).
    """

    def __init__(
        self,
        config: MqttWorkerConfig,
        *,
        client_factory: Callable = _default_client_factory,
        process_message: Callable = process_mqtt_message,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._process_message = process_message

        self.stats = WorkerStats()
        self._stop_event = threading.Event()
        self._first_message_event = threading.Event()
        self._client = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def build_client(self):
        """Create the underlying client and wire callbacks."""
        client = self._client_factory(self.config.client_id)
        if self.config.username:
            client.username_pw_set(self.config.username, self.config.password or None)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        self._client = client
        return client

    def connect(self) -> None:
        if self._client is None:
            self.build_client()
        logger.info(
            "Connecting MQTT worker to %s:%s as client_id=%s",
            self.config.host, self.config.port, self.config.client_id,
        )
        self._client.connect(self.config.host, self.config.port, self.config.keepalive)

    def run_forever(self) -> None:
        """Long-running mode. Blocks until interrupted."""
        self.connect()
        try:
            self._client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received; shutting down MQTT worker")
        finally:
            self.shutdown()

    def run_once(self, timeout_seconds: float = 30.0) -> bool:
        """
        Connect, wait for ONE successfully delivered message, then shut down.

        Returns True when a message was processed within the timeout, False otherwise.
        """
        self.connect()
        self._client.loop_start()
        try:
            received = self._first_message_event.wait(timeout=timeout_seconds)
            if received:
                logger.info("run_once: message processed, exiting")
            else:
                logger.warning(
                    "run_once: timeout after %.1fs without receiving a message",
                    timeout_seconds,
                )
            return received
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._client is None:
            return
        self._stop_event.set()
        try:
            self._client.loop_stop()
        except Exception:  # noqa: BLE001
            logger.debug("loop_stop() raised; ignoring on shutdown", exc_info=True)
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("disconnect() raised; ignoring on shutdown", exc_info=True)
        logger.info(
            "MQTT worker stopped. Stats: received=%d processed=%d duplicates=%d failures=%d errors=%d",
            self.stats.messages_received,
            self.stats.messages_processed,
            self.stats.duplicates,
            self.stats.failures,
            self.stats.unexpected_exceptions,
        )

    # ── Paho callbacks ───────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """
        Subscribe to configured topics once the broker accepts the connection.

        Signature is the paho-mqtt 2.x VERSION2 callback shape; the optional
        ``properties`` argument keeps it compatible with v5 callbacks.
        """
        rc_value = getattr(reason_code, "value", reason_code)
        if rc_value != 0:
            logger.error("MQTT connection failed (reason_code=%s)", reason_code)
            return

        logger.info("MQTT connected; subscribing to %d topic(s)", len(self.config.topics))
        for topic in self.config.topics:
            result = client.subscribe(topic)
            logger.info("  subscribe('%s') → %s", topic, result)

    def _on_message(self, client, userdata, message):
        topic = message.topic
        payload = self._decode_payload(message.payload)
        size = len(message.payload) if message.payload is not None else 0
        self.stats.messages_received += 1
        logger.info("MQTT message received topic=%s payload_bytes=%d", topic, size)

        try:
            result: IngestionResult = self._process_message(
                topic, payload, source_type="mqtt"
            )
        except Exception as exc:  # noqa: BLE001
            self.stats.unexpected_exceptions += 1
            logger.exception("Ingestion raised an unexpected exception for topic=%s", topic)
            self._first_message_event.set()  # unblock --once even on failure
            return

        self._log_result(topic, result)
        if result.success:
            self.stats.messages_processed += 1
            if result.duplicate:
                self.stats.duplicates += 1
        else:
            self.stats.failures += 1

        self._first_message_event.set()

    def _on_disconnect(self, client, userdata, *args, **kwargs):
        """
        Tolerant signature: paho-mqtt 2.x can call this with several positional
        arguments depending on protocol version.
        """
        logger.info("MQTT disconnected (args=%s)", args)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _decode_payload(payload):
        if payload is None:
            return ""
        if isinstance(payload, (bytes, bytearray)):
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload.decode("utf-8", errors="replace")
        return payload

    @staticmethod
    def _log_result(topic: str, result: IngestionResult) -> None:
        if result.duplicate:
            logger.info("ingestion duplicate topic=%s", topic)
            return
        if result.success:
            logger.info(
                "ingestion ok topic=%s measurements_created=%d updated=%d events=%d",
                topic,
                result.measurements_created,
                result.measurements_updated,
                result.events_created,
            )
        else:
            logger.warning(
                "ingestion failed topic=%s errors=%s events=%d",
                topic, result.errors, result.events_created,
            )
