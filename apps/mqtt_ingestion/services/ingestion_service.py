import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.models import DataType, OperationalStatus
from apps.digital_twin.models import AssetState
from apps.events.models import Event, EventStatus, EventType, Severity
from apps.mqtt_ingestion.exceptions import TopicParseError
from apps.mqtt_ingestion.results import IngestionResult
from apps.mqtt_ingestion.services.payload_validator import coerce_payload, validate_telemetry_payload
from apps.mqtt_ingestion.services.topic_parser import parse_topic
from apps.telemetry.models import (
    Measurement,
    MeasurementQuality,
    ProcessingStatus,
    RawMessage,
    SourceType,
)

logger = logging.getLogger(__name__)

_INGESTION_SOURCE = "mqtt_ingestion"

_SOURCE_TYPE_MAP = {
    "mqtt": SourceType.MQTT,
    "simulator": SourceType.SIMULATOR,
    "rest": SourceType.REST,
    "manual": SourceType.MANUAL,
}

_SUPPORTED_MESSAGE_TYPES = frozenset({"telemetry"})

_PAYLOAD_STATUS_MAP = {
    "charging": OperationalStatus.ACTIVE,
    "active": OperationalStatus.ACTIVE,
    "online": OperationalStatus.ACTIVE,
    "ok": OperationalStatus.ACTIVE,
    "normal": OperationalStatus.ACTIVE,
    "warning": OperationalStatus.WARNING,
    "error": OperationalStatus.ERROR,
    "fault": OperationalStatus.ERROR,
    "failed": OperationalStatus.ERROR,
    "offline": OperationalStatus.OFFLINE,
}


# ── Public entry point ────────────────────────────────────────────────────────

def process_mqtt_message(
    topic: str,
    payload,
    *,
    source_type: str = "mqtt",
    parser_version: str = "v1",
) -> IngestionResult:
    """
    Process one MQTT message end-to-end:
      parse topic → validate payload → persist RawMessage → resolve entities
      → create Measurements → update AssetState → update Device → return result.

    Does not connect to any MQTT broker. Accepts topic and payload directly.

    Args:
        topic: full MQTT topic string.
        payload: raw payload (str, bytes, or already-parsed dict).
        source_type: one of 'mqtt', 'simulator', 'rest', 'manual'.
        parser_version: version tag stored in RawMessage.parser_version.

    Returns:
        IngestionResult describing what was stored and any errors encountered.
    """
    received_at = timezone.now()
    st = _SOURCE_TYPE_MAP.get(source_type, SourceType.MQTT)

    try:
        return _run_pipeline(topic, payload, st, parser_version, received_at)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected ingestion error for topic=%s", topic)
        try:
            _create_event(
                event_type=EventType.INGESTION_ERROR,
                severity=Severity.CRITICAL,
                title="Unexpected ingestion exception",
                description=str(exc),
            )
        except Exception:  # noqa: BLE001
            pass
        return IngestionResult(success=False, errors=[f"Unexpected error: {exc}"])


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _run_pipeline(
    topic: str,
    payload,
    source_type: SourceType,
    parser_version: str,
    received_at,
) -> IngestionResult:

    # 1. Parse MQTT topic
    try:
        topic_info = parse_topic(topic)
    except TopicParseError as exc:
        raw = _save_minimal_raw(
            topic=topic,
            payload=payload,
            source_type=source_type,
            status=ProcessingStatus.FAILED,
            error=str(exc),
            parser_version=parser_version,
            received_at=received_at,
        )
        _create_event(
            event_type=EventType.VALIDATION_ERROR,
            severity=Severity.ERROR,
            title="Invalid MQTT topic format",
            description=str(exc),
            raw_message=raw,
        )
        return IngestionResult(success=False, raw_message=raw, events_created=1, errors=[str(exc)])

    # 2. Unsupported message type → store as ignored, no error event
    if topic_info.message_type not in _SUPPORTED_MESSAGE_TYPES:
        raw = _save_minimal_raw(
            topic=topic,
            payload=payload,
            source_type=source_type,
            status=ProcessingStatus.IGNORED,
            device_uid=topic_info.device_uid,
            parser_version=parser_version,
            received_at=received_at,
        )
        return IngestionResult(success=True, raw_message=raw)

    # 3. Coerce payload to dict
    payload_dict, payload_text = coerce_payload(payload)
    if payload_dict is None:
        raw = _save_minimal_raw(
            topic=topic,
            payload_text=payload_text,
            source_type=source_type,
            status=ProcessingStatus.FAILED,
            error="Payload is not valid JSON",
            device_uid=topic_info.device_uid,
            parser_version=parser_version,
            received_at=received_at,
        )
        _create_event(
            event_type=EventType.INGESTION_ERROR,
            severity=Severity.ERROR,
            title="Invalid JSON payload",
            description=f"Could not parse payload as JSON. topic={topic}",
            raw_message=raw,
        )
        return IngestionResult(
            success=False, raw_message=raw, events_created=1, errors=["Payload is not valid JSON"]
        )

    # 4. Validate required fields
    field_errors = validate_telemetry_payload(payload_dict)
    if field_errors:
        raw = _save_minimal_raw(
            topic=topic,
            payload=payload_dict,
            payload_text=payload_text,
            source_type=source_type,
            status=ProcessingStatus.FAILED,
            error="; ".join(field_errors),
            device_uid=topic_info.device_uid,
            parser_version=parser_version,
            received_at=received_at,
        )
        _create_event(
            event_type=EventType.VALIDATION_ERROR,
            severity=Severity.ERROR,
            title="Missing required payload fields",
            description="; ".join(field_errors),
            raw_message=raw,
        )
        return IngestionResult(
            success=False, raw_message=raw, events_created=1, errors=field_errors
        )

    # 5. Extract identity fields
    message_id = str(payload_dict.get("message_id", "")).strip()
    payload_device_id = str(payload_dict.get("device_id", "")).strip()

    # 6. device_id vs topic device_uid consistency check
    if payload_device_id and payload_device_id != topic_info.device_uid:
        error = (
            f"device_id mismatch: payload='{payload_device_id}', "
            f"topic='{topic_info.device_uid}'"
        )
        raw = _save_minimal_raw(
            topic=topic,
            payload=payload_dict,
            payload_text=payload_text,
            source_type=source_type,
            status=ProcessingStatus.FAILED,
            error=error,
            message_id=message_id,
            device_uid=topic_info.device_uid,
            parser_version=parser_version,
            received_at=received_at,
        )
        _create_event(
            event_type=EventType.VALIDATION_ERROR,
            severity=Severity.ERROR,
            title="Device ID mismatch between topic and payload",
            description=error,
            raw_message=raw,
        )
        return IngestionResult(success=False, raw_message=raw, events_created=1, errors=[error])

    device_uid = payload_device_id or topic_info.device_uid

    # 7. Duplicate check — before any DB insert
    if message_id and RawMessage.objects.filter(message_id=message_id).exists():
        return IngestionResult(success=True, duplicate=True)

    # 8. Parse timestamp from payload
    payload_timestamp = _parse_timestamp(payload_dict.get("timestamp"))

    # 9. Create the RawMessage (status: received — will be updated at the end)
    raw_message = RawMessage.objects.create(
        source_type=source_type,
        topic=topic,
        payload=payload_dict,
        payload_text=payload_text,
        message_id=message_id,
        device_uid=device_uid,
        received_at=received_at,
        payload_timestamp=payload_timestamp,
        processing_status=ProcessingStatus.RECEIVED,
        parser_version=parser_version,
    )

    # 10. Resolve Site
    from apps.assets.models import Asset, Device, Sensor, Site  # local import avoids circular

    try:
        site = Site.objects.get(code=topic_info.site_code)
    except Site.DoesNotExist:
        return _fail_raw(
            raw_message,
            error=f"Site not found: code='{topic_info.site_code}'",
            event_type=EventType.VALIDATION_ERROR,
            title="Unknown site",
        )

    raw_message.site = site
    raw_message.save(update_fields=["site"])

    # 11. Resolve Device
    try:
        device = Device.objects.select_related("asset").get(device_uid=device_uid)
    except Device.DoesNotExist:
        return _fail_raw(
            raw_message,
            error=f"Device not found: device_uid='{device_uid}'",
            event_type=EventType.VALIDATION_ERROR,
            title="Unknown device",
            site=site,
        )

    raw_message.device = device
    raw_message.save(update_fields=["device"])

    # 12. Resolve Asset
    asset_code_from_payload = str(payload_dict.get("asset_id", "")).strip()
    asset = _resolve_asset(site, device, asset_code_from_payload)
    if asset is None:
        if asset_code_from_payload:
            error = f"Asset not found: site='{site.code}', code='{asset_code_from_payload}'"
        else:
            error = "Asset could not be resolved: no asset_id in payload and device has no assigned asset"
        return _fail_raw(
            raw_message,
            error=error,
            event_type=EventType.VALIDATION_ERROR,
            title="Unknown asset",
            site=site,
            device=device,
        )

    raw_message.asset = asset
    raw_message.save(update_fields=["asset"])

    # 13. Resolve Sensor (best effort — never fails ingestion)
    sensor = Sensor.objects.filter(device=device, is_active=True).first()

    # 14 & 15. Create measurements and update state (atomic block for consistency)
    from apps.iot_config.models import MetricDefinition  # local import

    metrics_payload: dict = payload_dict.get("metrics", {})
    measurement_ts = payload_timestamp or received_at
    measurements_created = 0
    measurements_updated = 0
    events_created = 0
    unknown_metric_keys: list[str] = []
    persisted_measurements: list = []

    with transaction.atomic():
        for metric_key, raw_value in metrics_payload.items():
            result, measurement_obj = _process_one_metric(
                metric_key=metric_key,
                raw_value=raw_value,
                site=site,
                asset=asset,
                device=device,
                sensor=sensor,
                metric_def_cache=None,  # resolved inside
                raw_message=raw_message,
                measurement_ts=measurement_ts,
            )
            if result == "created":
                measurements_created += 1
                if measurement_obj is not None:
                    persisted_measurements.append(measurement_obj)
            elif result == "updated":
                measurements_updated += 1
                if measurement_obj is not None:
                    persisted_measurements.append(measurement_obj)
            elif result == "unknown":
                unknown_metric_keys.append(metric_key)
                events_created += _create_unknown_metric_event(
                    metric_key, message_id, site, asset, device, raw_message
                )
            elif result == "invalid":
                events_created += _create_invalid_value_event(
                    metric_key, raw_value, site, asset, device, raw_message
                )

        # 16. Update RawMessage processing status
        total_stored = measurements_created + measurements_updated
        if total_stored > 0:
            raw_message.processing_status = ProcessingStatus.PARSED
        else:
            raw_message.processing_status = ProcessingStatus.FAILED
            raw_message.error_message = (
                f"No measurements stored. Unknown metrics: {unknown_metric_keys}"
                if unknown_metric_keys
                else "No metrics processed"
            )
        raw_message.save(update_fields=["processing_status", "error_message"])

        # 17. Update Device
        device_fields = ["last_seen_at"]
        device.last_seen_at = measurement_ts
        fw = str(payload_dict.get("firmware_version", "")).strip()
        if fw:
            device.firmware_version = fw
            device_fields.append("firmware_version")
        device.save(update_fields=device_fields)

        # 18. Update AssetState (only when we actually stored something)
        if total_stored > 0:
            _update_asset_state(
                asset=asset,
                site=site,
                device=device,
                raw_message=raw_message,
                metrics_payload=metrics_payload,
                payload_status=str(payload_dict.get("status", "")).strip(),
                measurement_ts=measurement_ts,
            )

    # 19. Threshold analytics (outside the persistence transaction). Errors here
    #     must NOT corrupt successfully stored telemetry — failures are recorded
    #     in IngestionResult.errors and surfaced via an ingestion_error Event.
    analytics_events_created = 0
    analytics_errors: list[str] = []
    if persisted_measurements:
        analytics_events_created, analytics_errors_list = _evaluate_thresholds(
            persisted_measurements,
            raw_message=raw_message,
            site=site,
            asset=asset,
            device=device,
        )
        analytics_errors.extend(analytics_errors_list)
        if analytics_errors:
            events_created += 1  # the ingestion_error event recorded by _evaluate_thresholds

    # 20. Communication-timeout recovery: best-effort close of any open
    #     timeout event for this device. Never creates timeout events here;
    #     periodic detection lives in `check_communication_timeouts`.
    if total_stored > 0:
        recovery_errors = _close_communication_timeout_for_recovered_device(
            device, raw_message=raw_message, site=site, asset=asset,
        )
        analytics_errors.extend(recovery_errors)

    return IngestionResult(
        success=measurements_created + measurements_updated > 0,
        duplicate=False,
        raw_message=raw_message,
        measurements_created=measurements_created,
        measurements_updated=measurements_updated,
        events_created=events_created + analytics_events_created,
        analytics_events_created=analytics_events_created,
        errors=analytics_errors,
    )


def _close_communication_timeout_for_recovered_device(
    device, *, raw_message, site, asset,
) -> list[str]:
    """
    Best-effort: close any open communication_timeout Event for this device.
    Errors are isolated and never roll back telemetry.
    """
    try:
        from apps.analytics.services.communication_timeouts import (
            close_communication_timeout_for_device,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not import communication_timeouts service")
        return [f"Communication timeout close import failed: {exc}"]

    try:
        close_communication_timeout_for_device(device)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to close communication_timeout for device_uid=%s",
            getattr(device, "device_uid", "<unknown>"),
        )
        try:
            _create_event(
                event_type=EventType.INGESTION_ERROR,
                severity=Severity.WARNING,
                title="Communication timeout close failed",
                description=str(exc),
                site=site,
                asset=asset,
                device=device,
                raw_message=raw_message,
            )
        except Exception:  # noqa: BLE001
            pass
        return [f"Communication timeout close failed: {exc}"]


def _evaluate_thresholds(
    measurements,
    *,
    raw_message,
    site,
    asset,
    device,
) -> tuple[int, list[str]]:
    """
    Run threshold analytics on the given Measurements after they have been
    committed. Returns (events_created, errors). Catches every exception so
    that telemetry persistence is never reverted by an analytics bug.
    """
    try:
        from apps.analytics.services.thresholds import evaluate_measurements_thresholds
    except Exception as exc:  # noqa: BLE001 — analytics import must never break ingestion
        logger.exception("Could not import threshold analytics module")
        return 0, [f"Analytics import failed: {exc}"]

    try:
        result = evaluate_measurements_thresholds(measurements)
        events_total = result.events_created + result.events_updated + result.events_closed
        errors = list(result.errors)
        if errors:
            _create_event(
                event_type=EventType.INGESTION_ERROR,
                severity=Severity.WARNING,
                title="Threshold analytics partial failure",
                description="; ".join(errors[:3]),
                site=site,
                asset=asset,
                device=device,
                raw_message=raw_message,
            )
        return events_total, errors
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected threshold analytics failure")
        try:
            _create_event(
                event_type=EventType.INGESTION_ERROR,
                severity=Severity.WARNING,
                title="Threshold analytics error",
                description=str(exc),
                site=site,
                asset=asset,
                device=device,
                raw_message=raw_message,
            )
        except Exception:  # noqa: BLE001
            pass
        return 0, [f"Threshold evaluation failed: {exc}"]


# ── Metric processing helpers ─────────────────────────────────────────────────

def _process_one_metric(
    metric_key: str,
    raw_value,
    site,
    asset,
    device,
    sensor,
    metric_def_cache,
    raw_message,
    measurement_ts,
):
    """
    Attempt to create or update a single Measurement.
    Returns a tuple ``(status, measurement)`` where ``status`` is one of
    ``'created' | 'updated' | 'unknown' | 'invalid'`` and ``measurement`` is
    the persisted Measurement object (or ``None`` when nothing was stored).
    """
    from apps.iot_config.models import MetricDefinition

    try:
        metric_def = MetricDefinition.objects.get(key=metric_key)
    except MetricDefinition.DoesNotExist:
        return "unknown", None

    try:
        value_float, value_int, value_bool, value_text = _coerce_metric_value(
            raw_value, metric_def.data_type
        )
    except (TypeError, ValueError):
        return "invalid", None

    measurement_obj, created = Measurement.objects.update_or_create(
        raw_message=raw_message,
        metric=metric_def,
        defaults={
            "site": site,
            "asset": asset,
            "device": device,
            "sensor": sensor,
            "timestamp": measurement_ts,
            "value_float": value_float,
            "value_int": value_int,
            "value_bool": value_bool,
            "value_text": value_text,
            "unit": metric_def.unit,
            "quality": MeasurementQuality.GOOD,
        },
    )
    return ("created" if created else "updated"), measurement_obj


def _coerce_metric_value(raw_value, data_type: str) -> tuple:
    """
    Convert raw_value to the correct storage field.
    Returns (value_float, value_int, value_bool, value_text).
    Raises TypeError/ValueError on conversion failure.
    """
    value_float = value_int = value_bool = None
    value_text = ""

    if data_type == DataType.FLOAT:
        value_float = float(raw_value)
    elif data_type == DataType.INTEGER:
        value_int = int(raw_value)
    elif data_type == DataType.BOOLEAN:
        if isinstance(raw_value, bool):
            value_bool = raw_value
        elif isinstance(raw_value, (int, float)):
            value_bool = bool(raw_value)
        else:
            value_bool = str(raw_value).lower() in ("true", "1", "yes")
    elif data_type == DataType.STRING:
        value_text = str(raw_value)
    else:
        value_float = float(raw_value)

    return value_float, value_int, value_bool, value_text


def _create_unknown_metric_event(metric_key, message_id, site, asset, device, raw_message) -> int:
    _create_event(
        event_type=EventType.VALIDATION_ERROR,
        severity=Severity.WARNING,
        title=f"Unknown metric key: '{metric_key}'",
        description=(
            f"No MetricDefinition found for key='{metric_key}'. "
            f"message_id='{message_id}'"
        ),
        site=site,
        asset=asset,
        device=device,
        raw_message=raw_message,
    )
    return 1


def _create_invalid_value_event(metric_key, raw_value, site, asset, device, raw_message) -> int:
    _create_event(
        event_type=EventType.VALIDATION_ERROR,
        severity=Severity.WARNING,
        title=f"Invalid value for metric '{metric_key}'",
        description=f"Could not convert value {raw_value!r} for metric '{metric_key}'",
        site=site,
        asset=asset,
        device=device,
        raw_message=raw_message,
    )
    return 1


# ── AssetState update ─────────────────────────────────────────────────────────

def _update_asset_state(
    asset,
    site,
    device,
    raw_message,
    metrics_payload: dict,
    payload_status: str,
    measurement_ts,
) -> None:
    operational_status = _PAYLOAD_STATUS_MAP.get(
        payload_status.lower(), None
    ) if payload_status else None

    state_defaults: dict = {
        "site": site,
        "device": device,
        "last_seen_at": measurement_ts,
        "last_measurement_at": measurement_ts,
        "last_raw_message": raw_message,
        "state_payload": {**metrics_payload, "status": payload_status},
    }

    # Only update operational status when we have a known mapping; keep existing otherwise
    if operational_status is not None:
        state_defaults["status"] = operational_status

    # Only overwrite individual metric snapshot fields when present in this message
    _maybe_set(state_defaults, "last_temperature_c", metrics_payload, "temperature_c")
    _maybe_set(state_defaults, "last_voltage_v", metrics_payload, "voltage_v")
    _maybe_set(state_defaults, "last_current_a", metrics_payload, "current_a")
    _maybe_set(state_defaults, "last_power_w", metrics_payload, "power_w")
    _maybe_set(state_defaults, "last_battery_soc_pct", metrics_payload, "battery_soc_pct")

    AssetState.objects.update_or_create(asset=asset, defaults=state_defaults)


def _maybe_set(defaults: dict, state_field: str, metrics: dict, metric_key: str) -> None:
    if metric_key in metrics:
        try:
            defaults[state_field] = float(metrics[metric_key])
        except (TypeError, ValueError):
            pass


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _parse_timestamp(raw_ts):
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime, or return None."""
    if not raw_ts:
        return None
    try:
        dt = parse_datetime(str(raw_ts))
        if dt is not None and dt.tzinfo is None:
            from django.utils.timezone import make_aware
            dt = make_aware(dt)
        return dt
    except (ValueError, OverflowError):
        return None


def _resolve_asset(site, device, asset_code_from_payload: str):
    """
    Resolve Asset using payload asset_id (as Asset.code within site),
    falling back to device.asset.
    Returns None when resolution fails.
    """
    from apps.assets.models import Asset

    if asset_code_from_payload:
        try:
            return Asset.objects.get(site=site, code=asset_code_from_payload)
        except Asset.DoesNotExist:
            # Fall back to device.asset before giving up
            return device.asset if device.asset else None

    return device.asset if device.asset else None


def _fail_raw(
    raw_message: RawMessage,
    *,
    error: str,
    event_type: str,
    title: str,
    site=None,
    device=None,
) -> IngestionResult:
    """Mark RawMessage as failed, create an Event, and return a failure IngestionResult."""
    raw_message.processing_status = ProcessingStatus.FAILED
    raw_message.error_message = error
    raw_message.save(update_fields=["processing_status", "error_message"])
    _create_event(
        event_type=event_type,
        severity=Severity.ERROR,
        title=title,
        description=error,
        site=site,
        device=device,
        raw_message=raw_message,
    )
    return IngestionResult(success=False, raw_message=raw_message, events_created=1, errors=[error])


def _create_event(
    event_type: str,
    severity: str,
    title: str,
    description: str = "",
    site=None,
    asset=None,
    device=None,
    sensor=None,
    metric=None,
    raw_message=None,
) -> Event:
    return Event.objects.create(
        event_type=event_type,
        severity=severity,
        status=EventStatus.OPEN,
        site=site,
        asset=asset,
        device=device,
        sensor=sensor,
        metric=metric,
        raw_message=raw_message,
        title=title,
        description=description,
        source=_INGESTION_SOURCE,
    )


def _save_minimal_raw(
    topic: str = "",
    payload=None,
    payload_text: str = "",
    source_type=SourceType.UNKNOWN,
    status: str = ProcessingStatus.FAILED,
    error: str = "",
    device_uid: str = "",
    message_id: str = "",
    parser_version: str = "",
    received_at=None,
) -> RawMessage:
    """Create a RawMessage with minimal information for diagnostic purposes."""
    if received_at is None:
        received_at = timezone.now()

    if payload is None:
        payload_dict: dict = {}
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        if not payload_text:
            payload_text = str(payload)
        payload_dict = {}

    return RawMessage.objects.create(
        source_type=source_type,
        topic=topic,
        payload=payload_dict,
        payload_text=payload_text,
        message_id=message_id,
        device_uid=device_uid,
        received_at=received_at,
        processing_status=status,
        error_message=error,
        parser_version=parser_version,
    )
