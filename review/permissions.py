from __future__ import annotations

from functools import wraps

from django.contrib.auth.models import AnonymousUser
from django.shortcuts import render

from .models import SchoolProfile


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
    # Governors are read-only by construction, not by omission. Checking it
    # here means every existing POST guard and _readonly_redirect in the
    # application already covers them, and an account that somehow acquires
    # EDIT_PERMS as well still cannot save.
    if user_is_governor(user):
        return False
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
    # Governor wins over any group membership: the pages the QA permission
    # unlocks are pages a governor may not reach at all.
    if user_is_governor(user):
        return False
    return user.has_perm(QA_RISK_PERM)


# Pages a governor account may reach. Everything else in review/urls.py is
# refused. `enter` is a RedirectView onto `dashboard`, so it lands on an
# allowed page and needs no gate of its own.
#
# `home` is a deliberate fourth page and is not in this set because it lives in
# osed/urls.py, not review/urls.py. It is the post-login landing page and the
# nav links to it, so gating it would 403 a governor's "Home" link; it renders
# only the names and logos of the user's own schools, scoped through
# _get_allowed_schools. GovernorAccessTests asserts that explicitly so the
# decision is written down rather than assumed.
GOVERNOR_URL_NAMES = frozenset({"dashboard", "board", "evaluation", "enter"})


def user_is_governor(user) -> bool:
    """Return True if this account is a governor, i.e. read-only and limited to
    the School Dashboard, Trust Dashboard and Evaluation pages.

    Superusers are never governors: the role lives on SchoolProfile and
    superusers are exempt from needing one at all (see allauth_adapters).

    The answer is cached on the user instance because nav_flags asks it on
    every request, including admin pages that never touch a SchoolProfile.
    """

    if not user or isinstance(user, AnonymousUser):
        return False
    if getattr(user, "is_superuser", False):
        return False

    cached = getattr(user, "_osed_is_governor", None)
    if cached is not None:
        return cached

    # No profile means no role, which reads here as "not a governor" -- i.e.
    # this lookup on its own fails open. It is safe only because
    # provisioning_problem() in allauth_adapters.py refuses any non-superuser
    # without a SchoolProfile at login, so the only profile-less session that
    # can exist is a superuser's, and superusers have already returned above.
    # If that login gate is ever relaxed, this branch has to be revisited.
    role = (
        SchoolProfile.objects.filter(user=user)
        .values_list("role", flat=True)
        .first()
    )
    is_governor = role == SchoolProfile.Role.GOVERNOR
    user._osed_is_governor = is_governor
    return is_governor


def governor_denied(view_func):
    """Refuse a governor account this page with a rendered 403.

    Hiding a link in the nav is decoration; this is the gate. Note that the
    decorator alone is a deny-list, which fails *open* for the next view
    somebody adds -- the guarantee is GovernorUrlCoverageTests, which walks
    review/urls.py and goes red if a route appears that is neither in
    GOVERNOR_URL_NAMES nor decorated here.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if user_is_governor(getattr(request, "user", None)):
            # Carry the school the governor was working on through to the
            # recovery links. Coerced through int() before it can reach an
            # href, and _resolve_school_selection re-checks it against the
            # user's own allowed set on the way back in.
            school_param = ""
            raw_school = (request.GET.get("school") or "").strip()
            if raw_school:
                try:
                    school_param = f"?school={int(raw_school)}"
                except (TypeError, ValueError):
                    school_param = ""
            return render(
                request,
                "review/not_permitted.html",
                {"user": request.user, "school_param": school_param},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    _wrapped.governor_denied = True
    return _wrapped
