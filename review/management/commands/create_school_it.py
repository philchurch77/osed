from __future__ import annotations

import getpass

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError

from review.models import School, SchoolProfile


def _ensure_school_it_group() -> Group:
    group, _ = Group.objects.get_or_create(name="School IT")

    desired = [
        ("auth", "view_user"),
        ("auth", "add_user"),
        ("auth", "change_user"),
        ("review", "view_school"),
        ("review", "change_school"),
        ("review", "view_schoolprofile"),
        ("review", "add_schoolprofile"),
        ("review", "change_schoolprofile"),
        ("review", "view_evaluation"),
    ]

    perms = []
    for app_label, codename in desired:
        try:
            perms.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
        except Permission.DoesNotExist as exc:
            raise CommandError(f"Missing permission: {app_label}.{codename}") from exc

    group.permissions.set(perms)
    return group


class Command(BaseCommand):
    help = (
        "Create (or update) a per-school IT admin account: staff, limited perms, and linked SchoolProfile."
    )

    def add_arguments(self, parser):
        parser.add_argument("school_name", help="Exact School.name")
        parser.add_argument("username", help="Username for the IT account")
        parser.add_argument("--email", default="", help="Optional email")
        parser.add_argument(
            "--password",
            default=None,
            help="Optional password (if omitted, you'll be prompted)",
        )

    def handle(self, *args, **options):
        school_name: str = options["school_name"]
        username: str = options["username"]
        email: str = options["email"]
        password: str | None = options["password"]

        try:
            school = School.objects.get(name=school_name)
        except School.DoesNotExist as exc:
            raise CommandError(f"School not found: {school_name}") from exc

        group = _ensure_school_it_group()

        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        if email and user.email != email:
            user.email = email

        user.is_active = True
        user.is_staff = True
        user.is_superuser = False

        if created and password is None:
            password = getpass.getpass("Password: ")
            password2 = getpass.getpass("Confirm password: ")
            if password != password2:
                raise CommandError("Passwords did not match")

        if password is not None:
            user.set_password(password)

        user.save()
        user.groups.add(group)

        profile, _ = SchoolProfile.objects.update_or_create(user=user, defaults={"school": school})
        profile.schools.add(school)

        self.stdout.write(
            self.style.SUCCESS(
                f"School IT user ready: {username} (school={school.name})."
            )
        )
