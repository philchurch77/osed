from __future__ import annotations

from django.urls import path
from django.views.generic.base import RedirectView

from . import views

app_name = "review"

urlpatterns = [
    path("enter/", RedirectView.as_view(pattern_name="review:dashboard"), name="enter"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("respond/", views.respond, name="respond"),
    path("overview/", views.overview, name="overview"),
    path("evaluation/", views.evaluation, name="evaluation"),
]
