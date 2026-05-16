from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class SourceType(models.TextChoices):
    MQTT = "mqtt", "MQTT"
    REST = "rest", "REST"
    SIMULATOR = "simulator", "Simulator"
    MANUAL = "manual", "Manual"
    UNKNOWN = "unknown", "Unknown"


class ProcessingStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PARSED = "parsed", "Parsed"
    FAILED = "failed", "Failed"
    IGNORED = "ignored", "Ignored"
    DUPLICATE = "duplicate", "Duplicate"


class MeasurementQuality(models.TextChoices):
    GOOD = "good", "Good"
    ESTIMATED = "estimated", "Estimated"
    INVALID = "invalid", "Invalid"
    MISSING = "missing", "Missing"
    UNKNOWN = "unknown", "Unknown"


class RawMessage(BaseModel):
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.UNKNOWN,
    )
    topic = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict)
    payload_text = models.TextField(blank=True)
    message_id = models.CharField(max_length=128, blank=True, db_index=True)
    device_uid = models.CharField(max_length=128, blank=True, db_index=True)
    device = models.ForeignKey(
        "assets.Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raw_messages",
    )
    site = models.ForeignKey(
        "assets.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raw_messages",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raw_messages",
    )
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    payload_timestamp = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    parser_version = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Raw Message"
        verbose_name_plural = "Raw Messages"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["source_type"]),
        ]
        constraints = [
            # Partial unique constraint: enforce uniqueness only when message_id is non-empty.
            # Works on PostgreSQL and SQLite (3.8.9+). Prevents duplicate ingestion of the
            # same logical message while allowing multiple records with blank message_id.
            models.UniqueConstraint(
                fields=["message_id"],
                condition=models.Q(message_id__gt=""),
                name="unique_rawmessage_message_id_nonempty",
            ),
        ]

    def __str__(self) -> str:
        identifier = self.device_uid or (str(self.device_id) if self.device_id else "unknown")
        return f"[{self.source_type}] {identifier} @ {self.received_at:%Y-%m-%d %H:%M:%S}"


class Measurement(BaseModel):
    site = models.ForeignKey(
        "assets.Site",
        on_delete=models.CASCADE,
        related_name="measurements",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.CASCADE,
        related_name="measurements",
    )
    device = models.ForeignKey(
        "assets.Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="measurements",
    )
    sensor = models.ForeignKey(
        "assets.Sensor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="measurements",
    )
    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.PROTECT,
        related_name="measurements",
    )
    raw_message = models.ForeignKey(
        RawMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="measurements",
    )
    timestamp = models.DateTimeField(db_index=True)
    value_float = models.FloatField(null=True, blank=True)
    value_int = models.IntegerField(null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_text = models.CharField(max_length=512, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    quality = models.CharField(
        max_length=16,
        choices=MeasurementQuality.choices,
        default=MeasurementQuality.GOOD,
    )
    is_anomalous = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Measurement"
        verbose_name_plural = "Measurements"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["site", "timestamp"]),
            models.Index(fields=["asset", "timestamp"]),
            models.Index(fields=["device", "timestamp"]),
            models.Index(fields=["metric", "timestamp"]),
            models.Index(fields=["asset", "metric", "timestamp"]),
        ]
        constraints = [
            # When a raw_message is present, each metric may only appear once per message.
            # Prevents double-normalisation of the same payload. Nullable FK excluded by
            # condition so multiple measurements without a raw_message remain allowed.
            models.UniqueConstraint(
                fields=["raw_message", "metric"],
                condition=models.Q(raw_message__isnull=False),
                name="unique_measurement_raw_message_metric",
            ),
        ]

    @property
    def value(self):
        if self.value_float is not None:
            return self.value_float
        if self.value_int is not None:
            return self.value_int
        if self.value_bool is not None:
            return self.value_bool
        if self.value_text:
            return self.value_text
        return None

    def __str__(self) -> str:
        return (
            f"{self.asset} / {self.metric_id} = {self.value} "
            f"@ {self.timestamp:%Y-%m-%d %H:%M:%S}"
        )
