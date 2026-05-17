from django.db import models

from apps.core.models import BaseModel, OperationalStatus


class AssetType(models.TextChoices):
    CHARGER = "charger", "Charger"
    BATTERY = "battery", "Battery"
    SENSOR_NODE = "sensor_node", "Sensor Node"
    INFRASTRUCTURE_NODE = "infrastructure_node", "Infrastructure Node"
    OTHER = "other", "Other"


class Site(BaseModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Riga")
    is_demo = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Asset(BaseModel):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="assets")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=256)
    asset_type = models.CharField(
        max_length=32,
        choices=AssetType.choices,
        default=AssetType.OTHER,
    )
    status = models.CharField(
        max_length=32,
        choices=OperationalStatus.choices,
        default=OperationalStatus.UNKNOWN,
    )
    description = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    external_id = models.CharField(max_length=128, blank=True)

    class Meta:
        verbose_name = "Asset"
        verbose_name_plural = "Assets"
        ordering = ["site", "code"]
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="unique_asset_site_code")
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Device(BaseModel):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="devices")
    asset = models.ForeignKey(
        Asset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="devices",
    )
    device_uid = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=256)
    device_type = models.CharField(max_length=64, blank=True)
    is_simulated = models.BooleanField(default=False)
    expected_interval_seconds = models.PositiveIntegerField(default=60)
    firmware_version = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=32,
        choices=OperationalStatus.choices,
        default=OperationalStatus.UNKNOWN,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Device"
        verbose_name_plural = "Devices"
        ordering = ["device_uid"]

    def __str__(self) -> str:
        return f"{self.device_uid} — {self.name}"


class Sensor(BaseModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="sensors")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=256)
    sensor_type = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    # Convenience M2M — actual rows live in ``SensorMetric``. Every metric a
    # sensor can produce must be declared explicitly through this table; the
    # ingestion layer uses it to resolve ``Measurement.sensor`` for each
    # incoming metric key.
    metrics = models.ManyToManyField(
        "iot_config.MetricDefinition",
        through="SensorMetric",
        related_name="sensors",
        blank=True,
    )

    class Meta:
        verbose_name = "Sensor"
        verbose_name_plural = "Sensors"
        ordering = ["device", "code"]
        constraints = [
            models.UniqueConstraint(fields=["device", "code"], name="unique_sensor_device_code")
        ]

    def __str__(self) -> str:
        return f"{self.device.device_uid} / {self.code}"


class SensorMetric(BaseModel):
    """
    Declares which ``MetricDefinition`` a ``Sensor`` is capable of producing.

    This is the canonical source of sensor↔metric capability used by:
      * MQTT ingestion (to resolve ``Measurement.sensor`` per metric key);
      * the simulator (``SimulatorMetricProfile.sensor`` references a
        ``Sensor`` whose ``SensorMetric`` covers the configured metric);
      * analytics (``ThresholdRule.sensor`` optionally scopes a rule to a
        single sensor/metric pair).

    ``iot_config.DeviceProfileMetric`` is kept only as a profile-/template-
    level catalogue and must not be treated as the live capability mapping.
    """

    sensor = models.ForeignKey(
        Sensor,
        on_delete=models.CASCADE,
        related_name="sensor_metrics",
    )
    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.PROTECT,
        related_name="sensor_metrics",
    )
    is_required = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Sensor Metric"
        verbose_name_plural = "Sensor Metrics"
        ordering = ["sensor", "sort_order", "metric__key"]
        constraints = [
            models.UniqueConstraint(
                fields=["sensor", "metric"],
                name="unique_sensor_metric_sensor_metric",
            ),
        ]
        indexes = [
            models.Index(fields=["metric"]),
        ]

    def __str__(self) -> str:
        device_uid = getattr(self.sensor.device, "device_uid", "?")
        sensor_code = self.sensor.code
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{device_uid} / {sensor_code} / {metric_key}"
