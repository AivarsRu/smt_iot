"""
Phase 7, Task 3B — declares the ``simulator.can_control_simulator``
permission on ``SimulatorScenario`` via ``Meta.permissions``.

This migration only adjusts model options (and, as a side effect, lets
Django's ``post_migrate`` signal create the matching ``auth.Permission``
row). It does **not** change any database tables, columns, or
constraints.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('simulator', '0002_simulatormetricprofile_sensor'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='simulatorscenario',
            options={
                'ordering': ['code'],
                'permissions': [
                    ('can_control_simulator', 'Var vadīt simulatoru'),
                ],
                'verbose_name': 'Simulator Scenario',
                'verbose_name_plural': 'Simulator Scenarios',
            },
        ),
    ]
