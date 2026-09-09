"""Apply the Trust's retention policy to the version history.

Agreed 9 Sept 2026: prior versions are kept for three months, and the newest
snapshot of every record is kept indefinitely. This command is the one place
that policy lives, so it can be changed without hunting through a scheduler.

    python manage.py prune_history           # dry run: reports what WOULD go
    python manage.py prune_history --apply   # actually deletes

What it removes: history rows older than the window that are NOT the newest
snapshot of their record. What it always keeps:

- The live row. The current text lives in the ordinary tables and this command
  never reads them, let alone deletes from them.
- The newest history row for every record, however old. So every live row
  always has one recoverable copy, and a deleted record's final state stays
  recoverable too. That copy is a duplicate of what is (or was) live, not extra
  personal data, so it does not weaken the three-month decision.

The historical tables have no incoming foreign keys, so nothing can cascade out
of them. Verified: a zero-day prune removes every prunable row and leaves all
live rows byte-identical.

NEVER add this to startup.sh. That script runs unattended on every deploy, and
a destructive command in it is exactly the shape of the incident that led to
version history being added in the first place. Schedule it externally (an
Azure WebJob or a cron on the App Service) and keep the dry run as the default
so a mistyped invocation reports rather than deletes.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from review.models import (
    Evaluation,
    InDepthResponse,
    InDepthReview,
    OperationsEntry,
    OperationsNote,
    Risk,
)

RETENTION_DAYS = 90

# The six models carrying HistoricalRecords. Listed explicitly rather than
# discovered, so adding history to a new model is a deliberate decision here
# too.
TRACKED_MODELS = (
    Evaluation,
    InDepthReview,
    InDepthResponse,
    OperationsEntry,
    OperationsNote,
    Risk,
)


def prunable_history(model, cutoff):
    """History rows for `model` older than `cutoff`, minus each record's newest.

    `history_id` is an auto-increment, so the maximum per original record id is
    that record's most recent snapshot -- including a deletion marker, which
    carries the record's final state.
    """
    history_model = model.history.model
    newest_per_record = (
        history_model.objects.values("id")
        .annotate(newest=Max("history_id"))
        .values_list("newest", flat=True)
    )
    return history_model.objects.filter(history_date__lt=cutoff).exclude(
        history_id__in=newest_per_record
    )


class Command(BaseCommand):
    help = (
        f"Delete history rows older than {RETENTION_DAYS} days, always keeping the "
        "newest snapshot of every record. Dry run unless --apply is given. Never "
        "touches live data. Do not put this in startup.sh."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this flag the command only reports.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=RETENTION_DAYS,
            help=f"Retention window in days (default {RETENTION_DAYS}).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        apply = options["apply"]
        cutoff = timezone.now() - timezone.timedelta(days=days)
        mode = "APPLYING" if apply else "DRY RUN"
        self.stdout.write(
            f"{mode}: history older than {days} days, keeping the newest snapshot "
            "of every record."
        )

        total = 0
        with transaction.atomic():
            for model in TRACKED_MODELS:
                queryset = prunable_history(model, cutoff)
                count = queryset.count()
                total += count
                self.stdout.write(f"  {model.__name__:<18} {count} prunable row(s)")
                if apply and count:
                    queryset.delete()

        if apply:
            self.stdout.write(self.style.SUCCESS(f"Deleted {total} history row(s)."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run only: {total} row(s) would be deleted. "
                    "Re-run with --apply to delete."
                )
            )
