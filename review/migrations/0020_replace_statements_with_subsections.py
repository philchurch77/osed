from __future__ import annotations

import django.db.models.deletion
import review.models

from django.conf import settings
from django.db import migrations, models


def clear_indepth_data(apps, schema_editor):
    """Purge all old statement-based in-depth data before schema replacement."""
    InDepthResponse = apps.get_model("review", "InDepthResponse")
    InDepthReview = apps.get_model("review", "InDepthReview")
    InDepthStatement = apps.get_model("review", "InDepthStatement")
    InDepthResponse.objects.all().delete()
    InDepthReview.objects.all().delete()
    InDepthStatement.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0019_indepthreview_qa_reflection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. Clear all old data ────────────────────────────────────────────────
        migrations.RunPython(clear_indepth_data, migrations.RunPython.noop),

        # ── 2. Remove old unique constraint on InDepthResponse ───────────────────
        migrations.RemoveConstraint(
            model_name="indepthresponse",
            name="unique_indepth_response_per_review_statement",
        ),

        # ── 3. Remove old fields from InDepthResponse ────────────────────────────
        migrations.RemoveField(model_name="indepthresponse", name="statement"),
        migrations.RemoveField(model_name="indepthresponse", name="applies"),
        migrations.RemoveField(model_name="indepthresponse", name="rag"),
        migrations.RemoveField(model_name="indepthresponse", name="justification"),

        # ── 4. Remove old fields from InDepthReview ──────────────────────────────
        migrations.RemoveField(model_name="indepthreview", name="secondary_level"),
        migrations.RemoveField(model_name="indepthreview", name="secondary_applies"),
        migrations.RemoveField(model_name="indepthreview", name="justification"),

        # ── 5. Update InDepthReview.step choices & add overall_grade ─────────────
        migrations.AlterField(
            model_name="indepthreview",
            name="step",
            field=models.CharField(
                choices=[("review", "Review"), ("reflection", "Reflection")],
                default="review",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="indepthreview",
            name="overall_grade",
            field=models.CharField(blank=True, default="", max_length=25),
        ),

        # ── 6. Add purpose to InDepthArea, remove old context text fields ─────────
        migrations.AddField(
            model_name="indeptharea",
            name="purpose",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RemoveField(model_name="indeptharea", name="needs_attention_text"),
        migrations.RemoveField(model_name="indeptharea", name="strong_standard_text"),

        # ── 7. Create InDepthSubSection ───────────────────────────────────────────
        migrations.CreateModel(
            name="InDepthSubSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("area", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="subsections",
                    to="review.indeptharea",
                )),
                ("name", models.CharField(max_length=200)),
                ("overview", models.TextField(blank=True, default="")),
                ("evidence_criteria", models.TextField(blank=True, default="")),
                ("order", models.PositiveIntegerField(default=0)),
                ("urgent_improvement_descriptor", models.TextField(blank=True, default="")),
                ("needs_attention_descriptor", models.TextField(blank=True, default="")),
                ("expected_descriptor", models.TextField(blank=True, default="")),
                ("strong_descriptor", models.TextField(blank=True, default="")),
                ("exceptional_descriptor", models.TextField(blank=True, default="")),
                ("not_met_descriptor", models.TextField(blank=True, default="")),
                ("met_descriptor", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ("area__order", "area__name", "order"),
            },
        ),
        migrations.AddConstraint(
            model_name="indepthsubsection",
            constraint=models.UniqueConstraint(
                fields=["area", "name"],
                name="unique_indepth_subsection_per_area",
            ),
        ),

        # ── 8. Add new fields to InDepthResponse ─────────────────────────────────
        migrations.AddField(
            model_name="indepthresponse",
            name="subsection",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="review.indepthsubsection",
            ),
        ),
        migrations.AddField(
            model_name="indepthresponse",
            name="evidence_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="indepthresponse",
            name="grade",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_met", "Not Met"),
                    ("met", "Met"),
                    ("urgent_improvement", "Urgent Improvement"),
                    ("needs_attention", "Needs Attention"),
                    ("expected_standard", "Expected Standard"),
                    ("strong_standard", "Strong Standard"),
                    ("exceptional", "Exceptional"),
                ],
                default="",
                max_length=25,
            ),
        ),
        migrations.AddConstraint(
            model_name="indepthresponse",
            constraint=models.UniqueConstraint(
                fields=["review", "subsection"],
                name="unique_indepth_response_per_review_subsection",
            ),
        ),

        # ── 9. Delete InDepthStatement (no longer referenced) ────────────────────
        migrations.DeleteModel(name="InDepthStatement"),
    ]
