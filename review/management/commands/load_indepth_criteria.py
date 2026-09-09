"""
Load in-depth review criteria from review/data/criteria.json (the Nov 2025
Ofsted framework drafts extracted from the 'OSED statements' workbooks).

Builds:  InDepthArea -> InDepthStandard -> InDepthJudgementArea

This replaces the hardcoded placeholder data in load_indepth_blueprint.py.
The criteria.json file is re-importable, so a revised drop of the draft
workbooks can be re-extracted and reloaded.

Run with:
    python manage.py load_indepth_criteria            # upsert
    python manage.py load_indepth_criteria --clear     # wipe new-structure rows first
    python manage.py load_indepth_criteria --path /custom/criteria.json
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from review.management.commands._indepth_sync import sync_judgement_areas
from review.models import (
    InDepthArea,
    InDepthStandard,
)

# Sheet title in criteria.json -> InDepthStandard.Key value
SHEET_TO_KEY = {
    "Expected Standard": InDepthStandard.Key.EXPECTED_STANDARD,
    "Strong Standard": InDepthStandard.Key.STRONG_STANDARD,
    "Urgent Improvement": InDepthStandard.Key.URGENT_IMPROVEMENT,
    "Needs Attention": InDepthStandard.Key.NEEDS_ATTENTION,
    "Exceptional": InDepthStandard.Key.EXCEPTIONAL,
    "Met": InDepthStandard.Key.MET,
    "Not Met": InDepthStandard.Key.NOT_MET,
}

# Display/import order of the standards within an area
KEY_ORDER = {
    InDepthStandard.Key.URGENT_IMPROVEMENT: 1,
    InDepthStandard.Key.NEEDS_ATTENTION: 2,
    InDepthStandard.Key.EXPECTED_STANDARD: 3,
    InDepthStandard.Key.STRONG_STANDARD: 4,
    InDepthStandard.Key.EXCEPTIONAL: 5,
    InDepthStandard.Key.NOT_MET: 1,
    InDepthStandard.Key.MET: 2,
}

# Flat-shape standards whose statements are nonetheless RAG-able in the new
# ladder flow (the up-path tops out at Exceptional; the down-path RAGs Urgent
# Improvement). Needs Attention is never RAGed — it is only an outcome label —
# so it stays a non-rateable reference list.
RATEABLE_FLAT_KEYS = {
    InDepthStandard.Key.URGENT_IMPROVEMENT,
    InDepthStandard.Key.EXCEPTIONAL,
}

DEFAULT_PATH = Path(settings.BASE_DIR) / "review" / "data" / "criteria.json"


class Command(BaseCommand):
    help = "Load in-depth review criteria from criteria.json into the new standard/judgement-area models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all InDepthStandard rows (and their judgement areas) before loading.",
        )
        parser.add_argument(
            "--path",
            default=str(DEFAULT_PATH),
            help="Path to criteria.json (defaults to review/data/criteria.json).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"criteria.json not found at: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        areas = data.get("areas", [])
        if not areas:
            raise CommandError("criteria.json contained no 'areas'.")

        if opts["clear"]:
            deleted, _ = InDepthStandard.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared existing standards/judgement areas ({deleted} rows)."))

        n_areas = n_standards = n_ja = 0
        n_removed = n_kept = 0

        for a in areas:
            area, _ = InDepthArea.objects.update_or_create(
                name=a["name"],
                defaults={
                    "order": a.get("order", 0),
                    "is_safeguarding": a.get("is_safeguarding", False),
                },
            )
            n_areas += 1

            for sheet_title, body in a.get("standards", {}).items():
                key = SHEET_TO_KEY.get(sheet_title)
                if key is None:
                    self.stdout.write(self.style.WARNING(f"  Skipping unknown sheet '{sheet_title}' in {a['name']}"))
                    continue

                standard, _ = InDepthStandard.objects.update_or_create(
                    area=area,
                    key=key,
                    defaults={
                        "focus": body.get("focus", ""),
                        "usage_notes": body.get("notes", []),
                        "order": KEY_ORDER.get(key, 0),
                    },
                )
                n_standards += 1

                # Reload this standard's judgement areas in place. A blind
                # delete here cascaded to InDepthResponse and destroyed every
                # school's commentary on each deploy — see _indepth_sync.
                rows = []
                if "judgement_areas" in body:  # rich shape
                    for ja in body["judgement_areas"]:
                        rows.append(
                            dict(
                                statement=ja.get("statement", ""),
                                key_questions=ja.get("key_questions", []),
                                suggested_evidence=ja.get("suggested_evidence", []),
                                sources=ja.get("sources", []),
                                is_flat=False,
                            )
                        )
                else:  # flat statements/notes shape
                    # Urgent Improvement and Exceptional statements are RAG-able
                    # rungs in the ladder, so load them as non-flat judgement
                    # areas; all other flat lists stay reference-only.
                    is_flat = key not in RATEABLE_FLAT_KEYS
                    for stmt in body.get("statements", []):
                        rows.append(dict(statement=stmt, is_flat=is_flat))

                written, removed, kept = sync_judgement_areas(standard, rows)
                n_ja += written
                n_removed += removed
                n_kept += kept

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {n_areas} areas, {n_standards} standards, {n_ja} judgement areas/statements."
            )
        )
        if n_removed:
            self.stdout.write(f"Removed {n_removed} retired statement(s) with no written work.")
        if n_kept:
            self.stdout.write(
                self.style.WARNING(
                    f"Kept {n_kept} retired statement(s) that hold written work — "
                    "review them in the admin rather than deleting blind."
                )
            )
