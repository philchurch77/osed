from __future__ import annotations

from django.db import migrations


def add_purpose_if_missing(apps, schema_editor):
    """
    Migration 0020 was applied on the production (Render) PostgreSQL database
    before the 'purpose' AddField operation was added to it. This function
    adds the column only when it is absent, so it is safe to run on both
    Render (missing column) and local SQLite (column already exists).
    """
    connection = schema_editor.connection
    vendor = connection.vendor

    if vendor == "postgresql":
        schema_editor.execute(
            "ALTER TABLE review_indeptharea "
            "ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT '';"
        )
    else:
        # SQLite: check via PRAGMA before adding
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(review_indeptharea)")
            columns = [row[1] for row in cursor.fetchall()]
        if "purpose" not in columns:
            schema_editor.execute(
                "ALTER TABLE review_indeptharea "
                "ADD COLUMN purpose text NOT NULL DEFAULT '';"
            )


def remove_purpose_if_added(apps, schema_editor):
    connection = schema_editor.connection
    vendor = connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(
            "ALTER TABLE review_indeptharea DROP COLUMN IF EXISTS purpose;"
        )
    # SQLite does not support DROP COLUMN in older versions; skip reverse.


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0022_alter_indepthresponse_options"),
    ]

    operations = [
        migrations.RunPython(add_purpose_if_missing, remove_purpose_if_added),
    ]
