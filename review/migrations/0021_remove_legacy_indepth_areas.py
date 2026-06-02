"""Remove InDepthArea records that are not part of the current blueprint."""
from __future__ import annotations

from django.db import migrations

_BLUEPRINT_AREA_NAMES = {
    "Safeguarding",
    "Quality of Education",
    "Behaviour & Attitudes",
    "Personal Development",
    "Leadership & Management",
    "Early Years",
    "Sixth Form",
    "SEND",
}


def remove_legacy_areas(apps, schema_editor):
    InDepthArea = apps.get_model("review", "InDepthArea")
    InDepthArea.objects.exclude(name__in=_BLUEPRINT_AREA_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0020_replace_statements_with_subsections"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_areas, migrations.RunPython.noop),
    ]
