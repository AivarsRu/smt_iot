from dataclasses import dataclass

from apps.mqtt_ingestion.exceptions import TopicParseError

_EXPECTED_PREFIX = "smt"
_EXPECTED_PARTS = 6


@dataclass
class ParsedTopic:
    environment: str
    site_code: str
    asset_type: str
    device_uid: str
    message_type: str
    original_topic: str


def parse_topic(topic: str) -> ParsedTopic:
    """
    Parse an SMT MQTT topic into its structured components.

    Expected format:
        smt/{environment}/{site_code}/{asset_type}/{device_uid}/{message_type}

    Raises TopicParseError if the topic does not conform.
    """
    parts = topic.strip().split("/")

    if len(parts) != _EXPECTED_PARTS:
        raise TopicParseError(
            f"Invalid topic '{topic}': expected {_EXPECTED_PARTS} segments separated by '/', "
            f"got {len(parts)}. Format: smt/{{env}}/{{site}}/{{asset_type}}/{{device_id}}/{{type}}"
        )

    if parts[0] != _EXPECTED_PREFIX:
        raise TopicParseError(
            f"Invalid topic '{topic}': must start with '{_EXPECTED_PREFIX}/', got '{parts[0]}/'"
        )

    _, environment, site_code, asset_type, device_uid, message_type = parts

    empty = [name for name, val in [
        ("environment", environment),
        ("site_code", site_code),
        ("asset_type", asset_type),
        ("device_uid", device_uid),
        ("message_type", message_type),
    ] if not val]

    if empty:
        raise TopicParseError(
            f"Invalid topic '{topic}': empty segment(s): {empty}"
        )

    return ParsedTopic(
        environment=environment,
        site_code=site_code,
        asset_type=asset_type,
        device_uid=device_uid,
        message_type=message_type,
        original_topic=topic,
    )
