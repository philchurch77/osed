from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from review.models import School


class Command(BaseCommand):
    help = "Seed the initial list of schools. Safe to run multiple times."

    def handle(self, *args, **options):
        schools = [
            ("Rose Hill School", School.Phase.PRIMARY),
            ("Copleston High School", School.Phase.SECONDARY),
            ("Britannia Primary and Nursery School", School.Phase.PRIMARY),
            ("Stowupland High School", School.Phase.SECONDARY),
            ("Bacton Primary School", School.Phase.PRIMARY),
            ("Cedars Park Primary School", School.Phase.PRIMARY),
            ("Mendelsham Primary School", School.Phase.PRIMARY),
        ]

        demo_logos = {
            "Rose Hill School": "Rose_Hill_School.png",
            "Copleston High School": "Copleston_High_School.png",
            "Britannia Primary and Nursery School": "Britannia_Primary_and_Nursery_School.png",
            "Stowupland High School": "Stowupland_High_School.jpeg",
            "Bacton Primary School": "Bacton_Primary_School.jpeg",
            "Cedars Park Primary School": "Cedars_Park_Primary_School.jpeg",
            # Note: file on disk is spelled "Mendlesham".
            "Mendelsham Primary School": "Mendlesham_Primary_School.jpeg",
        }
        logos_dir = Path(settings.MEDIA_ROOT) / "school_logos"

        created = 0
        updated = 0
        logos_attached = 0

        for name, phase in schools:
            obj, was_created = School.objects.get_or_create(name=name)
            if was_created:
                created += 1
            if obj.phase != phase:
                obj.phase = phase
                obj.save(update_fields=["phase"])
                if not was_created:
                    updated += 1

            logo_filename = demo_logos.get(name)
            if logo_filename and not obj.logo:
                logo_path = logos_dir / logo_filename
                if logo_path.exists():
                    obj.logo.name = f"school_logos/{logo_filename}"
                    obj.save(update_fields=["logo"])
                    logos_attached += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Schools created: {created}. Schools updated: {updated}. Logos attached: {logos_attached}."
            )
        )
