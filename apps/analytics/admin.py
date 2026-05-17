from django.contrib import admin

from apps.analytics.models import ThresholdRule


@admin.register(ThresholdRule)
class ThresholdRuleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "metric",
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
    )
    list_filter = (
        "is_enabled",
        "severity",
        "metric",
        "site",
    )
    ordering = ("sort_order", "code")
    list_select_related = ("metric", "site", "asset", "device")
    autocomplete_fields = ()
    fieldsets = (
        (None, {
            "fields": ("code", "name", "description", "is_enabled", "sort_order"),
        }),
        ("Scope", {
            "fields": ("metric", "site", "asset", "device"),
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
