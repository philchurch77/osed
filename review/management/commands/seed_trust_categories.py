from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from review.models import InDepthArea, TrustCategory


# The nine OSED evaluation areas, matched against InDepthArea by name. The app's
# existing names win over the proposal's table — the proposal writes "Post-16
# Provision" where the app has "Post-16". If an area is missing, it is skipped
# rather than invented, so a rename shows up as a warning here instead of
# silently forking the list.
EVALUATION_AREA_NAMES: list[str] = [
    "Safeguarding",
    "Inclusion",
    "Curriculum and Teaching",
    "Achievement",
    "Attendance and Behaviour",
    "Personal Development and Wellbeing",
    "Early Years",
    "Post-16",
    "Leadership and Governance",
]

# The five Operations & Resources domains. Also the domain list phase two groups
# its metrics under.
OPERATIONS_DOMAINS: list[tuple[str, str]] = [
    ("finance-icfp", "Finance & ICFP"),
    ("hr-workforce", "HR & Workforce"),
    ("estates-operations", "Estates & Operations"),
    ("it", "IT"),
    ("governance-compliance", "Governance & Compliance"),
]


class Command(BaseCommand):
    help = (
        "Seed the shared 14-value TrustCategory list (9 OSED evaluation areas "
        "routing to SIV, 5 Operations & Resources domains routing to TFORS). "
        "Idempotent — safe to run on every deploy."
    )

    def handle(self, *args, **options):
        created = 0
        updated = 0
        missing: list[str] = []

        with transaction.atomic():
            order = 0
            for name in EVALUATION_AREA_NAMES:
                order += 10
                area = InDepthArea.objects.filter(name=name).first()
                if area is None:
                    missing.append(name)
                    continue
                _, was_created = TrustCategory.objects.update_or_create(
                    indepth_area=area,
                    defaults={
                        "group": TrustCategory.Group.EVALUATION_AREA,
                        "routes_to": TrustCategory.Route.SIV,
                        "order": order,
                        "domain_key": "",
                        "domain_name": "",
                    },
                )
                created += int(was_created)
                updated += int(not was_created)

            for key, label in OPERATIONS_DOMAINS:
                order += 10
                _, was_created = TrustCategory.objects.update_or_create(
                    domain_key=key,
                    defaults={
                        "group": TrustCategory.Group.OPERATIONS_DOMAIN,
                        "domain_name": label,
                        "routes_to": TrustCategory.Route.TFORS,
                        "order": order,
                        "indepth_area": None,
                    },
                )
                created += int(was_created)
                updated += int(not was_created)

        total = TrustCategory.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Trust categories seeded. Created: {created}, updated: {updated}, "
                f"total: {total}."
            )
        )
        for name in missing:
            self.stdout.write(
                self.style.WARNING(
                    f'No InDepthArea named "{name}" — category skipped. Run '
                    "load_indepth_criteria first, or correct the name here."
                )
            )
