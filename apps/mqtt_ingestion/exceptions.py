class TopicParseError(Exception):
    """Raised when an MQTT topic does not match the expected SMT structure."""


class PayloadValidationError(Exception):
    """Raised when a required payload field is missing or malformed."""


class IngestionError(Exception):
    """Raised for unexpected errors during the ingestion pipeline."""
