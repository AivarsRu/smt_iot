from django.db import IntegrityError
from django.test import TestCase

from apps.core.models import DataType, MqttTopicType
from apps.iot_config.models import DeviceProfile, DeviceProfileMetric, MetricDefinition, MqttTopicTemplate


class MetricDefinitionTest(TestCase):
    def test_create_metric(self):
        metric = MetricDefinition.objects.create(
            key="voltage_v",
            display_name="Voltage",
            unit="V",
            data_type=DataType.FLOAT,
            normal_min=45.0,
            normal_max=58.0,
            is_required=True,
            sort_order=1,
        )
        self.assertEqual(str(metric), "voltage_v (V)")
        self.assertEqual(metric.data_type, DataType.FLOAT)

    def test_metric_key_unique(self):
        MetricDefinition.objects.create(key="dup_key", display_name="First")
        with self.assertRaises(IntegrityError):
            MetricDefinition.objects.create(key="dup_key", display_name="Second")

    def test_metric_without_unit_str(self):
        metric = MetricDefinition.objects.create(key="flag", display_name="Flag", unit="")
        self.assertEqual(str(metric), "flag")


class MqttTopicTemplateTest(TestCase):
    def test_create_template(self):
        tmpl = MqttTopicTemplate.objects.create(
            name="default_telemetry",
            topic_type=MqttTopicType.TELEMETRY,
            template="smt/{env}/{site_id}/{asset_type}/{device_id}/telemetry",
        )
        self.assertIn("telemetry", str(tmpl))
        self.assertEqual(tmpl.topic_type, MqttTopicType.TELEMETRY)

    def test_topic_template_type_name_unique(self):
        MqttTopicTemplate.objects.create(
            name="same_name",
            topic_type=MqttTopicType.STATUS,
            template="smt/x/status",
        )
        with self.assertRaises(IntegrityError):
            MqttTopicTemplate.objects.create(
                name="same_name",
                topic_type=MqttTopicType.STATUS,
                template="smt/y/status",
            )

    def test_same_name_different_type_allowed(self):
        MqttTopicTemplate.objects.create(
            name="default",
            topic_type=MqttTopicType.TELEMETRY,
            template="smt/{env}/telemetry",
        )
        tmpl2 = MqttTopicTemplate.objects.create(
            name="default",
            topic_type=MqttTopicType.STATUS,
            template="smt/{env}/status",
        )
        self.assertEqual(tmpl2.name, "default")


class DeviceProfileTest(TestCase):
    def setUp(self):
        self.m1 = MetricDefinition.objects.create(key="voltage_v", display_name="Voltage", unit="V")
        self.m2 = MetricDefinition.objects.create(key="current_a", display_name="Current", unit="A")

    def test_create_profile(self):
        profile = DeviceProfile.objects.create(
            code="charger_profile",
            name="Charger Profile",
            device_type="charger",
        )
        self.assertEqual(str(profile), "charger_profile — Charger Profile")

    def test_assign_metrics_via_through_model(self):
        profile = DeviceProfile.objects.create(code="p1", name="Profile 1")
        DeviceProfileMetric.objects.create(profile=profile, metric=self.m1, is_required=True, sort_order=1)
        DeviceProfileMetric.objects.create(profile=profile, metric=self.m2, is_required=False, sort_order=2)
        self.assertEqual(profile.metrics.count(), 2)

    def test_device_profile_metric_unique(self):
        profile = DeviceProfile.objects.create(code="p2", name="Profile 2")
        DeviceProfileMetric.objects.create(profile=profile, metric=self.m1, sort_order=1)
        with self.assertRaises(IntegrityError):
            DeviceProfileMetric.objects.create(profile=profile, metric=self.m1, sort_order=2)

    def test_profile_code_unique(self):
        DeviceProfile.objects.create(code="dup_profile", name="First")
        with self.assertRaises(IntegrityError):
            DeviceProfile.objects.create(code="dup_profile", name="Second")
