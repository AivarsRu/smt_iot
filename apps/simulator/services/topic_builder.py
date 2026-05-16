from django.conf import settings


class SimulatorConfigError(Exception):
    pass


def build_telemetry_topic(device) -> str:
    """Build smt/{SMT_ENV}/{site_code}/{asset_type}/{device_uid}/telemetry."""
    if device.asset is None:
        raise SimulatorConfigError(
            f"Device '{device.device_uid}' has no assigned asset; "
            "asset_type is required for topic."
        )
    env = settings.SMT_ENV
    site_code = device.site.code
    asset_type = device.asset.asset_type
    device_uid = device.device_uid
    return f"smt/{env}/{site_code}/{asset_type}/{device_uid}/telemetry"
