"""Admin index grouping.

Every model in this project lives in the single `review` app, so Django's
default index renders all 22 of them as one alphabetical wall under a heading
called "Review" -- with Risk and Operations models scattered through it. This
splits that one block into named sections without touching the models: no
proxy models, no `app_label` juggling, no migrations.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.apps import AdminConfig

# Section heading -> the models under it, in the order they should appear.
# Order here is deliberate (most-used first), not alphabetical.
ADMIN_SECTIONS = [
    (
        "Schools & settings",
        ["School", "SchoolProfile", "Branding"],
    ),
    (
        "Dashboard evaluation",
        ["Category", "ReviewPeriod", "Evaluation"],
    ),
    (
        "In-depth review",
        [
            "InDepthArea",
            "InDepthStandard",
            "InDepthSubSection",
            "InDepthJudgementArea",
            "InDepthReview",
            "InDepthResponse",
        ],
    ),
    (
        "Risk register",
        # TrustCategory is shared with Operations, but it is the routing list
        # (TFORS or SIV) so it sits with Risk. Not to be confused with
        # Category above, which is the 8 dashboard evaluation categories.
        ["Risk", "RiskRating", "RiskSettings", "TrustCategory"],
    ),
    (
        "Operations & Resources (pilot)",
        [
            "OperationsMetricVisibility",
            "OperationsMetric",
            "OperationsEntry",
            "StatutoryComplianceItem",
            "GrantPublication",
            "ComplaintTheme",
            "OperationsNote",
        ],
    ),
]

# Anything registered later but not listed above lands here rather than
# vanishing off the index.
FALLBACK_SECTION = "Review — other"


class OsedAdminSite(admin.AdminSite):
    site_header = "OSED administration"
    site_title = "OSED admin"
    index_title = "Self-evaluation administration"

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # On a single-app page (/admin/review/) leave the listing alone --
        # splitting it there would break the app index Django builds for it.
        if app_label is not None:
            return app_list

        sections, others = [], []
        for app in app_list:
            if app.get("app_label") == "review":
                sections.extend(self._split_review(app))
            else:
                others.append(app)
        # Review sections first: this is the app people actually come here for.
        return sections + others

    def _split_review(self, app):
        by_name = {model["object_name"]: model for model in app["models"]}
        sections = []
        placed = set()

        for title, object_names in ADMIN_SECTIONS:
            models = [by_name[name] for name in object_names if name in by_name]
            if not models:
                # Every model in this section is hidden by permissions.
                continue
            placed.update(model["object_name"] for model in models)
            sections.append({**app, "name": title, "models": models})

        leftover = [m for m in app["models"] if m["object_name"] not in placed]
        if leftover:
            sections.append({**app, "name": FALLBACK_SECTION, "models": leftover})
        return sections


class OsedAdminConfig(AdminConfig):
    """Points `admin.site` at OsedAdminSite. Wired in via INSTALLED_APPS."""

    default_site = "review.admin_site.OsedAdminSite"
