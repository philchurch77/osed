from __future__ import annotations

from . import powerbi
from .models import Branding
from .permissions import requested_school_param, user_can_qa_risk, user_is_governor


def branding(request):
    return {"branding": Branding.objects.first()}


def nav_flags(request):
    """Nav gating for the tabs added by the TFORS/risk proposal.

    Both tabs are built. The flag stays so the Operations tab can be taken back
    off the nav in one place if the pilot is paused.

    `is_governor` hides the tabs a governor may not open, and suppresses the
    risk and operations blocks on the Trust Dashboard. It is decoration only --
    the gate is @governor_denied on the views themselves. Both helpers share one
    cached lookup per request, so this adds at most a single query.

    `nav_school_param` carries the working school from tab to tab. Without it
    every nav link is a bare path, so a multi-school user is silently returned
    to their default school on every move -- and now that the scoped pages open
    without a school, they would be sent back to the chooser on every move too.
    It is read from the query string, not the database, so it costs no query;
    an unrequested school stays unrequested, which is what keeps "nothing
    chosen" chosen.
    """

    user = getattr(request, "user", None)
    return {
        "show_operations_tab": True,
        # Off until the Trust sets POWERBI_ENABLED and the report's filter
        # target. Read through powerbi.is_configured() rather than the raw
        # setting so the nav cannot advertise a tab whose every page would say
        # "not set up yet".
        "show_context_dashboard_tab": powerbi.is_configured(),
        "can_qa_risk": user_can_qa_risk(user),
        "is_governor": user_is_governor(user),
        "nav_school_param": requested_school_param(request),
    }
