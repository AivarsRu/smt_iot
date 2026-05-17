"""
Server-rendered Django forms for the **staged** operator workflow.

Phase 7, Task 3B replaces the single-page mega-form from Task 3 with a
sequence of small forms — one per workflow stage:

  * Stage 1 :class:`AssetCreateStageForm`         (Site + Asset)
  * Stage 2a :class:`DeviceCreateStageForm`       (new Device for Asset)
  * Stage 2b :class:`DeviceAttachStageForm`       (attach existing Device)
  * Stage 3 :class:`SensorCreateStageForm`        (one Sensor on a Device)
  * Stage 4 :class:`SensorMetricStageForm`        (MetricDefinition +
                                                   SensorMetric +
                                                   optional ThresholdRule)

Each form covers exactly one stage and runs inside its own
``transaction.atomic`` block in the matching view. Technical identifier
fields (``Asset.code``, ``Device.device_uid``, ``Sensor.code``,
``ThresholdRule.code``) are deliberately **not** exposed — they are
generated server-side by :mod:`apps.assets.services.identifiers`.

The sensor-centric data-model invariant is still enforced:
``Stage 4`` is the only path that creates ``SensorMetric``; threshold
rules can only be created on top of an existing ``Sensor``/``Metric``
pair.
"""

from __future__ import annotations

from django import forms

from apps.analytics.models import (
    ThresholdRule,
    ThresholdRulePreset,
    ThresholdRuleScope,
)
from apps.assets.models import AssetType, Device, Sensor, Site
from apps.core.models import DataType, OperationalStatus
from apps.events.models import Severity
from apps.iot_config.models import MetricDefinition, SensorMetricPreset


# ── Constants ────────────────────────────────────────────────────────────────

# Curated timezone list for the Site form. The previous free-text field
# accepted arbitrary strings — that broke when an operator typed
# ``Europe/Tallin`` (one ``n``). Use a small, well-known set and reject
# anything else server-side.
ALLOWED_TIMEZONES = (
    "UTC",
    "Europe/Riga",
    "Europe/London",
    "Europe/Tallinn",
    "Europe/Vilnius",
    "Europe/Helsinki",
    "Europe/Stockholm",
    "Europe/Berlin",
)
DEFAULT_TIMEZONE = "Europe/Riga"
TIMEZONE_CHOICES = tuple((tz, tz) for tz in ALLOWED_TIMEZONES)

SITE_MODE_EXISTING = "existing"
SITE_MODE_NEW = "new"
SITE_MODE_CHOICES = (
    (SITE_MODE_EXISTING, "Izmantot esošu objektu"),
    (SITE_MODE_NEW, "Izveidot jaunu objektu"),
)

METRIC_MODE_PRESET = "preset"
METRIC_MODE_EXISTING = "existing"
METRIC_MODE_NEW = "new"
METRIC_MODE_CHOICES = (
    (METRIC_MODE_PRESET, "Izmantot SensorMetricPreset"),
    (METRIC_MODE_EXISTING, "Izvēlēties esošu MetricDefinition"),
    (METRIC_MODE_NEW, "Izveidot jaunu MetricDefinition"),
)

THRESHOLD_MODE_NONE = "none"
THRESHOLD_MODE_PRESET = "preset"
THRESHOLD_MODE_MANUAL = "manual"
THRESHOLD_MODE_CHOICES = (
    (THRESHOLD_MODE_NONE, "Neveidot sliekšņa noteikumu"),
    (THRESHOLD_MODE_PRESET, "Izmantot ThresholdRulePreset"),
    (THRESHOLD_MODE_MANUAL, "Definēt slieksni manuāli"),
)

# Explicit per-scope labels for the operator. Stage 4 defaults to ``sensor``
# (the natural scope when configuring from one sensor's metric page), but
# advanced operators can broaden the scope to device / asset / site /
# global on the same form. The model-level :class:`ThresholdRuleScope`
# enum is the source of truth; this tuple only adds Latvian labels.
THRESHOLD_SCOPE_CHOICES = (
    (
        ThresholdRuleScope.SENSOR,
        "Sensors (tikai šim sensoram)",
    ),
    (
        ThresholdRuleScope.DEVICE,
        "Ierīce (visiem ierīces sensoriem ar šo metriku)",
    ),
    (
        ThresholdRuleScope.ASSET,
        "Aktīvs (visām ierīcēm zem šī aktīva)",
    ),
    (
        ThresholdRuleScope.SITE,
        "Objekts (visiem aktīviem objektā)",
    ),
    (
        ThresholdRuleScope.GLOBAL,
        "Globāls (visiem mērījumiem ar šo metriku)",
    ),
)

# The edit page does NOT expose global scope — it operates inside a
# specific asset and the dashboard listing only shows rules reachable
# from that asset. Promoting a rule to global must go through admin to
# avoid surprises.
THRESHOLD_EDIT_SCOPE_CHOICES = tuple(
    (value, label) for value, label in THRESHOLD_SCOPE_CHOICES
    if value != ThresholdRuleScope.GLOBAL
)


# ── Stage 1: Asset (+ optional new Site) ────────────────────────────────────

class AssetCreateStageForm(forms.Form):
    """
    Stage 1 — create the ``Asset`` and optionally a new ``Site``.

    The operator does *not* type ``Asset.code`` — the view fills it in
    via :func:`apps.assets.services.identifiers.create_asset_with_unique_code`.
    """

    # Site sub-section.
    site_mode = forms.ChoiceField(
        choices=SITE_MODE_CHOICES,
        initial=SITE_MODE_EXISTING,
    )
    existing_site = forms.ModelChoiceField(
        queryset=Site.objects.all().order_by("code"),
        required=False,
        empty_label="— izvēlieties objektu —",
    )
    new_site_code = forms.CharField(max_length=64, required=False)
    new_site_name = forms.CharField(max_length=256, required=False)
    new_site_description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    new_site_address = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    new_site_latitude = forms.FloatField(required=False)
    new_site_longitude = forms.FloatField(required=False)
    new_site_timezone = forms.ChoiceField(
        choices=TIMEZONE_CHOICES,
        initial=DEFAULT_TIMEZONE,
        required=False,
    )
    new_site_is_demo = forms.BooleanField(required=False)

    # Asset sub-section. NB: ``code`` is intentionally absent — it is
    # generated by the view.
    name = forms.CharField(max_length=256)
    asset_type = forms.ChoiceField(
        choices=AssetType.choices, initial=AssetType.OTHER,
    )
    status = forms.ChoiceField(
        choices=OperationalStatus.choices,
        initial=OperationalStatus.UNKNOWN,
        required=False,
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    latitude = forms.FloatField(required=False)
    longitude = forms.FloatField(required=False)
    external_id = forms.CharField(max_length=128, required=False)

    def clean_new_site_timezone(self):
        # ``ChoiceField`` already rejects values outside the curated set,
        # but make the contract explicit so accidental widget changes
        # cannot silently allow free-text timezones again.
        value = self.cleaned_data.get("new_site_timezone") or ""
        if value and value not in ALLOWED_TIMEZONES:
            raise forms.ValidationError(
                "Nederīga laika josla. Atļautas: "
                + ", ".join(ALLOWED_TIMEZONES) + "."
            )
        return value

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("site_mode")
        if mode == SITE_MODE_EXISTING:
            if not cleaned.get("existing_site"):
                self.add_error(
                    "existing_site", "Lūdzu, izvēlieties objektu (Site).",
                )
        elif mode == SITE_MODE_NEW:
            code = (cleaned.get("new_site_code") or "").strip()
            name = (cleaned.get("new_site_name") or "").strip()
            if not code:
                self.add_error(
                    "new_site_code", "Lauks ir obligāts jaunam objektam.",
                )
            if not name:
                self.add_error(
                    "new_site_name", "Lauks ir obligāts jaunam objektam.",
                )
            if code and Site.objects.filter(code=code).exists():
                self.add_error(
                    "new_site_code",
                    f"Objekts ar kodu '{code}' jau eksistē.",
                )
            # If no timezone was selected, fall back to the default
            # rather than letting the model save with an empty string.
            if not cleaned.get("new_site_timezone"):
                cleaned["new_site_timezone"] = DEFAULT_TIMEZONE
        return cleaned


# ── Stage 2a: new Device ────────────────────────────────────────────────────

class DeviceCreateStageForm(forms.Form):
    """
    Stage 2a — create a new ``Device`` and attach it to the asset. The
    ``device_uid`` field is generated, not typed.
    """

    name = forms.CharField(max_length=256)
    device_type = forms.CharField(max_length=64, required=False)
    is_simulated = forms.BooleanField(required=False)
    expected_interval_seconds = forms.IntegerField(
        required=False, min_value=1, initial=60,
    )
    firmware_version = forms.CharField(max_length=64, required=False)
    status = forms.ChoiceField(
        choices=OperationalStatus.choices,
        initial=OperationalStatus.UNKNOWN,
        required=False,
    )


# ── Stage 2b: attach existing Device ────────────────────────────────────────

class DeviceAttachStageForm(forms.Form):
    """
    Stage 2b — attach an existing unassigned ``Device`` from the same Site.

    The queryset is restricted at form-construction time to devices that
    (a) belong to the asset's site and (b) are not already claimed by
    another asset. We still re-check in :meth:`clean` because the
    queryset is a HTML hint, not a security boundary.
    """

    existing_device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        empty_label="— izvēlieties ierīci —",
    )

    def __init__(self, *args, asset, **kwargs):
        super().__init__(*args, **kwargs)
        self.asset = asset
        # Only show unassigned devices on the asset's site.
        self.fields["existing_device"].queryset = (
            Device.objects
            .filter(site=asset.site, asset__isnull=True)
            .order_by("device_uid")
        )

    def clean_existing_device(self):
        device = self.cleaned_data.get("existing_device")
        if device is None:
            return device
        if device.site_id != self.asset.site_id:
            raise forms.ValidationError(
                f"Ierīce '{device.device_uid}' pieder citam objektam "
                f"({device.site.code}), nevis '{self.asset.site.code}'."
            )
        if device.asset_id is not None:
            raise forms.ValidationError(
                f"Ierīce '{device.device_uid}' jau ir piesaistīta citam "
                f"aktīvam — atsaistiet to administrācijā."
            )
        return device


# ── Stage 3: add Sensor ──────────────────────────────────────────────────────

class SensorCreateStageForm(forms.Form):
    """
    Stage 3 — add a single ``Sensor`` to a ``Device``.

    Selecting a :class:`SensorMetricPreset` prefills the sensor metadata
    *and* signals to the view that Stage 4 should auto-link a metric.
    """

    preset = forms.ModelChoiceField(
        queryset=SensorMetricPreset.objects
            .filter(is_active=True)
            .select_related("metric")
            .order_by("sort_order", "code"),
        required=False,
        empty_label="— bez preseta —",
    )
    name = forms.CharField(max_length=256, required=False)
    sensor_type = forms.CharField(max_length=64, required=False)
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("preset")
        name = (cleaned.get("name") or "").strip()
        # If no preset is chosen, require a sensor name so the operator
        # has at least one human-readable label.
        if preset is None and not name:
            self.add_error(
                "name",
                "Norādiet sensora nosaukumu vai izvēlieties presetu.",
            )
        return cleaned


# ── Stage 4: Metric + SensorMetric (+ optional ThresholdRule) ───────────────

class SensorMetricStageForm(forms.Form):
    """
    Stage 4 — bind one ``MetricDefinition`` to a ``Sensor`` via a new
    ``SensorMetric`` row, optionally seeding a ``ThresholdRule``.
    """

    metric_mode = forms.ChoiceField(
        choices=METRIC_MODE_CHOICES,
        initial=METRIC_MODE_EXISTING,
    )
    sensor_metric_preset = forms.ModelChoiceField(
        queryset=SensorMetricPreset.objects
            .filter(is_active=True)
            .select_related("metric")
            .order_by("sort_order", "code"),
        required=False,
        empty_label="— izvēlieties presetu —",
    )
    existing_metric = forms.ModelChoiceField(
        queryset=MetricDefinition.objects.all().order_by("sort_order", "key"),
        required=False,
        empty_label="— izvēlieties metriku —",
    )

    # New MetricDefinition fields (only used when ``metric_mode=new``).
    new_metric_key = forms.CharField(max_length=64, required=False)
    new_metric_display_name = forms.CharField(max_length=128, required=False)
    new_metric_unit = forms.CharField(max_length=32, required=False)
    new_metric_data_type = forms.ChoiceField(
        choices=DataType.choices, initial=DataType.FLOAT, required=False,
    )
    new_metric_normal_min = forms.FloatField(required=False)
    new_metric_normal_max = forms.FloatField(required=False)
    new_metric_warning_min = forms.FloatField(required=False)
    new_metric_warning_max = forms.FloatField(required=False)
    new_metric_sort_order = forms.IntegerField(required=False, initial=0)

    # SensorMetric metadata.
    sensor_metric_is_required = forms.BooleanField(required=False, initial=False)
    sensor_metric_sort_order = forms.IntegerField(required=False, initial=0)

    # ThresholdRule sub-section.
    threshold_mode = forms.ChoiceField(
        choices=THRESHOLD_MODE_CHOICES,
        initial=THRESHOLD_MODE_NONE,
    )
    threshold_preset = forms.ModelChoiceField(
        queryset=ThresholdRulePreset.objects
            .filter(is_active=True)
            .select_related("metric")
            .order_by("code"),
        required=False,
        empty_label="— izvēlieties presetu —",
    )
    threshold_name = forms.CharField(max_length=256, required=False)
    threshold_description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    threshold_lower_bound = forms.FloatField(required=False)
    threshold_upper_bound = forms.FloatField(required=False)
    threshold_severity = forms.ChoiceField(
        choices=[
            (Severity.WARNING, "Warning"),
            (Severity.ERROR, "Error"),
            (Severity.CRITICAL, "Critical"),
        ],
        initial=Severity.WARNING,
        required=False,
    )
    threshold_close_when_normal = forms.BooleanField(required=False, initial=True)
    # Phase 7 bugfix: scope is now an explicit, operator-visible choice.
    # The previous code silently bound rules to ``sensor`` scope; that is
    # still the default (and the safe choice when creating from a sensor
    # page), but operators can now broaden the scope without dropping into
    # Django admin.
    threshold_scope_level = forms.ChoiceField(
        choices=THRESHOLD_SCOPE_CHOICES,
        initial=ThresholdRuleScope.SENSOR,
        required=False,
    )

    def __init__(self, *args, sensor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sensor = sensor

    # ─── Helpers ─────────────────────────────────────────────────────────

    def resolved_metric(self):
        """
        Return the ``MetricDefinition`` instance this form represents,
        creating it if the operator chose ``metric_mode=new``. Only safe
        to call after ``is_valid()`` and inside ``transaction.atomic``.

        Returns ``(metric, created_bool)``.
        """
        mode = self.cleaned_data["metric_mode"]
        if mode == METRIC_MODE_PRESET:
            return self.cleaned_data["sensor_metric_preset"].metric, False
        if mode == METRIC_MODE_EXISTING:
            return self.cleaned_data["existing_metric"], False
        return (
            MetricDefinition.objects.create(
                key=self.cleaned_data["new_metric_key"].strip(),
                display_name=self.cleaned_data["new_metric_display_name"].strip(),
                unit=(self.cleaned_data.get("new_metric_unit") or "").strip(),
                data_type=(self.cleaned_data.get("new_metric_data_type") or "float"),
                normal_min=self.cleaned_data.get("new_metric_normal_min"),
                normal_max=self.cleaned_data.get("new_metric_normal_max"),
                warning_min=self.cleaned_data.get("new_metric_warning_min"),
                warning_max=self.cleaned_data.get("new_metric_warning_max"),
                sort_order=self.cleaned_data.get("new_metric_sort_order") or 0,
            ),
            True,
        )

    # ─── Validation ──────────────────────────────────────────────────────

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("metric_mode")

        if mode == METRIC_MODE_PRESET:
            if not cleaned.get("sensor_metric_preset"):
                self.add_error(
                    "sensor_metric_preset",
                    "Lūdzu, izvēlieties SensorMetricPreset.",
                )
        elif mode == METRIC_MODE_EXISTING:
            if not cleaned.get("existing_metric"):
                self.add_error(
                    "existing_metric", "Lūdzu, izvēlieties metriku.",
                )
        elif mode == METRIC_MODE_NEW:
            key = (cleaned.get("new_metric_key") or "").strip()
            display = (cleaned.get("new_metric_display_name") or "").strip()
            if not key:
                self.add_error(
                    "new_metric_key", "Lauks ir obligāts jaunai metrikai.",
                )
            if not display:
                self.add_error(
                    "new_metric_display_name",
                    "Lauks ir obligāts jaunai metrikai.",
                )
            if key and MetricDefinition.objects.filter(key=key).exists():
                self.add_error(
                    "new_metric_key",
                    f"Metrika ar atslēgu '{key}' jau eksistē.",
                )

        # Threshold sub-section.
        t_mode = cleaned.get("threshold_mode") or THRESHOLD_MODE_NONE
        if t_mode == THRESHOLD_MODE_PRESET:
            if not cleaned.get("threshold_preset"):
                self.add_error(
                    "threshold_preset",
                    "Lūdzu, izvēlieties ThresholdRulePreset.",
                )
        elif t_mode == THRESHOLD_MODE_MANUAL:
            if not (cleaned.get("threshold_name") or "").strip():
                self.add_error(
                    "threshold_name",
                    "Lauks ir obligāts manuālam sliekšņa noteikumam.",
                )
            lower = cleaned.get("threshold_lower_bound")
            upper = cleaned.get("threshold_upper_bound")
            if lower is None and upper is None:
                self.add_error(
                    "threshold_lower_bound",
                    "Norādiet vismaz vienu robežu (lower_bound vai upper_bound).",
                )
                self.add_error(
                    "threshold_upper_bound",
                    "Norādiet vismaz vienu robežu (lower_bound vai upper_bound).",
                )
            if lower is not None and upper is not None and lower > upper:
                self.add_error(
                    "threshold_lower_bound",
                    "lower_bound nedrīkst būt lielāks par upper_bound.",
                )

        # SensorMetric uniqueness (sensor + metric).
        if self.sensor is not None and not self.has_error_in_metric():
            metric_pk = self._tentative_metric_pk(cleaned)
            if metric_pk is not None:
                from apps.assets.models import SensorMetric
                if SensorMetric.objects.filter(
                    sensor=self.sensor, metric_id=metric_pk,
                ).exists():
                    self.add_error(
                        "metric_mode",
                        "Šī metrika jau ir piesaistīta šim sensoram caur "
                        "SensorMetric.",
                    )
        return cleaned

    # ─── Internal helpers used by validation ─────────────────────────────

    def has_error_in_metric(self) -> bool:
        keys = {
            "metric_mode", "sensor_metric_preset", "existing_metric",
            "new_metric_key", "new_metric_display_name",
        }
        return any(k in self.errors for k in keys)

    def _tentative_metric_pk(self, cleaned):
        """Look up the MetricDefinition id this form *would* link to."""
        mode = cleaned.get("metric_mode")
        if mode == METRIC_MODE_PRESET:
            preset = cleaned.get("sensor_metric_preset")
            return getattr(preset, "metric_id", None)
        if mode == METRIC_MODE_EXISTING:
            metric = cleaned.get("existing_metric")
            return getattr(metric, "id", None)
        # ``new`` mode: the metric does not exist yet, so there cannot
        # be a uniqueness collision on the SensorMetric pair.
        return None


# ── Threshold rule edit (post-creation maintenance) ─────────────────────────

class ThresholdRuleEditForm(forms.Form):
    """
    Edit form for a single :class:`apps.analytics.models.ThresholdRule`
    rendered inside the asset configuration UI.

    The form is **anchored** to a specific asset: it can only edit rules
    that are reachable from that asset (sensor whose ``sensor.device.asset
    == asset``, device whose ``device.asset == asset``, the asset itself,
    or the asset's site). Promoting a rule to a different asset or to
    global scope is intentionally not exposed — that would silently
    affect other operators' rules and belongs in Django admin.

    Operators can change: name, description, scope_level, the scope
    target (sensor/device/asset/site), bounds, severity, message
    template, ``close_when_normal``, ``is_enabled`` and ``sort_order``.
    """

    name = forms.CharField(max_length=256)
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    scope_level = forms.ChoiceField(
        choices=THRESHOLD_EDIT_SCOPE_CHOICES,
        initial=ThresholdRuleScope.SENSOR,
    )
    # Populated in ``__init__`` from the asset context. ``required=False``
    # because only one of these is relevant per ``scope_level`` choice;
    # ``clean()`` enforces the right one is set.
    sensor = forms.ModelChoiceField(
        queryset=Sensor.objects.none(),
        required=False,
        empty_label="— izvēlieties sensoru —",
    )
    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        empty_label="— izvēlieties ierīci —",
    )
    lower_bound = forms.FloatField(required=False)
    upper_bound = forms.FloatField(required=False)
    severity = forms.ChoiceField(
        choices=[
            (Severity.WARNING, "Warning"),
            (Severity.ERROR, "Error"),
            (Severity.CRITICAL, "Critical"),
        ],
        initial=Severity.WARNING,
    )
    close_when_normal = forms.BooleanField(required=False, initial=True)
    is_enabled = forms.BooleanField(required=False, initial=True)
    sort_order = forms.IntegerField(required=False, initial=0)
    message_template = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, asset, instance=None, **kwargs):
        """
        ``asset`` is the dashboard URL anchor and is required because the
        sensor/device choice querysets must be restricted to it.
        """
        super().__init__(*args, **kwargs)
        self.asset = asset
        self.instance = instance
        self.fields["sensor"].queryset = (
            Sensor.objects
            .filter(device__asset=asset)
            .select_related("device")
            .order_by("device__device_uid", "code")
        )
        self.fields["device"].queryset = (
            Device.objects.filter(asset=asset).order_by("device_uid")
        )

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope_level")
        sensor = cleaned.get("sensor")
        device = cleaned.get("device")

        if scope == ThresholdRuleScope.SENSOR:
            if not sensor:
                self.add_error(
                    "sensor",
                    "Sensor-scope noteikumam jāizvēlas sensors.",
                )
        elif scope == ThresholdRuleScope.DEVICE:
            if not device:
                self.add_error(
                    "device",
                    "Device-scope noteikumam jāizvēlas ierīce.",
                )
        # asset/site scopes don't need an extra picker — the URL anchor
        # determines which asset/site the rule is for.

        # Cross-asset reachability is enforced via the querysets above
        # (Sensor / Device limited to ``asset.devices``), so an attacker
        # POSTing a foreign sensor/device id gets a "not in queryset"
        # ValidationError automatically.

        # Bounds: at least one and not inverted. Model-level clean()
        # repeats this, but checking here yields a nicer per-field error.
        lower = cleaned.get("lower_bound")
        upper = cleaned.get("upper_bound")
        if lower is None and upper is None:
            self.add_error(
                "lower_bound",
                "Norādiet vismaz vienu robežu (lower_bound vai upper_bound).",
            )
            self.add_error(
                "upper_bound",
                "Norādiet vismaz vienu robežu (lower_bound vai upper_bound).",
            )
        if lower is not None and upper is not None and lower > upper:
            self.add_error(
                "lower_bound",
                "lower_bound nedrīkst būt lielāks par upper_bound.",
            )
        return cleaned

    def apply_to(self, rule):
        """
        Mutate ``rule`` from the cleaned form data and return it
        unsaved. The caller is responsible for ``rule.save()`` inside a
        transaction so model-level ``clean()`` runs once.
        """
        cd = self.cleaned_data
        scope = cd["scope_level"]
        rule.name = cd["name"].strip()
        rule.description = (cd.get("description") or "").strip()
        rule.scope_level = scope
        # Reset every FK first, then fill the one the scope demands.
        # Model ``_autofill_scope_fields`` will populate higher-level FKs
        # automatically — we keep the explicit reset to make the intent
        # obvious and to avoid a stale FK from a previous scope choice.
        rule.sensor = None
        rule.device = None
        rule.asset = None
        rule.site = None
        if scope == ThresholdRuleScope.SENSOR:
            rule.sensor = cd["sensor"]
        elif scope == ThresholdRuleScope.DEVICE:
            rule.device = cd["device"]
        elif scope == ThresholdRuleScope.ASSET:
            rule.asset = self.asset
        elif scope == ThresholdRuleScope.SITE:
            rule.site = self.asset.site
        rule.lower_bound = cd.get("lower_bound")
        rule.upper_bound = cd.get("upper_bound")
        rule.severity = cd.get("severity") or Severity.WARNING
        rule.close_when_normal = bool(cd.get("close_when_normal"))
        rule.is_enabled = bool(cd.get("is_enabled"))
        rule.sort_order = cd.get("sort_order") or 0
        rule.message_template = (cd.get("message_template") or "").strip()
        return rule

    @classmethod
    def initial_from(cls, rule):
        """
        Build the ``initial`` dict for editing ``rule``. Keeps the
        edit page idempotent on GET.
        """
        return {
            "name": rule.name,
            "description": rule.description,
            "scope_level": rule.scope_level,
            "sensor": rule.sensor_id,
            "device": rule.device_id,
            "lower_bound": rule.lower_bound,
            "upper_bound": rule.upper_bound,
            "severity": rule.severity,
            "close_when_normal": rule.close_when_normal,
            "is_enabled": rule.is_enabled,
            "sort_order": rule.sort_order,
            "message_template": rule.message_template,
        }
