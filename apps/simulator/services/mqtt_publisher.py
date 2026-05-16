"""
Simulator MQTT publisher.

Publishes one JSON-encoded telemetry payload to Mosquitto and blocks until the
broker has acknowledged the message (QoS 1). The publish is considered
successful only after ``MQTTMessageInfo.wait_for_publish()`` has returned and
``is_published()`` reports True; otherwise a :class:`SimulatorPublishError`
is raised. This guarantees that ``run_simulator`` cannot report success for
messages that never actually left the client's outbound queue.

The paho client is built by ``_default_client_factory``. The factory is
injectable so tests can supply a stub and never import paho.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


DEFAULT_PUBLISH_TIMEOUT_SECONDS: float = 10.0
DEFAULT_CONNECT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_QOS: int = 1


class SimulatorPublishError(RuntimeError):
    """Raised when the simulator cannot deliver a message to the MQTT broker."""


def publish_message(
    topic: str,
    payload: dict,
    *,
    qos: int = DEFAULT_QOS,
    timeout_seconds: float = DEFAULT_PUBLISH_TIMEOUT_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    client_factory: Optional[Callable] = None,
) -> None:
    """
    Publish ``payload`` (encoded as JSON) to ``topic`` via MQTT and wait for
    the broker to acknowledge the publish.

    Order of operations: ``connect`` → ``loop_start`` → wait for CONNACK →
    ``publish`` → ``wait_for_publish`` → ``loop_stop`` → ``disconnect``.

    Waiting for the CONNACK before publishing is required because paho's
    ``connect()`` only completes the TCP handshake — the MQTT-level CONNACK
    (and authentication result) is delivered asynchronously by the network
    loop. Publishing before the CONNACK has been processed yields
    ``MQTT_ERR_NO_CONN`` (rc=4) and an opaque failure; waiting lets us surface
    the broker's actual reason code (e.g. "not authorised") in the error.

    Args:
        topic: full MQTT topic, e.g. ``smt/dev/default_demo/charger/charger-001/telemetry``.
        payload: payload dict; will be JSON-serialised.
        qos: MQTT QoS level (default 1 — required for the publish ack).
        timeout_seconds: maximum time to wait for the publish ack.
        connect_timeout_seconds: maximum time to wait for CONNACK.
        client_factory: optional factory returning an unconnected paho-style client.
            Used by tests to inject a stub without importing paho.

    Raises:
        SimulatorPublishError: on connection failure, broker rejection,
            non-zero publish ``rc``, ``wait_for_publish`` failure, or timeout.
    """
    if client_factory is None:
        client_factory = _default_client_factory

    payload_str = json.dumps(payload)
    payload_bytes = len(payload_str.encode("utf-8"))

    host = getattr(settings, "MQTT_HOST", "mqtt")
    port = getattr(settings, "MQTT_PORT", 1883)
    keepalive = getattr(settings, "MQTT_KEEPALIVE_SECONDS", 60)
    username = getattr(settings, "MQTT_SIMULATOR_USERNAME", "") or ""
    password = getattr(settings, "MQTT_SIMULATOR_PASSWORD", "") or ""

    logger.info(
        "Simulator publishing topic=%s payload_bytes=%d host=%s port=%s "
        "authenticated=%s qos=%d connect_timeout=%.1fs publish_timeout=%.1fs",
        topic, payload_bytes, host, port, bool(username), qos,
        connect_timeout_seconds, timeout_seconds,
    )

    client = client_factory()
    if username:
        client.username_pw_set(username, password or None)

    connected_event = threading.Event()
    connect_state: dict = {"reason_code": None}

    def _on_connect(client_, userdata, flags, reason_code, properties=None):
        """
        Capture the broker's CONNACK reason code so we can fail fast with a
        clear error if the broker rejected the connection (e.g. bad credentials).
        """
        rc_value = getattr(reason_code, "value", reason_code)
        connect_state["reason_code"] = rc_value
        connected_event.set()

    client.on_connect = _on_connect

    loop_started = False
    try:
        try:
            client.connect(host, port, keepalive)
        except OSError as exc:
            raise SimulatorPublishError(
                f"Failed to connect to MQTT broker {host}:{port}: {exc}"
            ) from exc

        client.loop_start()
        loop_started = True

        if not connected_event.wait(timeout=connect_timeout_seconds):
            raise SimulatorPublishError(
                f"MQTT broker {host}:{port} did not return CONNACK within "
                f"{connect_timeout_seconds:.1f}s (username='{username or '<anonymous>'}')"
            )

        rc_value = connect_state["reason_code"]
        if rc_value != 0:
            raise SimulatorPublishError(
                f"MQTT broker {host}:{port} rejected connection "
                f"(reason_code={rc_value}, username='{username or '<anonymous>'}'); "
                "check MQTT_SIMULATOR_USERNAME / MQTT_SIMULATOR_PASSWORD"
            )

        publish_info = client.publish(topic, payload_str, qos=qos)

        rc = getattr(publish_info, "rc", None)
        if rc is not None and rc != 0:
            raise SimulatorPublishError(
                f"client.publish() returned non-zero rc={rc} for topic={topic}"
            )

        try:
            publish_info.wait_for_publish(timeout=timeout_seconds)
        except (ValueError, RuntimeError) as exc:
            # paho raises ValueError on bad rc and RuntimeError on disconnect.
            raise SimulatorPublishError(
                f"wait_for_publish failed for topic={topic}: {exc}"
            ) from exc

        if not publish_info.is_published():
            raise SimulatorPublishError(
                f"Publish to topic={topic} not acknowledged within "
                f"{timeout_seconds:.1f}s"
            )

        logger.info(
            "Simulator publish complete topic=%s payload_bytes=%d",
            topic, payload_bytes,
        )

    finally:
        if loop_started:
            try:
                client.loop_stop()
            except Exception:  # noqa: BLE001
                logger.debug("loop_stop() raised; ignoring on cleanup", exc_info=True)
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("disconnect() raised; ignoring on cleanup", exc_info=True)


def _default_client_factory():
    """
    Build a fresh paho-mqtt Client. The client is returned **unconnected**;
    ``publish_message`` is responsible for ``connect``, ``loop_start``,
    ``loop_stop`` and ``disconnect``.
    """
    import paho.mqtt.client as mqtt

    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api is not None:
        return mqtt.Client(
            client_id="smt-simulator",
            callback_api_version=callback_api.VERSION2,
        )
    return mqtt.Client(client_id="smt-simulator")
