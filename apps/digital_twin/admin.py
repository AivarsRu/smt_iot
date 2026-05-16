from django.contrib import admin

from .models import AssetState


@admin.register(AssetState)
class AssetStateAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "site",
        "status",
        "last_seen_at",
        "last_measurement_at",
        "has_active_anomaly",
        "active_anomaly_count",
    )
    search_fields = ("asset__code", "asset__name", "device__device_uid")
    list_filter = ("status", "has_active_anomaly", "site")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("asset", "site", "device")
    ordering = ("asset__code",)
