from django.contrib import admin

from .models import Measurement, RawMessage


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    list_display = (
        "source_type",
        "device_uid",
        "device",
        "processing_status",
        "received_at",
        "payload_timestamp",
    )
    search_fields = ("message_id", "device_uid", "topic", "error_message")
    list_filter = ("source_type", "processing_status", "received_at")
    readonly_fields = ("created_at", "updated_at", "received_at")
    list_select_related = ("device", "site", "asset")
    ordering = ("-received_at",)


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = (
        "site",
        "asset",
        "device",
        "metric",
        "display_value",
        "quality",
        "timestamp",
        "is_anomalous",
    )
    search_fields = (
        "asset__code",
        "asset__name",
        "device__device_uid",
        "metric__key",
    )
    list_filter = ("quality", "is_anomalous", "metric", "timestamp")
    date_hierarchy = "timestamp"
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("site", "asset", "device", "metric")
    ordering = ("-timestamp",)

    @admin.display(description="Value")
    def display_value(self, obj):
        v = obj.value
        unit = f" {obj.unit}" if obj.unit else ""
        return f"{v}{unit}" if v is not None else "—"
