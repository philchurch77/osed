from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


def _ensure_osed_staff_group() -> Group:
    group, _ = Group.objects.get_or_create(name="OSED Staff")

    desired = [
        ("review", "add_evaluation"),
        ("review", "change_evaluation"),
        ("review", "add_indepthresponse"),
        ("review", "change_indepthresponse"),
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
    help = "Create/update the 'OSED Staff' group used to grant edit access in the user UI."

    def handle(self, *args, **options):
        group = _ensure_osed_staff_group()
        self.stdout.write(self.style.SUCCESS(f"Group ready: {group.name}"))
