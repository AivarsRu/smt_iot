"""
Make ``SimulatorMetricProfile`` sensor-aware.

Steps:
  1. Drop the old ``unique_simulator_metric_profile`` (scenario_device,
     metric) constraint.
  2. Add a nullable ``sensor`` FK to ``assets.Sensor``.
  3. Data-migrate existing rows: for each row whose
     ``scenario_device.device`` has at least one active Sensor, link the
     first such Sensor (deterministic by ``created_at, id``). Rows on
     devices without any active sensor stay null and are flagged at
     runtime by the simulator with a clear configuration error.
  4. Add the new ``unique_simulator_metric_profile_sensor``
     (scenario_device, sensor, metric) unique constraint.

The ``sensor`` column stays nullable at the DB level so partial historic
data is not destroyed; application logic enforces the non-null requirement
in ``simulator.services.payload_generator``.
"""

import django.db.models.deletion
from django.db import migrations, models


def _assign_first_active_sensor(apps, schema_editor):
    SimulatorMetricProfile = apps.get_model("simulator", "SimulatorMetricProfile")
    Sensor = apps.get_model("assets", "Sensor")
    for profile in SimulatorMetricProfile.objects.select_related(
        "scenario_device__device"
    ).all():
        device = profile.scenario_device.device
        sensor = (
            Sensor.objects.filter(device=device, is_active=True)
            .order_by("created_at", "id")
            .first()
        )
        if sensor is not None:
            profile.sensor = sensor
            profile.save(update_fields=["sensor"])


def _reverse_assign(apps, schema_editor):
    SimulatorMetricProfile = apps.get_model("simulator", "SimulatorMetricProfile")
    SimulatorMetricProfile.objects.update(sensor=None)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0002_sensormetric_sensor_metrics_and_more"),
        ("iot_config", "0001_initial"),
        ("simulator", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="simulatormetricprofile",
            name="unique_simulator_metric_profile",
        ),
        migrations.AddField(
            model_name="simulatormetricprofile",
            name="sensor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="simulator_metric_profiles",
                to="assets.sensor",
            ),
        ),
        migrations.RunPython(_assign_first_active_sensor, _reverse_assign),
        migrations.AddConstraint(
            model_name="simulatormetricprofile",
            constraint=models.UniqueConstraint(
                fields=("scenario_device", "sensor", "metric"),
                name="unique_simulator_metric_profile_sensor",
            ),
        ),
    ]
