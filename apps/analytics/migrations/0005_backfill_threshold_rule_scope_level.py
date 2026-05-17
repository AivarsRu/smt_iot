"""
Backfill ``ThresholdRule.scope_level`` from the previously-implicit NULL FK
semantics so existing rows expose their *actual* scope explicitly.

Inference rules (most specific wins):

    sensor_id  set → scope_level = 'sensor'
    device_id  set → scope_level = 'device'
    asset_id   set → scope_level = 'asset'
    site_id    set → scope_level = 'site'
    all NULL       → scope_level = 'global'

We deliberately do **not** delete or mutate any user data here: the FKs stay
exactly as they were and only the new ``scope_level`` column is populated.
Operators can later promote a rule from accidental ``global`` to an explicit
narrower scope through admin or the operator workflow.

The backward migration resets ``scope_level`` to the model default (``sensor``)
so the schema-level rollback in 0004 stays consistent; it does not pretend to
restore the previous NULL-wildcard semantics.
"""

from __future__ import annotations

from django.db import migrations


def backfill_scope_level(apps, schema_editor):
    ThresholdRule = apps.get_model("analytics", "ThresholdRule")
    for rule in ThresholdRule.objects.all().only(
        "id", "sensor_id", "device_id", "asset_id", "site_id", "scope_level",
    ):
        if rule.sensor_id:
            inferred = "sensor"
        elif rule.device_id:
            inferred = "device"
        elif rule.asset_id:
            inferred = "asset"
        elif rule.site_id:
            inferred = "site"
        else:
            inferred = "global"
        if rule.scope_level != inferred:
            rule.scope_level = inferred
            rule.save(update_fields=["scope_level"])


def reverse_noop(apps, schema_editor):
    # The schema migration drops the column, so there is nothing reversible
    # at the data-migration level. Keep the function so ``migrate --plan``
    # treats this migration as reversible.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0004_thresholdrule_scope_level_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_scope_level, reverse_noop),
    ]
