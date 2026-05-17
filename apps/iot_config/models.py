from django.db import models

from apps.core.models import BaseModel, DataType, MqttTopicType


class MetricDefinition(BaseModel):
    key = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=32, blank=True)
    data_type = models.CharField(
        max_length=16,
        choices=DataType.choices,
        default=DataType.FLOAT,
    )
    normal_min = models.FloatField(null=True, blank=True)
    normal_max = models.FloatField(null=True, blank=True)
    warning_min = models.FloatField(null=True, blank=True)
    warning_max = models.FloatField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Metric Definition"
        verbose_name_plural = "Metric Definitions"
        ordering = ["sort_order", "key"]

    def __str__(self) -> str:
        return f"{self.key} ({self.unit})" if self.unit else self.key


class MqttTopicTemplate(BaseModel):
    name = models.CharField(max_length=128)
    topic_type = models.CharField(
        max_length=16,
        choices=MqttTopicType.choices,
    )
    template = models.CharField(max_length=512)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "MQTT Topic Template"
        verbose_name_plural = "MQTT Topic Templates"
        ordering = ["topic_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["topic_type", "name"],
                name="unique_mqtt_topic_template_type_name",
            )
        ]

    def __str__(self) -> str:
        return f"[{self.topic_type}] {self.template}"


class DeviceProfile(BaseModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    device_type = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    default_expected_interval_seconds = models.PositiveIntegerField(default=60)
    metrics = models.ManyToManyField(
        MetricDefinition,
        through="DeviceProfileMetric",
        related_name="device_profiles",
        blank=True,
    )

    class Meta:
        verbose_name = "Device Profile"
        verbose_name_plural = "Device Profiles"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class DeviceProfileMetric(models.Model):
    profile = models.ForeignKey(
        DeviceProfile,
        on_delete=models.CASCADE,
        related_name="profile_metrics",
    )
    metric = models.ForeignKey(
        MetricDefinition,
        on_delete=models.CASCADE,
        related_name="profile_metrics",
    )
    is_required = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Device Profile Metric"
        verbose_name_plural = "Device Profile Metrics"
        ordering = ["sort_order", "metric__key"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "metric"],
                name="unique_device_profile_metric",
            )
        ]

    def __str__(self) -> str:
        return f"{self.profile.code} / {self.metric.key}"


class SensorMetricPreset(BaseModel):
    """
    Reusable single-sensor/metric template used by the operator UI.

    A preset captures the common case "this kind of sensor produces this
    metric" so the operator does not have to retype the same
    ``sensor_type`` + ``MetricDefinition`` combination for every new
    sensor. When chosen in the Stage 4 form, the dashboard prefills:

      * the new Sensor's ``sensor_type`` and ``name`` (from
        ``default_sensor_name``);
      * the ``SensorMetric`` row using ``metric``, ``is_required`` and
        ``sort_order``.

    Presets are templates only — they never appear in measurements or
    ingestion. The authoritative live mapping remains ``SensorMetric``.
    """

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    sensor_type = models.CharField(max_length=64, blank=True)
    metric = models.ForeignKey(
        MetricDefinition,
        on_delete=models.PROTECT,
        related_name="sensor_metric_presets",
    )
    default_sensor_name = models.CharField(max_length=256, blank=True)
    default_unit = models.CharField(max_length=32, blank=True)
    is_required = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Sensor Metric Preset"
        verbose_name_plural = "Sensor Metric Presets"
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{self.code} → {metric_key}"
