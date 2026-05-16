from django.db import models

from apps.core.models import BaseModel, OperationalStatus


class AssetState(BaseModel):
    asset = models.OneToOneField(
        "assets.Asset",
        on_delete=models.CASCADE,
        related_name="state",
    )
    site = models.ForeignKey(
        "assets.Site",
        on_delete=models.CASCADE,
        related_name="asset_states",
    )
    device = models.ForeignKey(
        "assets.Device",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_states",
    )
    status = models.CharField(
        max_length=32,
        choices=OperationalStatus.choices,
        default=OperationalStatus.UNKNOWN,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_measurement_at = models.DateTimeField(null=True, blank=True)
    last_raw_message = models.ForeignKey(
        "telemetry.RawMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="asset_states",
    )
    last_temperature_c = models.FloatField(null=True, blank=True)
    last_voltage_v = models.FloatField(null=True, blank=True)
    last_current_a = models.FloatField(null=True, blank=True)
    last_power_w = models.FloatField(null=True, blank=True)
    last_battery_soc_pct = models.FloatField(null=True, blank=True)
    active_anomaly_count = models.PositiveIntegerField(default=0)
    has_active_anomaly = models.BooleanField(default=False)
    state_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Asset State"
        verbose_name_plural = "Asset States"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["last_seen_at"]),
            models.Index(fields=["has_active_anomaly"]),
            models.Index(fields=["site", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset} — {self.status}"
