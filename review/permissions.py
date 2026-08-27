from __future__ import annotations

from django.contrib.auth.models import AnonymousUser


EDIT_PERMS = (
    "review.add_evaluation",
    "review.change_evaluation",
    "review.add_indepthresponse",
    "review.change_indepthresponse",
    "review.add_risk",
    "review.change_risk",
)


# Held by the "Risk QA" group (the CFO, and the CEO where they QA too). Kept
# separate from EDIT_PERMS: logging a risk and signing one off are different jobs.
QA_RISK_PERM = "review.qa_risk"


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


def user_can_qa_risk(user) -> bool:
    """Return True if the user may sign risk register entries off before TFORS.

    This grants the cross-school "awaiting QA" view, but it is not a bypass of
    school scoping: that view still filters through the usual allowed-schools
    helper, so a QA account must be provisioned with the schools it reviews.
    """

    if not user or isinstance(user, AnonymousUser):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.has_perm(QA_RISK_PERM)
