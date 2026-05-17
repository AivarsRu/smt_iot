from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class SimulatorScenario(BaseModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    site = models.ForeignKey(
        "assets.Site",
        on_delete=models.CASCADE,
        related_name="simulator_scenarios",
    )
    default_status = models.CharField(max_length=32, default="charging")
    interval_seconds = models.PositiveIntegerField(default=60)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Simulator Scenario"
        verbose_name_plural = "Simulator Scenarios"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class SimulatorScenarioDevice(BaseModel):
    scenario = models.ForeignKey(
        SimulatorScenario,
        on_delete=models.CASCADE,
        related_name="scenario_devices",
    )
    device = models.ForeignKey(
        "assets.Device",
        on_delete=models.CASCADE,
        related_name="scenario_devices",
    )
    device_profile = models.ForeignKey(
        "iot_config.DeviceProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scenario_devices",
    )
    is_enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    status_override = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "Simulator Scenario Device"
        verbose_name_plural = "Simulator Scenario Devices"
        ordering = ["scenario", "sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "device"],
                name="unique_simulator_scenario_device",
            )
        ]

    def __str__(self) -> str:
        return f"{self.scenario.code} / {self.device.device_uid}"


class SimulatorMetricProfile(BaseModel):
    GENERATION_MODE_CHOICES = [
        ("constant", "Constant"),
        ("random_noise", "Random Noise"),
        ("random_walk", "Random Walk"),
    ]

    scenario_device = models.ForeignKey(
        SimulatorScenarioDevice,
        on_delete=models.CASCADE,
        related_name="metric_profiles",
    )
    # Sensor that produces this metric. Nullable at the DB level only to
    # tolerate legacy rows created before the sensor-centric data model;
    # the simulator pipeline (``payload_generator`` / ``run_simulator``)
    # requires a non-null sensor and will raise a clear configuration
    # error when it is missing.
    sensor = models.ForeignKey(
        "assets.Sensor",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="simulator_metric_profiles",
    )
    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.CASCADE,
        related_name="metric_profiles",
    )
    base_value = models.FloatField()
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)
    noise_amplitude = models.FloatField(default=0.0)
    generation_mode = models.CharField(
        max_length=32,
        choices=GENERATION_MODE_CHOICES,
        default="constant",
    )
    is_enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Simulator Metric Profile"
        verbose_name_plural = "Simulator Metric Profiles"
        ordering = ["scenario_device", "sort_order"]
        constraints = [
            # New uniqueness (sensor-aware). Two rows that target the same
            # (scenario_device, sensor, metric) triple are still rejected.
            models.UniqueConstraint(
                fields=["scenario_device", "sensor", "metric"],
                name="unique_simulator_metric_profile_sensor",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.sensor_id is None:
            return
        # Sensor must belong to the same Device as the scenario_device.
        if (
            self.scenario_device_id is not None
            and self.sensor.device_id != self.scenario_device.device_id
        ):
            raise ValidationError(
                "SimulatorMetricProfile.sensor must belong to the same "
                "Device as scenario_device.device."
            )
        # Sensor must declare this metric via SensorMetric.
        from apps.assets.models import SensorMetric
        if self.metric_id is not None and not SensorMetric.objects.filter(
            sensor=self.sensor, metric_id=self.metric_id,
        ).exists():
            raise ValidationError(
                "SimulatorMetricProfile.metric is not declared by the "
                "linked Sensor (no matching SensorMetric row)."
            )

    def __str__(self) -> str:
        scenario_code = getattr(self.scenario_device.scenario, "code", "?")
        device_uid = getattr(self.scenario_device.device, "device_uid", "?")
        sensor_code = getattr(self.sensor, "code", "?") if self.sensor_id else "?"
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{scenario_code} / {device_uid} / {sensor_code} / {metric_key}"


class SimulatorRun(BaseModel):
    RUN_STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    scenario = models.ForeignKey(
        SimulatorScenario,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=RUN_STATUS_CHOICES,
        default="running",
    )
    messages_published = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Simulator Run"
        verbose_name_plural = "Simulator Runs"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.scenario.code} [{self.status}] {self.started_at:%Y-%m-%d %H:%M}"
