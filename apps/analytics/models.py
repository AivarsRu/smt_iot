from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.events.models import Severity


class ThresholdRule(BaseModel):
    """
    Configurable threshold for a single metric. Optionally scoped to a site,
    asset, or device. A rule must define at least one of ``lower_bound`` or
    ``upper_bound``. When a Measurement violates an enabled rule, the analytics
    service creates a ``threshold_anomaly`` Event; when the value returns to
    the allowed range and ``close_when_normal`` is True, the related open
    event is closed.
    """

    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)

    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.PROTECT,
        related_name="threshold_rules",
    )
    site = models.ForeignKey(
        "assets.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="threshold_rules",
    )
    asset = models.ForeignKey(
        "assets.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="threshold_rules",
    )
    device = models.ForeignKey(
        "assets.Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="threshold_rules",
    )

    is_enabled = models.BooleanField(default=True)
    lower_bound = models.FloatField(null=True, blank=True)
    upper_bound = models.FloatField(null=True, blank=True)

    severity = models.CharField(
        max_length=16,
        choices=[
            (Severity.WARNING, "Warning"),
            (Severity.ERROR, "Error"),
            (Severity.CRITICAL, "Critical"),
        ],
        default=Severity.WARNING,
    )
    message_template = models.TextField(blank=True)
    close_when_normal = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Threshold Rule"
        verbose_name_plural = "Threshold Rules"
        ordering = ["sort_order", "code"]
        indexes = [
            models.Index(fields=["is_enabled"]),
            models.Index(fields=["metric"]),
            models.Index(fields=["site", "metric"]),
            models.Index(fields=["asset", "metric"]),
            models.Index(fields=["device", "metric"]),
        ]

    def __str__(self) -> str:
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{self.code} ({metric_key})"

    def clean(self) -> None:
        super().clean()
        if self.lower_bound is None and self.upper_bound is None:
            raise ValidationError(
                "ThresholdRule must define at least one of lower_bound or upper_bound."
            )
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValidationError(
                "ThresholdRule.lower_bound must not exceed upper_bound."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
