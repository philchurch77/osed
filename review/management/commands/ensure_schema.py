"""
Emergency schema-repair command.

Adds any columns that should exist according to the current models but are
missing from the live database.  Safe to run multiple times (all operations
are guarded with IF NOT EXISTS / column-presence checks).

Usage:
    python manage.py ensure_schema
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


# Each entry: (table, column, column_definition_for_alter_table)
_REQUIRED_COLUMNS = [
    (
        "review_indeptharea",
        "purpose",
        "text NOT NULL DEFAULT ''",
    ),
    # Migration 0036. Here because startup.sh swallows a failed `migrate` and
    # boots gunicorn anyway, and this column is not feature-local: Django's
    # default SELECT lists every column, so a model that has it against a
    # database that does not turns EVERY query on School into a
    # ProgrammingError -- login, home, the admin and every scoped page, not
    # just the Context Dashboard. Same shape as the 0035 warning in CLAUDE.md,
    # but School is read on effectively every authenticated request.
    #
    # This restores the column only. The partial unique index is left to the
    # next successful migrate: keeping the site up is the urgent half, and an
    # absent index refuses nothing.
    (
        "review_school",
        "powerbi_school_name",
        "varchar(200) NOT NULL DEFAULT ''",
    ),
]


class Command(BaseCommand):
    help = "Ensure all required DB columns exist; adds any that are missing."

    def handle(self, *args, **options):
        vendor = connection.vendor

        with connection.cursor() as cursor:
            for table, column, definition in _REQUIRED_COLUMNS:
                if vendor == "postgresql":
                    cursor.execute(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = %s AND column_name = %s",
                        [table, column],
                    )
                    exists = cursor.fetchone() is not None
                else:
                    # SQLite
                    cursor.execute(f"PRAGMA table_info({table})")
                    exists = any(row[1] == column for row in cursor.fetchall())

                if exists:
                    self.stdout.write(f"  {table}.{column}: already present")
                else:
                    # Check the table itself exists before trying ALTER TABLE.
                    # On a fresh database migrate hasn't run yet, so silently
                    # skip — migrate will create everything from scratch.
                    if vendor == "postgresql":
                        cursor.execute(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_name = %s",
                            [table],
                        )
                        table_exists = cursor.fetchone() is not None
                    else:
                        cursor.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name=%s",
                            [table],
                        )
                        table_exists = cursor.fetchone() is not None

                    if not table_exists:
                        self.stdout.write(
                            f"  {table}.{column}: table absent, skipping "
                            f"(migrate will create it)"
                        )
                        continue

                    cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"  {table}.{column}: ADDED")
                    )
