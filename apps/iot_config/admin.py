from django.contrib import admin

from .models import (
    DeviceProfile,
    DeviceProfileMetric,
    MetricDefinition,
    MqttTopicTemplate,
    SensorMetricPreset,
)


class DeviceProfileMetricInline(admin.TabularInline):
    model = DeviceProfileMetric
    extra = 0
    fields = ("metric", "is_required", "sort_order")
    ordering = ("sort_order", "metric__key")


@admin.register(MetricDefinition)
class MetricDefinitionAdmin(admin.ModelAdmin):
    list_display = ("key", "display_name", "unit", "data_type", "is_required", "sort_order", "is_active")
    search_fields = ("key", "display_name", "unit")
    list_filter = ("data_type", "is_required", "is_active")
    ordering = ("sort_order", "key")


@admin.register(MqttTopicTemplate)
class MqttTopicTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "topic_type", "template", "is_active")
    search_fields = ("name", "template")
    list_filter = ("topic_type", "is_active")
    ordering = ("topic_type", "name")


@admin.register(DeviceProfile)
class DeviceProfileAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "device_type", "default_expected_interval_seconds", "is_active")
    search_fields = ("code", "name", "device_type")
    list_filter = ("is_active",)
    ordering = ("code",)
    inlines = [DeviceProfileMetricInline]


@admin.register(SensorMetricPreset)
class SensorMetricPresetAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "metric", "sensor_type",
        "is_required", "sort_order", "is_active",
    )
    search_fields = ("code", "name", "metric__key", "sensor_type")
    list_filter = ("is_required", "is_active")
    ordering = ("sort_order", "code")
    list_select_related = ("metric",)
