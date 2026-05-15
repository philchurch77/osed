from __future__ import annotations

from django.contrib.auth.models import AnonymousUser


EDIT_PERMS = (
    "review.add_evaluation",
    "review.change_evaluation",
    "review.add_indepthresponse",
    "review.change_indepthresponse",
)


def user_can_edit(user) -> bool:
    """Return True if the user should be allowed to modify data in the user UI.

    Viewer accounts (e.g. trustees) should be able to log in and view data, but
    not edit. Staff accounts should be granted the permissions in EDIT_PERMS.
    """

    if not user or isinstance(user, AnonymousUser):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return any(user.has_perm(p) for p in EDIT_PERMS)
