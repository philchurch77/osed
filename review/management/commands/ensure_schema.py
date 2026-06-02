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
                    cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"  {table}.{column}: ADDED")
                    )
