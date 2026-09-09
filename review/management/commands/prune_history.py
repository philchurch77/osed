"""Apply the Trust's retention policy to the version history.

Agreed 9 Sept 2026: prior versions are kept for three months. This command is
the one place that policy lives, so it can be changed without hunting through
a scheduler.

    python manage.py prune_history           # dry run: reports what WOULD go
    python manage.py prune_history --apply   # actually deletes

It only ever touches the six Historical* tables. The live rows -- the current
version of every record -- are never read, let alone deleted, and the
historical tables have no incoming foreign keys, so nothing can cascade out of
them. Verified: a prune with --days 0 removed every history row and left all
live rows byte-identical.

NEVER add this to startup.sh. That script runs unattended on every deploy, and
a destructive command in it is exactly the shape of the incident that led to
version history being added in the first place. Schedule it externally (an
Azure WebJob or a cron on the App Service) and keep the dry run as the default
so a mistyped invocation reports rather than deletes.

Note what "three months" means in practice: a record not edited for longer
than that has no trail at all until it is next saved, and if it is then
cascade-deleted there is nothing to recover from. That is the policy working
as intended, not a gap -- but it is worth knowing when someone asks.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand

RETENTION_DAYS = 90


class Command(BaseCommand):
    help = (
        f"Delete history rows older than {RETENTION_DAYS} days from the six "
        "version-tracked models. Dry run unless --apply is given. Never touches "
        "live data. Do not put this in startup.sh."
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
        mode = "APPLYING" if apply else "DRY RUN"
        self.stdout.write(
            f"{mode}: history rows older than {days} days on all version-tracked models."
        )
        args = ["--auto", "--days", str(days)]
        if not apply:
            args.append("--dry")
        call_command("clean_old_history", *args, verbosity=2)
        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry run only. Re-run with --apply to delete.")
            )
