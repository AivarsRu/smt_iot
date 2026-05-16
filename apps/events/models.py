from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class EventType(models.TextChoices):
    SYSTEM = "system", "System"
    VALIDATION_ERROR = "validation_error", "Validation Error"
    DEVICE_STATUS = "device_status", "Device Status"
    THRESHOLD_ANOMALY = "threshold_anomaly", "Threshold Anomaly"
    COMMUNICATION_TIMEOUT = "communication_timeout", "Communication Timeout"
    INGESTION_ERROR = "ingestion_error", "Ingestion Error"
    SIMULATOR_EVENT = "simulator_event", "Simulator Event"


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class EventStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    CLOSED = "closed", "Closed"
    IGNORED = "ignored", "Ignored"


class Event(BaseModel):
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        default=EventType.SYSTEM,
        db_index=True,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.INFO,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=EventStatus.choices,
        default=EventStatus.OPEN,
        db_index=True,
    )
    site = models.ForeignKey(
        "assets.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    device = models.ForeignKey(
        "assets.Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    sensor = models.ForeignKey(
        "assets.Sensor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    measurement = models.ForeignKey(
        "telemetry.Measurement",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    raw_message = models.ForeignKey(
        "telemetry.RawMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    title = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Event"
        verbose_name_plural = "Events"
        ordering = ["-detected_at"]
        indexes = [
            models.Index(fields=["site", "status"]),
            models.Index(fields=["asset", "status"]),
            models.Index(fields=["device", "status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.event_type}] [{self.severity}] [{self.status}] {self.title}"
