from __future__ import annotations

from .models import Branding
from .permissions import user_can_qa_risk, user_is_governor


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
    """

    user = getattr(request, "user", None)
    return {
        "show_operations_tab": True,
        "can_qa_risk": user_can_qa_risk(user),
        "is_governor": user_is_governor(user),
    }
