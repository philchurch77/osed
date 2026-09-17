from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from django.conf import settings


# Every embed URL must start with this. It is the only thing standing between a
# mistyped App Setting and OSED framing an arbitrary site: there is no CSP in
# this project yet, so `frame-src` cannot do it for us. When CSP arrives this
# check stays -- a prefix test and a frame-src directive fail at different
# moments, and the useful one is the one that fails before the page renders.
EMBED_URL_PREFIX = "https://app.powerbi.com/reportEmbed?"


# A Power BI URL filter addresses `Table/Column`, and neither part may contain a
# space -- there is no escaping that makes it work. A report whose table is
# "School Context" cannot be filtered this way at all and has to be renamed at
# the report end. Failing the whole check here turns that into an explanatory
# panel rather than a report silently showing every school.
FILTER_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*/[A-Za-z_][A-Za-z0-9_]*$")


# The two reasons a frame is withheld. Exactly one is ever set, and either way
# there is no iframe on the page -- never a grey placeholder, never a default
# school, never an unfiltered report.
UNAVAILABLE_NOT_CONFIGURED = "not_configured"
UNAVAILABLE_SCHOOL_NOT_MAPPED = "school_not_mapped"


# Rendered verbatim, whether or not a frame is built, so it must be true in
# both states. It deliberately does NOT mention "the panel below": on the two
# unavailable states there is no panel, and a page that describes a panel that
# is not there reads as half-broken -- which is exactly the ticket this feature
# would otherwise generate in its first week.
EMBED_STANDING_TEXT = (
    "This report is provided by Power BI and opens with your own Microsoft "
    "account, not your OSED sign-in. OSED cannot see whether your account has "
    "been given access to it."
)


# Rendered only when there IS a frame, because every sentence in it is about
# that frame. The last clause covers the failure nothing else on the page can:
# a mapped school whose name does not match the report's own slicer value
# filters to nothing, and Power BI renders the report with every visual empty.
# OSED cannot detect that, and without this sentence the Principal reads it as
# "the Trust holds no data for my school".
PANEL_FAILURE_TEXT = (
    "If you are not signed in to Power BI, or your account has not been given "
    "access, the panel below will show a Microsoft sign-in page or stay blank "
    "-- that is Power BI rather than OSED, and OSED cannot tell which has "
    "happened. If the report loads but every chart is empty, the school name "
    "OSED is sending may not match the report's own; ask a Trust administrator "
    "to check it."
)


# Rendered verbatim, and asserted by a test, because this is the sentence the
# feature turns on. The supplied embed is user-owns-data (`autoAuth=true`): OSED
# chooses which school the report OPENS at, and nothing more. The viewer can
# change the report's own slicer inside the panel. Access is decided by Power BI
# workspace permissions and whatever RLS is on the dataset -- a second
# access-control system this repo cannot see, cannot test and cannot keep in
# step with SchoolProfile. See POWERBI_EMBED_PLAN.md section 3, which rejected
# this mode for that reason; this notice is the condition on which it shipped
# anyway. Do not soften it, and do not describe this page as filtering a user to
# their own school.
FILTER_NOTICE = (
    "This page opens the report at the school named above. The report's own "
    "school filter can be changed inside the panel. What you are able to see "
    "is controlled by Power BI, not by OSED."
)


def report_title() -> str:
    return getattr(settings, "POWERBI_REPORT_TITLE", "") or "Context Dashboard"


def _escape_filter_value(value: str) -> str:
    """Double any single quote, the way OData string literals are escaped.

    Without this a school called `St Mary's` terminates the literal early and
    the report falls back to showing everything -- the exact failure this whole
    module exists to prevent.
    """
    return value.replace("'", "''")


def is_configured() -> bool:
    """True when the four settings together describe a usable, filtered embed.

    Deliberately strict about the filter target: an embed we cannot filter is
    not a degraded version of this feature, it is a different one, and it is
    the one nobody asked for.
    """
    if not getattr(settings, "POWERBI_ENABLED", False):
        return False
    report_url = (getattr(settings, "POWERBI_REPORT_URL", "") or "").strip()
    if not report_url.startswith(EMBED_URL_PREFIX):
        return False
    target = (getattr(settings, "POWERBI_FILTER_TARGET", "") or "").strip()
    return bool(FILTER_TARGET_RE.match(target))


def resolve_embed(school) -> tuple[str, str]:
    """Return `(embed_url, unavailable_reason)` for one School.

    Exactly one of the two is ever non-empty, and the caller renders a frame
    only for the first. Kept as a single function rather than an
    `embed_url_for` / `unavailable_reason_for` pair on purpose: two entry points
    to the same decision is how one of them ends up permitting what the other
    refuses.

    There is no branch that returns an unfiltered URL. A school with no mapping
    gets no report at all -- an all-schools view handed to whoever happened to
    open the page is worse than an explanatory panel, and it would be invisible
    from this end.
    """
    if not is_configured():
        return "", UNAVAILABLE_NOT_CONFIGURED

    mapped_name = (getattr(school, "powerbi_school_name", "") or "").strip()
    if not mapped_name:
        return "", UNAVAILABLE_SCHOOL_NOT_MAPPED

    report_url = settings.POWERBI_REPORT_URL.strip()
    target = settings.POWERBI_FILTER_TARGET.strip()
    expression = f"{target} eq '{_escape_filter_value(mapped_name)}'"

    # `quote` rather than the default `quote_plus`, so the spaces in a school
    # name become `%20` and not `+`. `safe="/"` keeps the separator in
    # `Table/Column` literal, which is the form Power BI's own documentation
    # uses -- `%2F` most likely decodes to the same thing, but "most likely" is
    # not a good enough reason to send a shape nobody has tested. The supplied
    # URL already carries `reportId`, `autoAuth` and `ctid`, so the join is `&`.
    query = urlencode({"filter": expression}, safe="/", quote_via=quote)
    return f"{report_url}&{query}", ""


# Deliberately no multi-school / trust-wide helper here. The school chooser
# resolves exactly one school for every user, superusers included, so the live
# path is always single-value, and untested speculative code in a security
# module is how a future trust-wide view gets built on a function nobody ever
# exercised. When that view is commissioned, the OData `in (...)` form is a few
# lines to write next to it -- and it must arrive with its own permission,
# shaped like `Risk QA`, never on `is_superuser`, which would silently re-grade
# every existing superuser (POWERBI_EMBED_PLAN.md section 4.4).
