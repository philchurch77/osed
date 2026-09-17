"""Populate `School.powerbi_school_name` for the schools that already exist.

This lives in a migration rather than in `seed_schools` because it must happen
exactly **once**. Blank is a meaningful value on this field -- it means "show no
report for this school" -- so a set-if-blank rule in a command that runs on every
deploy could not tell "never configured" from "the Trust deliberately switched
this school off", and would silently switch it back on. `School` carries no
`simple_history`, so nothing would record that it had ever been cleared.

`seed_schools` still sets the value for a school it creates, so a fresh database
needs no runbook step.

Forward is set-if-blank and case-preserving: a value an admin has already entered
is never touched, and a school not in this list is left alone. Reverse is a noop
-- 0036's own reverse drops the column.
"""
from __future__ import annotations

from django.db import migrations


# (canonical OSED name, the value in the report's School slicer). These match
# none of the seven OSED names, which is the whole reason the field exists.
POWERBI_NAMES = [
    ("Rose Hill School", "Rose Hill Primary"),
    ("Copleston High School", "Copleston"),
    ("Britannia Primary and Nursery School", "Britannia Primary"),
    ("Stowupland High School", "Stowupland"),
    ("Bacton Primary School", "Bacton Primary"),
    ("Cedars Park Primary School", "Cedars Park Primary"),
    ("Mendlesham Primary School", "Mendlesham Primary"),
]


def set_powerbi_names(apps, schema_editor):
    School = apps.get_model("review", "School")
    for name, powerbi_name in POWERBI_NAMES:
        # Filtered on the blank value as well as the name, so this cannot
        # overwrite anything already set. `School.name` is not unique, so this
        # is an update() over a queryset rather than a get() that could raise.
        School.objects.filter(name=name, powerbi_school_name="").update(
            powerbi_school_name=powerbi_name
        )


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0036_school_powerbi_school_name_and_more"),
    ]

    operations = [
        migrations.RunPython(set_powerbi_names, migrations.RunPython.noop),
    ]
