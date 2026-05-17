from django.contrib import admin

from apps.simulator.models import (
    SimulatorMetricProfile,
    SimulatorRun,
    SimulatorScenario,
    SimulatorScenarioDevice,
)


class SimulatorMetricProfileInline(admin.TabularInline):
    model = SimulatorMetricProfile
    extra = 1
    fields = [
        "sensor", "metric", "generation_mode", "base_value", "noise_amplitude",
        "min_value", "max_value", "is_enabled", "sort_order",
    ]
    raw_id_fields = ["sensor", "metric"]


class SimulatorScenarioDeviceInline(admin.TabularInline):
    model = SimulatorScenarioDevice
    extra = 1
    fields = ["device", "device_profile", "is_enabled", "sort_order", "status_override"]


@admin.register(SimulatorScenario)
class SimulatorScenarioAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "site", "is_active", "interval_seconds", "last_run_at"]
    search_fields = ["code", "name"]
    list_filter = ["is_active", "site"]
    inlines = [SimulatorScenarioDeviceInline]


@admin.register(SimulatorScenarioDevice)
class SimulatorScenarioDeviceAdmin(admin.ModelAdmin):
    list_display = ["scenario", "device", "device_profile", "is_enabled", "sort_order"]
    search_fields = ["scenario__code", "device__device_uid"]
    list_filter = ["is_enabled"]
    inlines = [SimulatorMetricProfileInline]


@admin.register(SimulatorMetricProfile)
class SimulatorMetricProfileAdmin(admin.ModelAdmin):
    list_display = [
        "scenario_device", "sensor", "metric", "generation_mode",
        "base_value", "noise_amplitude", "is_enabled",
    ]
    list_filter = ["generation_mode", "is_enabled"]
    raw_id_fields = ["sensor", "metric", "scenario_device"]
    search_fields = [
        "scenario_device__scenario__code",
        "scenario_device__device__device_uid",
        "sensor__code",
        "metric__key",
    ]


@admin.register(SimulatorRun)
class SimulatorRunAdmin(admin.ModelAdmin):
    list_display = ["scenario", "status", "started_at", "finished_at", "messages_published"]
    list_filter = ["status"]
    readonly_fields = ["started_at"]
