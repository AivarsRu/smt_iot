from django.contrib import admin

from .models import Asset, Device, Sensor, Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "timezone", "is_demo", "is_active")
    search_fields = ("code", "name", "address")
    list_filter = ("is_demo", "is_active", "timezone")
    ordering = ("code",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "site", "asset_type", "status", "is_active")
    search_fields = ("code", "name", "external_id")
    list_filter = ("asset_type", "status", "is_active", "site")
    ordering = ("site", "code")
    raw_id_fields = ("site", "parent")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "device_uid",
        "name",
        "site",
        "asset",
        "device_type",
        "is_simulated",
        "status",
        "last_seen_at",
        "is_active",
    )
    search_fields = ("device_uid", "name", "firmware_version")
    list_filter = ("is_simulated", "status", "is_active", "site")
    ordering = ("device_uid",)
    raw_id_fields = ("site", "asset")


@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "device", "sensor_type", "is_active")
    search_fields = ("code", "name", "device__device_uid")
    list_filter = ("sensor_type", "is_active")
    ordering = ("device", "code")
    raw_id_fields = ("device",)
