from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from review.models import Category


CATEGORIES: list[tuple[int, str]] = [
    (10, "Safeguarding"),
    (20, "Inclusion"),
    (30, "Curriculum and Teaching"),
    (40, "Achievement"),
    (50, "Attendance and Behaviour"),
    (60, "Personal Development and Well-being"),
    (70, "Early Years / P16"),
    (80, "Leadership and Governance"),
]


class Command(BaseCommand):
    help = "Seed the standard OSED categories and deactivate any others (non-destructive)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reactivate-all",
            action="store_true",
            help="If set, reactivates all categories instead of deactivating non-standard ones.",
        )

    def handle(self, *args, **options):
        reactivate_all: bool = options["reactivate_all"]
        desired_names = [name for _, name in CATEGORIES]

        with transaction.atomic():
            for order, name in CATEGORIES:
                # Avoid duplicate name rows causing confusion.
                existing = list(Category.objects.filter(name=name).order_by("id"))
                if existing:
                    keep = existing[0]
                    Category.objects.filter(id=keep.id).update(order=order, is_active=True)
                    if len(existing) > 1:
                        Category.objects.filter(id__in=[c.id for c in existing[1:]]).update(is_active=False)
                else:
                    Category.objects.create(name=name, order=order, is_active=True)

            if reactivate_all:
                Category.objects.update(is_active=True)
            else:
                Category.objects.exclude(name__in=desired_names).update(is_active=False)

        active = Category.objects.filter(is_active=True).count()
        total = Category.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Seeded categories. Active: {active} / Total: {total}"))
