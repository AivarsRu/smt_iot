import random
import uuid

from django.utils import timezone


class SimulatorMetricProfileConfigError(ValueError):
    """
    Raised when ``SimulatorMetricProfile`` rows for a single
    ``SimulatorScenarioDevice`` cannot be safely serialised into the
    flat ``metrics`` payload. The current MQTT contract has no per-metric
    sensor field, so two sensors producing the same metric key on the
    same device would silently overwrite each other.
    """


def generate_payload(scenario_device, *, rng=None, message_id=None) -> tuple:
    """
    Returns (topic_str, payload_dict) for one SimulatorScenarioDevice.

    Each enabled ``SimulatorMetricProfile`` MUST reference a Sensor whose
    Device equals ``scenario_device.device``. Two enabled profiles on the
    same scenario_device that produce the same metric key from different
    sensors raise ``SimulatorMetricProfileConfigError`` because the flat
    MQTT payload cannot distinguish them.

    Args:
        scenario_device: SimulatorScenarioDevice instance (device + asset must be preloaded).
        rng: optional random.Random instance for deterministic tests.
        message_id: optional UUID string override (for tests).
    """
    from apps.simulator.services.topic_builder import build_telemetry_topic

    if rng is None:
        rng = random.Random()

    device = scenario_device.device
    asset = device.asset

    topic = build_telemetry_topic(device)

    metrics: dict = {}
    metric_key_to_sensor: dict = {}
    enabled_profiles = list(
        scenario_device.metric_profiles
        .filter(is_enabled=True)
        .select_related("metric", "sensor", "sensor__device")
        .order_by("sort_order")
    )
    for profile in enabled_profiles:
        # Sensor must be configured and must belong to the same device.
        if profile.sensor_id is None:
            raise SimulatorMetricProfileConfigError(
                f"SimulatorMetricProfile id={profile.id} has no sensor; "
                f"sensor-centric data model requires every enabled profile "
                f"to reference a Sensor."
            )
        if profile.sensor.device_id != device.id:
            raise SimulatorMetricProfileConfigError(
                f"SimulatorMetricProfile id={profile.id} sensor "
                f"'{profile.sensor.code}' belongs to a different device "
                f"than scenario_device.device='{device.device_uid}'."
            )

        metric_key = profile.metric.key
        existing_sensor = metric_key_to_sensor.get(metric_key)
        if existing_sensor is not None and existing_sensor != profile.sensor_id:
            raise SimulatorMetricProfileConfigError(
                f"Duplicate metric key '{metric_key}' for scenario_device "
                f"'{scenario_device}': two enabled SimulatorMetricProfile "
                f"rows produce the same metric from different sensors. "
                f"The flat MQTT payload cannot represent this — fix the "
                f"scenario configuration."
            )

        metrics[metric_key] = _generate_value(profile, rng)
        metric_key_to_sensor[metric_key] = profile.sensor_id

    status = scenario_device.status_override or scenario_device.scenario.default_status

    payload = {
        "message_id": message_id or str(uuid.uuid4()),
        "device_id": device.device_uid,
        "asset_id": asset.code,
        "timestamp": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": metrics,
        "status": status,
        "firmware_version": device.firmware_version or "",
    }
    return topic, payload


def _generate_value(profile, rng: random.Random) -> float:
    mode = profile.generation_mode
    value = profile.base_value

    if mode in ("random_noise", "random_walk"):
        if profile.noise_amplitude:
            value += rng.uniform(-profile.noise_amplitude, profile.noise_amplitude)

    if profile.min_value is not None:
        value = max(value, profile.min_value)
    if profile.max_value is not None:
        value = min(value, profile.max_value)

    return round(value, 4)
