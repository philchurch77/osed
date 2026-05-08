from __future__ import annotations

from django.core.management.base import BaseCommand

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

        created = 0
        updated = 0

        for name, phase in schools:
            obj, was_created = School.objects.get_or_create(name=name)
            if was_created:
                created += 1
            if obj.phase != phase:
                obj.phase = phase
                obj.save(update_fields=["phase"])
                if not was_created:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Schools created: {created}. Schools updated: {updated}."
            )
        )
