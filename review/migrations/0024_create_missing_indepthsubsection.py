from __future__ import annotations

from django.db import migrations


def create_indepthsubsection_if_missing(apps, schema_editor):
    """
    Migration 0020 was applied to the Render PostgreSQL database before the
    CreateModel InDepthSubSection block (and corresponding InDepthResponse
    columns) were added to it.  This migration recreates everything that
    should have been created by those missing operations, guarded so it is
    safe to run on databases that are already correct.

    SQLite (local dev) is skipped — it always ran migrations in order and
    already has the correct schema.
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        CREATE TABLE IF NOT EXISTS review_indepthsubsection (
            id                              bigserial PRIMARY KEY,
            area_id                         bigint    NOT NULL
                                            REFERENCES review_indeptharea(id)
                                            ON DELETE CASCADE
                                            DEFERRABLE INITIALLY DEFERRED,
            name                            varchar(200) NOT NULL,
            overview                        text NOT NULL DEFAULT '',
            evidence_criteria               text NOT NULL DEFAULT '',
            "order"                         integer  NOT NULL DEFAULT 0,
            urgent_improvement_descriptor   text NOT NULL DEFAULT '',
            needs_attention_descriptor      text NOT NULL DEFAULT '',
            expected_descriptor             text NOT NULL DEFAULT '',
            strong_descriptor               text NOT NULL DEFAULT '',
            exceptional_descriptor          text NOT NULL DEFAULT '',
            not_met_descriptor              text NOT NULL DEFAULT '',
            met_descriptor                  text NOT NULL DEFAULT ''
        )
    """)

    schema_editor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'unique_indepth_subsection_per_area'
            ) THEN
                ALTER TABLE review_indepthsubsection
                    ADD CONSTRAINT unique_indepth_subsection_per_area
                    UNIQUE (area_id, name);
            END IF;
        END
        $$;
    """)

    # Columns added to InDepthResponse in the same missing 0020 block.
    schema_editor.execute("""
        ALTER TABLE review_indepthresponse
            ADD COLUMN IF NOT EXISTS subsection_id bigint
                REFERENCES review_indepthsubsection(id) ON DELETE CASCADE;
    """)
    schema_editor.execute("""
        ALTER TABLE review_indepthresponse
            ADD COLUMN IF NOT EXISTS evidence_text text NOT NULL DEFAULT '';
    """)
    schema_editor.execute("""
        ALTER TABLE review_indepthresponse
            ADD COLUMN IF NOT EXISTS grade varchar(25) NOT NULL DEFAULT '';
    """)

    schema_editor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'unique_indepth_response_per_review_subsection'
            ) THEN
                ALTER TABLE review_indepthresponse
                    ADD CONSTRAINT unique_indepth_response_per_review_subsection
                    UNIQUE (review_id, subsection_id);
            END IF;
        END
        $$;
    """)


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0023_add_missing_indeptharea_purpose"),
    ]

    operations = [
        migrations.RunPython(
            create_indepthsubsection_if_missing,
            migrations.RunPython.noop,
        ),
    ]
