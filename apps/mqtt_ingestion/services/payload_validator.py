import json
from typing import Optional, Tuple

REQUIRED_TELEMETRY_FIELDS = ("message_id", "device_id", "timestamp", "metrics")


def coerce_payload(payload) -> Tuple[Optional[dict], str]:
    """
    Coerce an incoming MQTT payload to (dict, payload_text).

    - If payload is already a dict, return (payload, "").
    - If payload is bytes/str, attempt JSON parse.
    - Returns (None, raw_text) when JSON parsing fails.
    """
    if isinstance(payload, dict):
        return payload, ""

    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")

    payload_text = str(payload)
    try:
        return json.loads(payload_text), payload_text
    except (json.JSONDecodeError, ValueError):
        return None, payload_text


def validate_telemetry_payload(payload: dict) -> list[str]:
    """
    Validate required fields for a telemetry payload.
    Returns a list of error strings; an empty list means the payload is valid.
    """
    errors: list[str] = []

    for field_name in REQUIRED_TELEMETRY_FIELDS:
        if field_name not in payload:
            errors.append(f"Missing required field: '{field_name}'")

    if "metrics" in payload and not isinstance(payload["metrics"], dict):
        errors.append("'metrics' must be a JSON object (key-value pairs)")

    if "timestamp" in payload and not payload.get("timestamp"):
        errors.append("'timestamp' must not be empty")

    return errors
