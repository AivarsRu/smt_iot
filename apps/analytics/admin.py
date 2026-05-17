from django.contrib import admin

from apps.analytics.models import ThresholdRule, ThresholdRulePreset


@admin.register(ThresholdRule)
class ThresholdRuleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "metric",
        "scope_level",
        "sensor",
        "severity",
        "lower_bound",
        "upper_bound",
        "is_enabled",
        "site",
        "asset",
        "device",
        "sort_order",
    )
    search_fields = (
        "code",
        "name",
        "description",
        "metric__key",
        "sensor__code",
    )
    list_filter = (
        "scope_level",
        "is_enabled",
        "severity",
        "metric",
        "site",
    )
    ordering = ("sort_order", "code")
    list_select_related = ("metric", "site", "asset", "device", "sensor")
    autocomplete_fields = ()
    fieldsets = (
        (None, {
            "fields": ("code", "name", "description", "is_enabled", "sort_order"),
        }),
        ("Scope", {
            "fields": ("scope_level", "metric", "site", "asset", "device", "sensor"),
            "description": (
                "scope_level controls how the rule is matched at evaluation "
                "time. Populate the FK that matches the chosen scope; "
                "finer-grained FKs must be empty."
            ),
        }),
        ("Bounds", {
            "fields": ("lower_bound", "upper_bound"),
        }),
        ("Event behaviour", {
            "fields": ("severity", "message_template", "close_when_normal"),
        }),
        ("Metadata", {
            "fields": ("metadata",),
            "classes": ("collapse",),
        }),
    )


@admin.register(ThresholdRulePreset)
class ThresholdRulePresetAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "metric", "lower_bound", "upper_bound",
        "severity", "close_when_normal", "is_active",
    )
    search_fields = ("code", "name", "description", "metric__key")
    list_filter = ("severity", "is_active")
    ordering = ("code",)
    list_select_related = ("metric",)
