import random
import uuid

from django.utils import timezone


def generate_payload(scenario_device, *, rng=None, message_id=None) -> tuple:
    """
    Returns (topic_str, payload_dict) for one SimulatorScenarioDevice.

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

    metrics = {}
    for profile in (
        scenario_device.metric_profiles
        .filter(is_enabled=True)
        .select_related("metric")
        .order_by("sort_order")
    ):
        metrics[profile.metric.key] = _generate_value(profile, rng)

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
