from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


GROUP_NAME = "Risk QA"


def _ensure_risk_qa_group() -> Group:
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)

    desired = [
        ("review", "qa_risk"),
    ]

    perms = []
    for app_label, codename in desired:
        try:
            perms.append(
                Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
            )
        except Permission.DoesNotExist as exc:
            raise CommandError(f"Missing permission: {app_label}.{codename}") from exc

    group.permissions.set(perms)
    return group


class Command(BaseCommand):
    help = (
        "Create/update the 'Risk QA' group, which lets the CFO sign risk "
        "register entries off before TFORS and see the cross-school "
        "'awaiting QA' view. One-off, like ensure_osed_staff_group."
    )

    def handle(self, *args, **options):
        group = _ensure_risk_qa_group()
        self.stdout.write(self.style.SUCCESS(f"Group ready: {group.name}"))
        self.stdout.write(
            "Members also need a SchoolProfile listing every school they QA — "
            "the QA view still respects school scoping."
        )
