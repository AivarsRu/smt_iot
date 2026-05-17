from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel
from apps.events.models import Severity


class ThresholdRuleScope(models.TextChoices):
    """
    Explicit scope of a ``ThresholdRule``.

    The previous implementation treated a NULL ``site/asset/device/sensor`` FK
    as "wildcard". That semantics was dangerous in the real domain: a rule
    intended for one specific sensor (e.g. outdoor temperature ≤ 40 °C) would
    silently fire for every other sensor under the same metric (e.g. a motor
    temperature sensor where 80 °C is normal).

    From Phase 7 onwards each rule must declare its scope explicitly:

      * ``GLOBAL`` — applies to **every** measurement of ``metric``.
        FKs must be empty.
      * ``SITE``   — applies only to measurements at ``site``.
      * ``ASSET``  — applies only to measurements on ``asset``.
      * ``DEVICE`` — applies only to measurements from ``device``.
      * ``SENSOR`` — applies only to measurements from ``sensor``.
    """

    GLOBAL = "global", "Global"
    SITE = "site", "Site"
    ASSET = "asset", "Asset"
    DEVICE = "device", "Device"
    SENSOR = "sensor", "Sensor"


class ThresholdRule(BaseModel):
    """
    Configurable threshold for a single metric scoped at exactly one level
    (global / site / asset / device / sensor). A rule must define at least
    one of ``lower_bound`` or ``upper_bound``. When a Measurement violates an
    enabled rule, the analytics service creates a ``threshold_anomaly`` Event;
    when the value returns to the allowed range and ``close_when_normal`` is
    True, the related open event is closed.

    Scope precision is enforced by :meth:`clean`: the FK matching the chosen
    scope is required, and FKs for finer or unrelated levels must be empty
    (or fully consistent — e.g. a sensor-scoped rule may have its ``device``
    auto-filled to ``sensor.device`` but must not point at a different
    device).
    """

    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)

    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.PROTECT,
        related_name="threshold_rules",
    )

    # The chosen level of precision. See ``ThresholdRuleScope``.
    scope_level = models.CharField(
        max_length=16,
        choices=ThresholdRuleScope.choices,
        default=ThresholdRuleScope.SENSOR,
        db_index=True,
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
    sensor = models.ForeignKey(
        "assets.Sensor",
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

    # Sentinel used by ``save()`` to detect ``is_enabled`` transitions
    # without an extra DB roundtrip. Set in ``__init__``; the value
    # snapshots what was loaded from the database (or the value the
    # caller passed when constructing a fresh instance).
    _prev_is_enabled: bool

    class Meta:
        verbose_name = "Threshold Rule"
        verbose_name_plural = "Threshold Rules"
        ordering = ["sort_order", "code"]
        indexes = [
            models.Index(fields=["is_enabled"]),
            models.Index(fields=["metric"]),
            models.Index(fields=["scope_level", "metric"]),
            models.Index(fields=["site", "metric"]),
            models.Index(fields=["asset", "metric"]),
            models.Index(fields=["device", "metric"]),
            models.Index(fields=["sensor", "metric"]),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot the ``is_enabled`` value as it stands right after
        # __init__. For loaded rows this matches the DB; for fresh
        # instances it matches whatever the caller passed (or the model
        # default of ``True``). ``save()`` uses this to detect a
        # True → False transition and auto-close the rule's open events.
        self._prev_is_enabled = self.is_enabled

    def __str__(self) -> str:
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{self.code} ({metric_key}, {self.scope_level})"

    # ── Validation ───────────────────────────────────────────────────────

    def clean(self) -> None:
        super().clean()
        self._validate_bounds()
        self._autofill_scope_fields()
        self._validate_scope()
        self._validate_sensor_metric_capability()

    def _validate_bounds(self) -> None:
        if self.lower_bound is None and self.upper_bound is None:
            raise ValidationError(
                "ThresholdRule must define at least one of "
                "lower_bound or upper_bound."
            )
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValidationError(
                "ThresholdRule.lower_bound must not exceed upper_bound."
            )

    def _autofill_scope_fields(self) -> None:
        """
        For asset/device/sensor scopes, derive higher-level FKs from the
        chosen target if they were left blank. This is a convenience for
        operator forms; it keeps the row internally consistent without
        forcing the caller to repeat the same data four times.

        We refuse to *overwrite* an explicitly-set FK that conflicts —
        :meth:`_validate_scope` enforces equality below.
        """
        if self.scope_level == ThresholdRuleScope.SENSOR and self.sensor_id:
            sensor = self.sensor
            if self.device_id is None:
                self.device = sensor.device
            if self.asset_id is None and sensor.device.asset_id:
                self.asset = sensor.device.asset
            if self.site_id is None and sensor.device.site_id:
                self.site = sensor.device.site
        elif self.scope_level == ThresholdRuleScope.DEVICE and self.device_id:
            device = self.device
            if self.asset_id is None and device.asset_id:
                self.asset = device.asset
            if self.site_id is None and device.site_id:
                self.site = device.site
        elif self.scope_level == ThresholdRuleScope.ASSET and self.asset_id:
            asset = self.asset
            if self.site_id is None and asset.site_id:
                self.site = asset.site

    def _validate_scope(self) -> None:
        """
        Enforce that exactly the right scope FK is populated and that no
        finer-grained FK leaks in. We treat any populated FK below the
        rule's scope_level as an error to avoid ambiguity at evaluation
        time.
        """
        scope = self.scope_level

        if scope == ThresholdRuleScope.GLOBAL:
            for field_name in ("site", "asset", "device", "sensor"):
                if getattr(self, f"{field_name}_id"):
                    raise ValidationError({
                        field_name: (
                            f"Global ThresholdRule must not set {field_name}."
                        ),
                    })
            return

        if scope == ThresholdRuleScope.SITE:
            if not self.site_id:
                raise ValidationError({"site": "Site-scoped rule requires site."})
            for field_name in ("asset", "device", "sensor"):
                if getattr(self, f"{field_name}_id"):
                    raise ValidationError({
                        field_name: (
                            f"Site-scoped ThresholdRule must not set {field_name}."
                        ),
                    })
            return

        if scope == ThresholdRuleScope.ASSET:
            if not self.asset_id:
                raise ValidationError({"asset": "Asset-scoped rule requires asset."})
            for field_name in ("device", "sensor"):
                if getattr(self, f"{field_name}_id"):
                    raise ValidationError({
                        field_name: (
                            f"Asset-scoped ThresholdRule must not set {field_name}."
                        ),
                    })
            # site, if set, must match asset.site.
            if self.site_id and self.asset.site_id != self.site_id:
                raise ValidationError({
                    "site": "Site must match the asset's site.",
                })
            return

        if scope == ThresholdRuleScope.DEVICE:
            if not self.device_id:
                raise ValidationError({"device": "Device-scoped rule requires device."})
            if self.sensor_id:
                raise ValidationError({
                    "sensor": "Device-scoped ThresholdRule must not set sensor.",
                })
            if self.asset_id and self.device.asset_id != self.asset_id:
                raise ValidationError({
                    "asset": "Asset must match the device's asset.",
                })
            if self.site_id and self.device.site_id != self.site_id:
                raise ValidationError({
                    "site": "Site must match the device's site.",
                })
            return

        if scope == ThresholdRuleScope.SENSOR:
            if not self.sensor_id:
                raise ValidationError({
                    "sensor": "Sensor-scoped rule requires sensor.",
                })
            sensor = self.sensor
            if self.device_id and sensor.device_id != self.device_id:
                raise ValidationError({
                    "device": "Device must match the sensor's device.",
                })
            if self.asset_id and sensor.device.asset_id != self.asset_id:
                raise ValidationError({
                    "asset": "Asset must match the sensor's asset.",
                })
            if self.site_id and sensor.device.site_id != self.site_id:
                raise ValidationError({
                    "site": "Site must match the sensor's site.",
                })
            return

        raise ValidationError({
            "scope_level": f"Unknown scope_level '{scope}'.",
        })

    def _validate_sensor_metric_capability(self) -> None:
        """
        A sensor-scoped rule must point at a metric the sensor actually
        produces. If no SensorMetric mapping exists for (sensor, metric),
        the rule would never fire on real data — that is a configuration
        bug, surface it at validation time.
        """
        if (
            self.scope_level != ThresholdRuleScope.SENSOR
            or not self.sensor_id
            or not self.metric_id
        ):
            return
        # Local import to avoid an import cycle at module load.
        from apps.assets.models import SensorMetric

        exists = SensorMetric.objects.filter(
            sensor_id=self.sensor_id,
            metric_id=self.metric_id,
            is_active=True,
        ).exists()
        if not exists:
            raise ValidationError({
                "metric": (
                    "Sensor does not declare this metric. Configure a "
                    "SensorMetric for the chosen sensor + metric first."
                ),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        # Detect the True → False transition *before* delegating to
        # ``super().save()`` because ``_state.adding`` flips to False
        # after the first save and we'd otherwise lose the signal.
        transition_to_disabled = (
            not self._state.adding
            and self._prev_is_enabled
            and not self.is_enabled
        )
        result = super().save(*args, **kwargs)
        if transition_to_disabled:
            self._close_open_events_on_disable()
        # Refresh the snapshot so a follow-up ``rule.save()`` from the
        # same Python instance doesn't fire the transition logic twice.
        self._prev_is_enabled = self.is_enabled
        return result

    def _close_open_events_on_disable(self) -> int:
        """
        Auto-close every still-open ``threshold_anomaly`` event whose
        ``payload.rule_code`` matches this rule.

        Why this exists: once ``is_enabled`` is False, the analytics
        service (``_applicable_rules``) skips the rule entirely, so a
        later "return-to-normal" measurement can no longer reach
        ``_close_open_events`` to close the event. Without this hook the
        rule's open events would sit on the dashboard forever.

        Each closed event gets ``payload.closed_reason='rule_disabled'``
        and a ``closed_at`` timestamp so operators can audit the
        disable-driven close vs. a normal threshold close.

        Returns the number of events closed (useful for tests).
        """
        # Local imports to keep the analytics → events dependency
        # one-directional at module load time.
        from django.utils import timezone

        from apps.events.models import Event, EventStatus, EventType

        now = timezone.now()
        open_events = Event.objects.filter(
            event_type=EventType.THRESHOLD_ANOMALY,
            status=EventStatus.OPEN,
            payload__rule_code=self.code,
        )
        closed = 0
        for ev in open_events:
            ev.status = EventStatus.CLOSED
            ev.closed_at = now
            ev.payload = {
                **(ev.payload or {}),
                "closed_reason": "rule_disabled",
                "closed_at": now.isoformat(),
            }
            ev.save(update_fields=[
                "status", "closed_at", "payload", "updated_at",
            ])
            closed += 1
        return closed


class ThresholdRulePreset(BaseModel):
    """
    Template for a common threshold rule. The Stage 4 operator form uses
    presets to spin up a concrete :class:`ThresholdRule` scoped to the
    current Asset/Device/Sensor/Metric without typing bounds by hand.

    Presets never affect ingestion or analytics directly — only the
    derived ``ThresholdRule`` is evaluated by
    :mod:`apps.analytics.services.thresholds`. A preset has no ``scope_level``
    of its own; scope is decided by *where* the operator materialises the
    preset (today: always sensor-scoped from the sensor configuration page).
    """

    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)

    metric = models.ForeignKey(
        "iot_config.MetricDefinition",
        on_delete=models.PROTECT,
        related_name="threshold_rule_presets",
    )
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
    close_when_normal = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Threshold Rule Preset"
        verbose_name_plural = "Threshold Rule Presets"
        ordering = ["code"]

    def __str__(self) -> str:
        metric_key = getattr(self.metric, "key", str(self.metric_id))
        return f"{self.code} → {metric_key}"

    def clean(self) -> None:
        super().clean()
        if self.lower_bound is None and self.upper_bound is None:
            raise ValidationError(
                "ThresholdRulePreset must define at least one of "
                "lower_bound or upper_bound."
            )
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValidationError(
                "ThresholdRulePreset.lower_bound must not exceed upper_bound."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
