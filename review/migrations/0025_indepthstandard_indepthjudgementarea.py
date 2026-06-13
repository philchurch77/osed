from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0024_create_missing_indepthsubsection"),
    ]

    operations = [
        migrations.CreateModel(
            name="InDepthStandard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.CharField(
                        choices=[
                            ("urgent_improvement", "Urgent Improvement"),
                            ("needs_attention", "Needs Attention"),
                            ("expected_standard", "Expected Standard"),
                            ("strong_standard", "Strong Standard"),
                            ("exceptional", "Exceptional"),
                            ("met", "Met"),
                            ("not_met", "Not Met"),
                        ],
                        max_length=25,
                    ),
                ),
                ("focus", models.TextField(blank=True, default="")),
                ("usage_notes", models.JSONField(blank=True, default=list)),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="standards",
                        to="review.indeptharea",
                    ),
                ),
            ],
            options={
                "ordering": ("area__order", "order"),
            },
        ),
        migrations.CreateModel(
            name="InDepthJudgementArea",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("statement", models.TextField()),
                ("key_questions", models.JSONField(blank=True, default=list)),
                ("suggested_evidence", models.JSONField(blank=True, default=list)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("is_flat", models.BooleanField(default=False)),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "standard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="judgement_areas",
                        to="review.indepthstandard",
                    ),
                ),
            ],
            options={
                "ordering": ("standard", "order"),
            },
        ),
        migrations.AddConstraint(
            model_name="indepthstandard",
            constraint=models.UniqueConstraint(
                fields=("area", "key"), name="unique_indepth_standard_per_area"
            ),
        ),
    ]
