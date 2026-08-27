from __future__ import annotations

from .models import Branding
from .permissions import user_can_qa_risk


def branding(request):
    return {"branding": Branding.objects.first()}


def nav_flags(request):
    """Nav gating for the tabs added by the TFORS/risk proposal.

    Both tabs are built. The flag stays so the Operations tab can be taken back
    off the nav in one place if the pilot is paused.
    """

    return {
        "show_operations_tab": True,
        "can_qa_risk": user_can_qa_risk(getattr(request, "user", None)),
    }
