from __future__ import annotations

from pathlib import Path

from django.core.exceptions import MultipleObjectsReturned
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.conf import settings

from review.models import School


class Command(BaseCommand):
    help = "Seed the initial list of schools. Safe to run multiple times."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-apply the seed phase to schools that already exist, discarding admin edits.",
        )

    def handle(self, *args, **options):
        force: bool = options["force"]
        # (canonical OSED name, phase, Power BI slicer value)
        #
        # The third value is the string this school appears as in the Power BI
        # Context Dashboard's School slicer, which matches the OSED name in none
        # of the seven cases. Seeded rather than left to the admin because the
        # values are known, are neither secret nor personal, and startup.sh
        # already runs this command -- so a fresh database gets a working page
        # with no runbook step. Applied only when blank, so the day a report
        # author renames a slicer value, the admin fix survives the next deploy.
        schools = [
            ("Rose Hill School", School.Phase.PRIMARY, "Rose Hill Primary"),
            ("Copleston High School", School.Phase.SECONDARY, "Copleston"),
            ("Britannia Primary and Nursery School", School.Phase.PRIMARY, "Britannia Primary"),
            ("Stowupland High School", School.Phase.SECONDARY, "Stowupland"),
            ("Bacton Primary School", School.Phase.PRIMARY, "Bacton Primary"),
            ("Cedars Park Primary School", School.Phase.PRIMARY, "Cedars Park Primary"),
            ("Mendlesham Primary School", School.Phase.PRIMARY, "Mendlesham Primary"),
        ]

        demo_logos = {
            "Rose Hill School": "Rose_Hill_School.png",
            "Copleston High School": "Copleston_High_School.png",
            "Britannia Primary and Nursery School": "Britannia_Primary_and_Nursery_School.png",
            "Stowupland High School": "Stowupland_High_School.jpeg",
            "Bacton Primary School": "Bacton_Primary_School.jpeg",
            "Cedars Park Primary School": "Cedars_Park_Primary_School.jpeg",
            "Mendlesham Primary School": "Mendlesham_Primary_School.jpeg",
        }
        logos_dir = Path(settings.MEDIA_ROOT) / "school_logos"
        use_azure_media_storage = getattr(settings, "USE_AZURE_MEDIA_STORAGE", False)

        created = 0
        updated = 0
        logos_attached = 0
        powerbi_names_set = 0

        # Rename any existing record with the old misspelling.
        School.objects.filter(name="Mendelsham Primary School").update(name="Mendlesham Primary School")

        for name, phase, powerbi_name in schools:
            # One transaction per school, and a failure skips only that school.
            # Without this, a single IntegrityError -- an admin having given
            # school A the slicer value that belongs to school B, or the
            # Mendelsham rename leaving two rows with one name -- aborted the
            # whole loop, so every school after it got neither its Power BI name
            # nor its logo. startup.sh swallows the failure, so the only symptom
            # would be a half-configured Trust and a line in a log nobody reads.
            try:
                with transaction.atomic():
                    obj, was_created = School.objects.get_or_create(name=name)
                    school_created = 1 if was_created else 0
                    school_updated = 0
                    name_set = 0
                    logo_set = 0

                    # Phase is set when the school is first created, and on an
                    # existing school only with --force. It is admin-editable, and
                    # it selects the phase-aware OperationsMetricBand rows, so
                    # reverting it every deploy made a school's Operations RAGs
                    # recompute against the wrong bands.
                    if obj.phase != phase and (was_created or force):
                        obj.phase = phase
                        obj.save(update_fields=["phase"])
                        if not was_created:
                            school_updated = 1

                    # On CREATION only -- deliberately not set-if-blank. Blank is
                    # a meaningful, documented value here ("show no report for
                    # this school"), so a set-if-blank rule cannot tell "never
                    # configured" from "the Trust switched this school off", and
                    # every deploy would silently switch it back on. School
                    # carries no simple_history, so nothing would record that it
                    # had ever been cleared. Existing rows are populated once by
                    # migration 0037 instead.
                    if was_created and powerbi_name:
                        obj.powerbi_school_name = powerbi_name
                        obj.save(update_fields=["powerbi_school_name"])
                        name_set = 1

                    logo_filename = demo_logos.get(name)
                    if logo_filename:
                        desired_name = f"school_logos/{logo_filename}"
                        logo_path = logos_dir / logo_filename

                        current_missing_on_disk = False
                        if obj.logo and not use_azure_media_storage:
                            current_path = Path(settings.MEDIA_ROOT) / obj.logo.name
                            current_missing_on_disk = not current_path.exists()

                        if (not obj.logo or current_missing_on_disk) and logo_path.exists():
                            obj.logo.name = desired_name
                            obj.save(update_fields=["logo"])
                            logo_set = 1
            except (IntegrityError, MultipleObjectsReturned) as exc:
                self.stderr.write(
                    self.style.WARNING(f"  Skipped {name}: {exc}")
                )
                continue

            created += school_created
            updated += school_updated
            powerbi_names_set += name_set
            logos_attached += logo_set

        # Name the schools the Context Dashboard will refuse to show. A blank
        # mapping is a legitimate setting ("show no report for this school"),
        # so this is not an error -- but a school that was meant to be mapped
        # and quietly is not would otherwise be invisible until a Principal
        # reports an empty page, and the deploy log is where anyone would look.
        unmapped = list(
            School.objects.filter(powerbi_school_name="")
            .order_by("name")
            .values_list("name", flat=True)
        )
        if unmapped:
            self.stdout.write(
                "  No Power BI school name (Context Dashboard will show no "
                f"report): {', '.join(unmapped)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Schools created: {created}. Schools updated: {updated}. "
                f"Logos attached: {logos_attached}. Power BI names set: {powerbi_names_set}."
            )
        )
