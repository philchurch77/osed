from __future__ import annotations

from django.urls import path
from django.views.generic.base import RedirectView

from . import views

app_name = "review"

urlpatterns = [
    path("enter/", RedirectView.as_view(pattern_name="review:dashboard"), name="enter"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("overview/", views.overview, name="overview"),
    path("board/", views.board_view, name="board"),
    path("evaluation/", views.evaluation, name="evaluation"),
    path("in-depth/", views.indepth_review, name="indepth_review"),
    path("reflection/", views.reflection, name="reflection"),
    path("operations/", views.operations, name="operations"),
    # Not added to permissions.GOVERNOR_URL_NAMES: the view carries
    # @governor_denied, which is what keeps GovernorUrlCoverageTests green.
    path("context/", views.context_dashboard, name="context_dashboard"),
    path("risk/", views.risk_register, name="risk_register"),
    path("risk/qa/", views.risk_qa, name="risk_qa"),
]
