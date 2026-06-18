from __future__ import annotations

from django.db import migrations


def remove_2025_data(apps, schema_editor):
    """Drop all 2025/2026 (academic year start 2025) records.

    The client retired academic year 25/26 — the system now starts at
    Round 1, 26/27. Deleting the ReviewPeriod rows cascades (via the
    Evaluation.period FK, on_delete=CASCADE) to their Evaluations;
    InDepthReview rows cascade to their InDepthResponses.
    """
    ReviewPeriod = apps.get_model("review", "ReviewPeriod")
    InDepthReview = apps.get_model("review", "InDepthReview")

    ReviewPeriod.objects.filter(year__lt=2026).delete()
    InDepthReview.objects.filter(year__lt=2026).delete()


def noop_reverse(apps, schema_editor):
    """Irreversible — the deleted 25/26 data cannot be reconstructed."""


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0026_alter_indepthresponse_options_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_2025_data, noop_reverse),
    ]
