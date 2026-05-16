from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "severity",
        "status",
        "title",
        "asset",
        "device",
        "detected_at",
    )
    search_fields = ("title", "description", "asset__code", "asset__name", "device__device_uid")
    list_filter = ("event_type", "severity", "status", "detected_at")
    date_hierarchy = "detected_at"
    readonly_fields = ("created_at", "updated_at", "detected_at")
    list_select_related = ("site", "asset", "device", "metric")
    ordering = ("-detected_at",)
