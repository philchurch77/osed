from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from allauth.account.views import LoginView

from .forms import (
	DashboardRatingForm,
	EvaluationEntryForm,
	InDepthJudgementAreaForm,
	RATING_CHOICES_DEFAULT,
	RATING_CHOICES_SAFEGUARDING,
	RiskCloseForm,
	RiskEntryForm,
	RiskRatingForm,
)
from .models import (
	Category,
	Evaluation,
	InDepthArea,
	InDepthJudgementArea,
	InDepthResponse,
	InDepthReview,
	InDepthStandard,
	ComplaintTheme,
	OperationsEntry,
	OperationsMetric,
	OperationsMetricVisibility,
	OperationsNote,
	ReviewPeriod,
	Risk,
	RiskRating,
	RiskSettings,
	School,
	SchoolProfile,
	TERM_LABELS,
	TrustCategory,
	current_academic_year_start,
)
from .operations import (
	BLUE as OPS_BLUE,
	AMBER as OPS_AMBER,
	RED as OPS_RED,
	GRANT_LABELS,
	LEGEND_STANDING_TEXT as OPS_LEGEND_STANDING_TEXT,
	RAG_CHOICES as OPS_RAG_CHOICES,
	RAG_LABELS as OPS_RAG_LABELS,
	RAG_LEGEND as OPS_RAG_LEGEND,
	RULE_COMPLAINTS_TREND,
	RULE_GRANT_PUBLICATION,
	RULE_STATUTORY_DATES,
	SMALL_PRINT as OPS_SMALL_PRINT,
	applicable_grants,
	complaints_rag,
	grant_rag,
	rag_for_entry,
	statutory_rag,
	summarise as ops_summarise,
)

# The three band statements a Principal can pick between; Blue is a computed
# state, never a choice.
OPS_BAND_CHOICES = [c for c in OPS_RAG_CHOICES if c[0] != OPS_BLUE]
from .permissions import user_can_edit, user_can_qa_risk
from .risk import (
	BAND_LABELS,
	RAG_CSS,
	RAG_LEGEND,
	SEVERITY,
	TREND_LABELS,
	is_escalated,
	matrix_lookup,
	matrix_rows,
	trend_for,
)


MIN_ACADEMIC_YEAR_START = 2026


def _apply_category_specific_rating_choices(*, forms, safeguarding_category_ids: set[int]) -> None:
	for form in forms:
		# Works for both bound and unbound forms.
		if form.is_bound:
			raw_category_id = form.data.get(form.add_prefix("category_id"))
		else:
			raw_category_id = (form.initial or {}).get("category_id")

		try:
			category_id = int(raw_category_id)
		except (TypeError, ValueError):
			category_id = None

		if category_id in safeguarding_category_ids:
			form.fields["rating"].choices = RATING_CHOICES_SAFEGUARDING
		else:
			form.fields["rating"].choices = RATING_CHOICES_DEFAULT


def _parse_academic_year_start(raw_value: str | None, default_year: int) -> int:
	if not raw_value:
		return default_year

	raw_value = raw_value.strip()
	# Back-compat: allow plain start year like "2026"
	if raw_value.isdigit():
		return int(raw_value)

	# Preferred: "2026-2027" (also accept "2026/2027")
	normalized = raw_value.replace("/", "-")
	parts = [p for p in normalized.split("-") if p]
	if not parts:
		return default_year
	try:
		start = int(parts[0])
	except ValueError:
		return default_year
	return start


def _no_school_profile_response(request: HttpRequest) -> HttpResponse:
	return render(
		request,
		"review/no_school_profile.html",
		{"user": request.user},
		status=403,
	)


def _get_allowed_schools(
	request: HttpRequest,
) -> tuple[SchoolProfile | None, list[School] | None, HttpResponse | None]:
	"""Fetch the user's SchoolProfile and the schools they may access.

	Returns (school_profile, allowed_schools, error_response); error_response is
	a 403 render when the user has no SchoolProfile.
	"""
	try:
		school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
			"schools"
		).get(user=request.user)
	except SchoolProfile.DoesNotExist:
		return None, None, _no_school_profile_response(request)

	allowed_schools = list(school_profile.schools.order_by("name").all())
	if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
		allowed_schools.insert(0, school_profile.school)
	return school_profile, allowed_schools, None


def _resolve_school_selection(
	request: HttpRequest,
) -> tuple[School | None, list[School] | None, HttpResponse | None]:
	"""Resolve the working school and the selector dropdown list.

	Returns (school, schools, error_response). `schools` is None when the user
	only has access to a single school (the selector is hidden in that case).
	"""
	school = None
	if request.user.is_superuser:
		schools = list(School.objects.order_by("name").all())
		selected = request.GET.get("school") or request.POST.get("school_id")
		if selected:
			try:
				school = School.objects.get(id=selected)
			except School.DoesNotExist:
				school = None
		if school is None and schools:
			school = schools[0]
		if school is None:
			messages.error(request, "No schools have been set up yet.")
			return None, None, redirect("home")
		return school, schools, None

	school_profile, allowed_schools, error = _get_allowed_schools(request)
	if error is not None:
		return None, None, error
	selected = request.GET.get("school") or request.POST.get("school_id")
	if selected:
		try:
			selected_id = int(selected)
		except (TypeError, ValueError):
			selected_id = None
		if selected_id is not None:
			school = next((s for s in allowed_schools if s.id == selected_id), None)
	if school is None:
		school = school_profile.school or (allowed_schools[0] if allowed_schools else None)
	schools = allowed_schools if len(allowed_schools) > 1 else None
	return school, schools, None


def _academic_year_context(
	request: HttpRequest, *, include_post: bool = True
) -> tuple[int, str, list[dict[str, str]]]:
	"""Return (selected_year, selected_year_value, academic_year_options)."""
	default_year = max(current_academic_year_start(), MIN_ACADEMIC_YEAR_START)
	raw_year = request.GET.get("year")
	if include_post:
		raw_year = raw_year or request.POST.get("year")
	selected_year = _parse_academic_year_start(raw_year, default_year)
	selected_year = max(selected_year, MIN_ACADEMIC_YEAR_START)
	selected_year_value = f"{selected_year}-{selected_year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, selected_year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]
	return selected_year, selected_year_value, academic_year_options


def _readonly_redirect(
	request: HttpRequest, url_name: str, params: list[tuple[str, str]]
) -> HttpResponse:
	"""Bounce a read-only user's POST back to the page, preserving their selection."""
	messages.error(request, "You have read-only access and cannot save changes.")
	query = "&".join(f"{name}={value}" for name, value in params if value)
	return redirect(f"{reverse(url_name)}{'?' + query if query else ''}")


def home(request: HttpRequest) -> HttpResponse:
	if not request.user.is_authenticated:
		# Keep the sign-in experience on the homepage.
		return LoginView.as_view(template_name="account/login.html")(request)

	if request.user.is_superuser:
		schools = School.objects.order_by("name").all()
		return render(request, "review/home.html", {"schools": schools})

	_, allowed_schools, error = _get_allowed_schools(request)
	if error is not None:
		return error
	return render(request, "review/home.html", {"schools": allowed_schools})


@login_required
def overview(request: HttpRequest) -> HttpResponse:
	school = None
	schools = None
	all_schools_selected = False

	selected_phase = (request.GET.get("phase") or "").strip().upper()
	valid_phases = {choice[0] for choice in School.Phase.choices}
	if selected_phase not in valid_phases:
		selected_phase = ""

	phase_options = [("" , "All phases")] + list(School.Phase.choices)

	if request.user.is_superuser:
		schools = list(School.objects.order_by("name").all())
		# Filter the dropdown list by phase (the aggregation query is filtered separately).
		if selected_phase:
			schools = [s for s in schools if s.phase == selected_phase]
		selected = request.GET.get("school")
		if selected is None:
			# Default landing: show all schools.
			all_schools_selected = True
			if schools:
				school = schools[0]
		elif selected == "all":
			all_schools_selected = True
			if schools:
				# Keep a non-None school in context for template convenience.
				school = schools[0]
		else:
			try:
				school = School.objects.get(id=selected)
			except School.DoesNotExist:
				school = None
		if school is None and schools and not all_schools_selected:
			school = schools[0]
		if school is None and not all_schools_selected:
			messages.error(request, "No schools have been set up yet.")
			return redirect("home")
	else:
		_, allowed_schools, error = _get_allowed_schools(request)
		if error is not None:
			return error
		# Filter the school dropdown by phase for non-superusers too.
		if selected_phase:
			allowed_schools = [s for s in allowed_schools if s.phase == selected_phase]
		selected = request.GET.get("school")
		if selected:
			try:
				selected_id = int(selected)
			except (TypeError, ValueError):
				selected_id = None
			if selected_id is not None:
				school = next((s for s in allowed_schools if s.id == selected_id), None)
		if school is None:
			school = (allowed_schools[0] if allowed_schools else None)
		schools = allowed_schools if len(allowed_schools) > 1 else None

	year, selected_year_value, academic_year_options = _academic_year_context(
		request, include_post=False
	)

	# Overview is read-only: don't create periods as a side-effect of viewing.
	periods = {
		r: ReviewPeriod.objects.filter(year=year, round=r).first()
		for r in (1, 2, 3)
	}

	rows = []
	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	for category in categories:
		cells = []
		for r in (1, 2, 3):
			period = periods.get(r)
			if period is None:
				cells.append({"avg": None, "band": None, "label": "—"})
				continue
			ratings_qs = Evaluation.objects.filter(
				period=period,
				category=category,
				rating__isnull=False,
			)
			if all_schools_selected:
				if selected_phase:
					ratings_qs = ratings_qs.filter(school__phase=selected_phase)
				if not ratings_qs.exists():
					cells.append({"avg": None, "band": None, "label": "—"})
					continue
			else:
				if school is None:
					cells.append({"avg": None, "band": None, "label": "—"})
					continue
				ratings_qs = ratings_qs.filter(school=school)
			ratings = list(ratings_qs.values_list("rating", flat=True))

			if not ratings:
				cells.append({"avg": None, "band": None, "label": "—"})
				continue

			avg = sum(ratings) / len(ratings)
			band = int(round(avg))
			band = max(1, min(5, band))
			cells.append({"avg": avg, "band": band, "label": f"{avg:.1f}"})

		rows.append({"category": category, "cells": cells})

	has_any_data = any(cell["band"] is not None for row in rows for cell in row["cells"])

	return render(
		request,
		"review/overview.html",
		{
			"school": school,
			"schools": schools,
			"all_schools_selected": all_schools_selected,
			"year": year,
			"selected_year_value": selected_year_value,
			"academic_year_options": academic_year_options,
			"rows": rows,
			"phase_options": phase_options,
			"selected_phase": selected_phase,
			"has_any_data": has_any_data,
		},
	)


@login_required
def board_view(request: HttpRequest) -> HttpResponse:
	"""Board view: schools as rows, categories as columns, for a single round."""

	# --- Permission / school resolution (mirrors overview) ---
	selected_phase = (request.GET.get("phase") or "").strip().upper()
	valid_phases = {choice[0] for choice in School.Phase.choices}
	if selected_phase not in valid_phases:
		selected_phase = ""
	phase_options = [("", "All phases")] + list(School.Phase.choices)

	if request.user.is_superuser:
		schools = list(School.objects.order_by("name").all())
	else:
		_, schools, error = _get_allowed_schools(request)
		if error is not None:
			return error

	if selected_phase:
		schools = [s for s in schools if s.phase == selected_phase]

	if not schools:
		messages.error(request, "No schools are available.")
		return redirect("home")

	# --- Period resolution ---
	year, selected_year_value, academic_year_options = _academic_year_context(
		request, include_post=False
	)

	try:
		selected_round = int(request.GET.get("round") or 1)
	except (TypeError, ValueError):
		selected_round = 1
	if selected_round not in (1, 2, 3):
		selected_round = 1

	round_options = [{"value": r, "label": f"{TERM_LABELS[r]} term"} for r in (1, 2, 3)]

	current_period = ReviewPeriod.objects.filter(year=year, round=selected_round).first()

	# Determine the previous period for trend comparison.
	# Autumn's predecessor is Summer of the prior academic year.
	if selected_round == 1:
		prev_period = ReviewPeriod.objects.filter(year=year - 1, round=3).first()
	else:
		prev_period = ReviewPeriod.objects.filter(year=year, round=selected_round - 1).first()

	# --- Bulk-fetch evaluations (2 queries total) ---
	school_ids = [s.id for s in schools]
	categories = list(Category.objects.filter(is_active=True).order_by("order", "name"))

	SHORT_LABELS = {
		1: "Exceptional",
		2: "Strong",
		3: "Expected",
		4: "Needs Attention",
		5: "Urgent",
	}

	current_evals: dict[tuple[int, int], int] = {}
	if current_period:
		for e in Evaluation.objects.filter(
			period=current_period,
			school_id__in=school_ids,
			rating__isnull=False,
		).values("school_id", "category_id", "rating"):
			current_evals[(e["school_id"], e["category_id"])] = e["rating"]

	prev_evals: dict[tuple[int, int], int] = {}
	if prev_period:
		for e in Evaluation.objects.filter(
			period=prev_period,
			school_id__in=school_ids,
			rating__isnull=False,
		).values("school_id", "category_id", "rating"):
			prev_evals[(e["school_id"], e["category_id"])] = e["rating"]

	# --- Build the row/cell matrix ---
	rows = []
	for school in schools:
		cells = []
		for category in categories:
			key = (school.id, category.id)
			band = current_evals.get(key)
			prev_band = prev_evals.get(key)

			# Lower band = better (1=Exceptional, 5=Urgent Improvement).
			if band is not None and prev_band is not None:
				if band < prev_band:
					trend = "up"
				elif band > prev_band:
					trend = "down"
				else:
					trend = "same"
			else:
				trend = None

			cells.append({
				"band": band,
				"label": SHORT_LABELS.get(band, "") if band else "",
				"trend": trend,
			})
		rows.append({"school": school, "cells": cells})

	has_any_data = any(cell["band"] is not None for row in rows for cell in row["cells"])

	# Risk exception report — Red only under the agreed starting rule. Sits on
	# this page rather than a separate one, and is built to screenshot cleanly:
	# the Committee and Trust Board see it as an image in a board pack.
	escalated_risks = _escalated_risk_rows(
		schools, year=year, round_number=selected_round
	)

	# Operations & Resources roll-up, with each school's pilot scope shown.
	operations_rows = _operations_summary_rows(
		schools, year=year, round_number=selected_round
	)

	return render(
		request,
		"review/board.html",
		{
			"schools": schools,
			"escalated_risks": escalated_risks,
			"operations_rows": operations_rows,
			"operations_summary": _operations_executive_summary(operations_rows),
			"operations_small_print": OPS_SMALL_PRINT,
			"categories": categories,
			"rows": rows,
			"year": year,
			"selected_year_value": selected_year_value,
			"selected_round": selected_round,
			"round_options": round_options,
			"academic_year_options": academic_year_options,
			"phase_options": phase_options,
			"selected_phase": selected_phase,
			"current_period": current_period,
			"has_any_data": has_any_data,
		},
	)


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)
	if request.method == "POST" and not can_edit:
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:dashboard",
			[
				("school", school_id or ""),
				("year", request.POST.get("year") or ""),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)

	# For viewers, avoid creating ReviewPeriods as a side-effect of viewing.
	if can_edit:
		periods = {
			r: ReviewPeriod.objects.get_or_create(year=selected_year, round=r)[0]
			for r in (1, 2, 3)
		}
	else:
		periods = {
			r: ReviewPeriod.objects.filter(year=selected_year, round=r).first()
			for r in (1, 2, 3)
		}

	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	category_ids = {c.id for c in categories}
	safeguarding_category_ids = {c.id for c in categories if (c.name or "").strip().lower() == "safeguarding"}

	period_list = [p for p in periods.values() if p is not None]
	existing_qs = Evaluation.objects.filter(school=school, category__in=categories)
	if period_list:
		existing_qs = existing_qs.filter(period__in=period_list)
	else:
		existing_qs = existing_qs.none()

	existing = {(e.category_id, e.period.round): e for e in existing_qs}

	DashboardFormSet = formset_factory(DashboardRatingForm, extra=0)

	if request.method == "POST":
		formset = DashboardFormSet(request.POST)
		_apply_category_specific_rating_choices(
			forms=formset.forms,
			safeguarding_category_ids=safeguarding_category_ids,
		)
		if formset.is_valid():
			with transaction.atomic():
				for form in formset:
					category_id = form.cleaned_data["category_id"]
					round_value = form.cleaned_data["round"]
					if category_id not in category_ids:
						continue
					if round_value not in (1, 2, 3):
						continue
					rating = form.cleaned_data["rating"]

					Evaluation.objects.update_or_create(
						school=school,
						period=periods[round_value],
						category_id=category_id,
						defaults={
							"rating": rating,
							"updated_by": request.user,
						},
					)

			messages.success(request, "Dashboard ratings saved.")
			params = f"?year={selected_year_value}"
			if request.user.is_superuser:
				params = f"?school={school.id}&year={selected_year_value}"
			return redirect(f"{reverse('review:dashboard')}{params}")
	else:
		initial = []
		for category in categories:
			for round_value in (1, 2, 3):
				current = existing.get((category.id, round_value))
				initial.append(
					{
						"category_id": category.id,
						"round": round_value,
						"rating": current.rating if current else None,
					}
				)
		formset = DashboardFormSet(initial=initial)
		_apply_category_specific_rating_choices(
			forms=formset.forms,
			safeguarding_category_ids=safeguarding_category_ids,
		)

	if not can_edit:
		for form in formset.forms:
			for field in form.fields.values():
				field.disabled = True

	# Build a 2D structure (category -> three forms)
	forms_iter = iter(formset.forms)
	rows = []
	for category in categories:
		cells = [next(forms_iter) for _ in (1, 2, 3)]
		rows.append({"category": category, "cells": cells})

	return render(
		request,
		"review/dashboard.html",
		{
			"school": school,
			"schools": schools,
			"selected_year_value": selected_year_value,
			"academic_year_options": academic_year_options,
			"rows": rows,
			"formset": formset,
			"can_edit": can_edit,
		},
	)


def _indepth_grade_for_categories(school, year, categories):
	"""Map each category to the grade its in-depth review concluded (if any).

	The link between a dashboard category and an in-depth area is by name
	(e.g. category 'Achievement' ↔ area 'Achievement'). Returns
	{category_id: {grade_key, grade_label, rating}} only for categories whose
	matching review has reached a conclusion.
	"""
	reviews = {
		(r.area.name or "").strip().lower(): r
		for r in InDepthReview.objects.filter(school=school, year=year).select_related("area")
	}
	out = {}
	for category in categories:
		review = reviews.get((category.name or "").strip().lower())
		if not (review and review.overall_grade):
			continue
		rating = GRADE_TO_RATING.get(review.overall_grade)
		if rating is None:
			continue
		out[category.id] = {
			"grade_key": review.overall_grade,
			"grade_label": _GRADE_LABELS.get(review.overall_grade, ""),
			"rating": rating,
		}
	return out


@login_required
def evaluation(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)
	if request.method == "POST" and not can_edit:
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:evaluation",
			[
				("year", request.POST.get("year") or ""),
				("round", request.POST.get("round") or ""),
				("school", school_id or ""),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	# Period selection (academic year start + round)
	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)

	try:
		selected_round = int(request.GET.get("round") or request.POST.get("round") or 1)
	except (TypeError, ValueError):
		selected_round = 1
	if selected_round not in (1, 2, 3):
		selected_round = 1

	period_db = None
	if can_edit:
		period_db, _ = ReviewPeriod.objects.get_or_create(year=selected_year, round=selected_round)
		period = period_db
	else:
		period_db = ReviewPeriod.objects.filter(year=selected_year, round=selected_round).first()
		period = period_db or ReviewPeriod(year=selected_year, round=selected_round)

	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	category_ids = {c.id for c in categories}
	safeguarding_category_ids = {c.id for c in categories if (c.name or "").strip().lower() == "safeguarding"}

	if period_db is None:
		existing = {}
	else:
		existing = {
			e.category_id: e
			for e in Evaluation.objects.filter(school=school, period=period_db, category__in=categories)
		}

	# Grade each category's in-depth review concluded, for the over-write feature.
	indepth_grades = _indepth_grade_for_categories(school, selected_year, categories)

	# Over-write action: set an area's evaluation grade to the grade its in-depth
	# review concluded. Gated by can_edit (non-editors are bounced at the top).
	if request.method == "POST" and request.POST.get("action") == "override_grade":
		try:
			cat_id = int(request.POST.get("category_id") or 0)
		except (TypeError, ValueError):
			cat_id = 0
		info = indepth_grades.get(cat_id)
		if info is not None and period_db is not None and cat_id in category_ids:
			existing_ev = existing.get(cat_id)
			prior_rating = existing_ev.rating if existing_ev else None
			Evaluation.objects.update_or_create(
				school=school,
				period=period_db,
				category_id=cat_id,
				defaults={
					"rating": info["rating"],
					"system_rating": prior_rating,
					"rating_overridden": True,
					"overridden_by": request.user,
					"overridden_at": timezone.now(),
					"override_reason": (request.POST.get("reason") or "").strip(),
					"updated_by": request.user,
				},
			)
			messages.success(
				request,
				f"Grade over-written to the in-depth review grade ({info['grade_label']}).",
			)
		else:
			messages.error(request, "Could not over-write that grade.")
		params = f"?year={selected_year_value}&round={period.round}"
		if request.user.is_superuser:
			params = f"?school={school.id}&year={selected_year_value}&round={period.round}"
		return redirect(f"{reverse('review:evaluation')}{params}")

	EvaluationFormSet = formset_factory(EvaluationEntryForm, extra=0)

	if request.method == "POST":
		formset = EvaluationFormSet(request.POST)
		_apply_category_specific_rating_choices(
			forms=formset.forms,
			safeguarding_category_ids=safeguarding_category_ids,
		)
		if formset.is_valid():
			with transaction.atomic():
				for form in formset:
					category_id = form.cleaned_data["category_id"]
					if category_id not in category_ids:
						continue
					rating = form.cleaned_data["rating"]
					judgement_evidence = form.cleaned_data["judgement_evidence"]
					to_progress = form.cleaned_data["to_progress"]

					Evaluation.objects.update_or_create(
						school=school,
						period=period,
						category_id=category_id,
						defaults={
							"rating": rating,
							"judgement_evidence": judgement_evidence,
							"to_progress": to_progress,
							"updated_by": request.user,
						},
					)

			messages.success(request, "Evaluation saved.")
			params = f"?year={selected_year_value}&round={period.round}"
			if request.user.is_superuser:
				params = f"?school={school.id}&year={selected_year_value}&round={period.round}"
			return redirect(f"{reverse('review:evaluation')}{params}")
	else:
		initial = []
		for category in categories:
			current = existing.get(category.id)
			initial.append(
				{
					"category_id": category.id,
					"rating": current.rating if current else None,
					"judgement_evidence": current.judgement_evidence if current else "",
					"to_progress": current.to_progress if current else "",
				}
			)
		formset = EvaluationFormSet(initial=initial)
		_apply_category_specific_rating_choices(
			forms=formset.forms,
			safeguarding_category_ids=safeguarding_category_ids,
		)

	if not can_edit:
		for form in formset.forms:
			for field in form.fields.values():
				field.disabled = True

	rows = []
	for category, form in zip(categories, formset.forms):
		rows.append({"category": category, "form": form})

	# Areas whose in-depth review concluded a grade that differs from the current
	# evaluation rating — these are offered for over-write.
	override_rows = []
	for category in categories:
		info = indepth_grades.get(category.id)
		if not info:
			continue
		existing_ev = existing.get(category.id)
		current_rating = existing_ev.rating if existing_ev else None
		if current_rating != info["rating"]:
			override_rows.append({
				"category": category,
				"grade_label": info["grade_label"],
				"indepth_rating": info["rating"],
				"current_rating": current_rating,
			})

	return render(
		request,
		"review/evaluation.html",
		{
			"school": school,
			"schools": schools,
			"period": period,
			"selected_year_value": selected_year_value,
			"academic_year_options": academic_year_options,
			"rows": rows,
			"formset": formset,
			"can_edit": can_edit,
			"override_rows": override_rows,
		},
	)


_GRADE_LABELS = {
	"not_met": "Not Met",
	"met": "Met",
	"urgent_improvement": "Urgent Improvement",
	"needs_attention": "Needs Attention",
	"expected_standard": "Expected Standard",
	"strong_standard": "Strong Standard",
	"exceptional": "Exceptional",
}

_GRADE_CSS = {
	"not_met": "not_met",
	"urgent_improvement": "urgent_improvement",
	"needs_attention": "needs_attention",
	"expected_standard": "expected_standard",
	"strong_standard": "strong_standard",
	"exceptional": "exceptional",
	"met": "met",
}

# Maps an in-depth-review grade key to the 1–5 evaluation rating scale
# (1 = best). See RATING_CHOICES_DEFAULT / RATING_CHOICES_SAFEGUARDING in
# forms.py — this is the inverse, used when over-writing a dashboard grade with
# the grade an in-depth review concluded.
GRADE_TO_RATING = {
	"exceptional": 1,
	"strong_standard": 2,
	"expected_standard": 3,
	"needs_attention": 4,
	"urgent_improvement": 5,
	"met": 1,
	"not_met": 5,
}

# RAG-able rungs, in DOM/reveal order. The ladder starts on Expected; the
# up-path climbs Expected -> Strong -> Exceptional. Any red at Expected
# concludes Needs Attention (an outcome label, never RAGed).
_RICH_KEYS_DEFAULT = [
	"expected_standard",
	"strong_standard",
	"exceptional",
]
_RICH_KEYS_SAFEGUARDING = ["met"]

# When writing commentary a school only documents the band its grade landed on,
# not every rung it RAGed to climb there (to reach Strong you RAG Expected all
# green first, but only Strong needs a write-up). Map each awarded grade to the
# rung whose statements need commentary. Failing/down-path outcomes point at the
# rung that was evaluated to reach them.
_GRADE_TO_COMMENTARY_RUNG = {
	"expected_standard": "expected_standard",
	"strong_standard": "strong_standard",
	"exceptional": "exceptional",
	# Needs Attention writes up the Expected Standard statements (with their RAG),
	# so leaders explain why each is red/amber.
	"needs_attention": "expected_standard",
	"met": "met",
	"not_met": "met",
}


def _rung_state(rags) -> str:
	"""Classify a rung's RAG values.

	'absent'     — the rung has no rateable statements at all
	'incomplete' — at least one statement is un-rated
	'has_red' / 'has_amber' / 'all_green' — fully rated, by worst rating present
	"""
	if rags is None:
		return "absent"
	if not rags or any(r == "" for r in rags):
		return "incomplete"
	if any(r == "red" for r in rags):
		return "has_red"
	if any(r == "amber" for r in rags):
		return "has_amber"
	return "all_green"


def conclude_indepth_grade(rags_by_key, *, is_safeguarding: bool = False) -> str:
	"""Derive the self-evaluation grade from the RAG ladder.

	`rags_by_key` maps a standard key to the list of RAG values for that rung's
	rateable statements (use "" for un-rated; omit the key entirely when the
	rung has no statements). Returns a grade key, or "" when the ladder has not
	yet reached a conclusion (a required rung is still incomplete).
	"""
	if is_safeguarding:
		met = rags_by_key.get("met")
		if _rung_state(met) in ("absent", "incomplete"):
			return ""
		return "not_met" if any(r == "red" for r in met) else "met"

	expected = _rung_state(rags_by_key.get("expected_standard"))
	if expected in ("absent", "incomplete"):
		return ""

	if expected == "has_red":
		# Any red at Expected Standard concludes Needs Attention. (Urgent
		# Improvement is no longer an auto-concluded grade.)
		return "needs_attention"

	if expected == "has_amber":
		return "expected_standard"

	# All green at Expected — climb to Strong.
	strong = _rung_state(rags_by_key.get("strong_standard"))
	if strong == "absent":
		return "expected_standard"
	if strong == "incomplete":
		return ""
	if strong == "has_red":
		return "expected_standard"
	if strong == "has_amber":
		return "strong_standard"

	# All green at Strong — climb to Exceptional.
	exc_list = rags_by_key.get("exceptional")
	exc = _rung_state(exc_list)
	if exc == "absent":
		return "strong_standard"
	if exc == "incomplete":
		return ""
	return "strong_standard" if exc == "has_red" else "exceptional"


@login_required
def indepth_review(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)

	# Two pages share this view: 'rag' (the ladder that concludes the grade) and
	# 'commentary' (the per-statement write-up). Default to the ladder.
	page = (request.GET.get("page") or request.POST.get("page") or "rag").strip()
	if page not in ("rag", "commentary"):
		page = "rag"

	if request.method == "POST" and not can_edit:
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:indepth_review",
			[
				("year", request.POST.get("year") or ""),
				("area", request.POST.get("area_id") or ""),
				("school", school_id or ""),
				("page", page),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)

	# Only areas with the new criteria loaded are part of the active flow; the
	# legacy subsection-only areas are intentionally left out of the dropdown.
	areas = list(
		InDepthArea.objects.filter(standards__isnull=False).distinct().order_by("order", "name")
	)
	area = None
	selected_area = request.GET.get("area") or request.POST.get("area_id")
	if selected_area:
		area = next((a for a in areas if str(a.id) == str(selected_area)), None)
	if area is None and areas:
		area = areas[0]

	if not areas or area is None:
		messages.error(
			request,
			"No in-depth review criteria have been loaded yet. "
			"Run the load_indepth_criteria management command.",
		)
		return render(
			request,
			"review/indepth_review.html",
			{
				"school": school,
				"schools": schools,
				"areas": areas,
				"area": area,
				"selected_year_value": selected_year_value,
				"academic_year_options": academic_year_options,
				"review": None,
				"rich_blocks": [],
				"formset": None,
				"can_edit": can_edit,
				"is_safeguarding": False,
				"page": page,
				"overall_grade": "",
				"overall_grade_label": "",
				"overall_grade_css": "",
			},
		)

	is_safeguarding = area.is_safeguarding
	rich_keys = _RICH_KEYS_SAFEGUARDING if is_safeguarding else _RICH_KEYS_DEFAULT

	standards = {
		s.key: s
		for s in InDepthStandard.objects.filter(area=area).prefetch_related("judgement_areas")
	}

	# RAG-able rungs in DOM/reveal order, each with its rateable judgement areas.
	rich_standards = [standards[k] for k in rich_keys if k in standards]
	rung_jas = []  # [(standard, [ja, ...]), ...] — only rungs that have statements
	ja_ids = set()
	for s in rich_standards:
		jas = [ja for ja in s.judgement_areas.all() if not ja.is_flat]
		if not jas:
			continue
		rung_jas.append((s, jas))
		ja_ids.update(ja.id for ja in jas)
	all_jas = [ja for _s, jas in rung_jas for ja in jas]

	review = InDepthReview.objects.filter(school=school, year=selected_year, area=area).first()
	existing = {} if review is None else {
		r.judgement_area_id: r
		for r in InDepthResponse.objects.filter(review=review, judgement_area__isnull=False)
	}

	def _build_params(target_page: str) -> str:
		base = f"?school={school.id}&" if request.user.is_superuser else "?"
		return f"{base}year={selected_year_value}&area={area.id}&page={target_page}"

	def _rags_by_key(resp_map) -> dict:
		"""Per-rung RAG lists ("" for un-rated) for grade computation."""
		out = {}
		for s, jas in rung_jas:
			out[s.key] = [
				(resp_map[ja.id].rag if ja.id in resp_map and resp_map[ja.id].rag else "")
				for ja in jas
			]
		return out

	# The commentary page only asks for write-ups on the band the grade landed
	# on: the RAGed statements belonging to the awarded grade's rung. (Earlier
	# rungs were RAGed to reach that grade but don't need their own commentary.)
	na_bullets = []
	na_comment = ""
	if page == "commentary":
		rated = [ja for ja in all_jas if ja.id in existing and existing[ja.id].rag]
		ja_rung_key = {ja.id: s.key for s, jas in rung_jas for ja in jas}
		band_key = _GRADE_TO_COMMENTARY_RUNG.get(review.overall_grade if review else "")
		if band_key:
			band_jas = [ja for ja in rated if ja_rung_key.get(ja.id) == band_key]
			# Fall back to every rated statement if the band has none, so the page
			# is never inexplicably blank.
			page_jas = band_jas or rated
		else:
			page_jas = rated
		# On a Needs Attention grade, offer the flat Needs Attention statements as
		# a prompt: "in addition, does one or more of the following apply?".
		if review and review.overall_grade == "needs_attention":
			na_bullets = list(
				InDepthJudgementArea.objects.filter(
					standard__area=area,
					standard__key="needs_attention",
					is_flat=True,
				).order_by("order")
			)
			na_comment = review.needs_attention_comment
	else:
		page_jas = all_jas

	FormSetClass = formset_factory(InDepthJudgementAreaForm, extra=0)
	formset = None

	# ── POST handler ────────────────────────────────────────────────────────────
	if request.method == "POST" and can_edit:
		formset = FormSetClass(request.POST)
		if formset.is_valid():
			with transaction.atomic():
				if review is None:
					review = InDepthReview.objects.create(
						school=school, year=selected_year, area=area, updated_by=request.user,
					)
				for f in formset:
					ja_id = f.cleaned_data.get("judgement_area_id")
					if ja_id not in ja_ids:
						continue
					resp = InDepthResponse.objects.filter(
						review=review, judgement_area_id=ja_id
					).first()
					if page == "commentary":
						# Only touch the write-up fields; leave the RAG intact.
						commentary = f.cleaned_data["commentary"]
						next_steps = f.cleaned_data["next_steps"]
						if resp:
							resp.evidence_text = commentary
							resp.next_steps = next_steps
							if not (resp.rag or commentary or next_steps):
								resp.delete()
							else:
								resp.save()
						elif commentary or next_steps:
							InDepthResponse.objects.create(
								review=review, judgement_area_id=ja_id,
								evidence_text=commentary, next_steps=next_steps,
							)
					else:
						# RAG page — only touch the rating. A blank rating means the
						# statement is not (or no longer) rated; drop the whole
						# response so no orphaned commentary lingers on an abandoned
						# branch (page 2 only ever shows rated statements).
						rag = f.cleaned_data["rag"]
						if rag:
							if resp:
								resp.rag = rag
								resp.save()
							else:
								InDepthResponse.objects.create(
									review=review, judgement_area_id=ja_id, rag=rag,
								)
						elif resp:
							resp.delete()

				# The "one or more of the following applies" comment is only
				# rendered (and therefore posted) on a Needs Attention commentary
				# page; persist it when present.
				if page == "commentary" and "needs_attention_comment" in request.POST:
					review.needs_attention_comment = (
						request.POST.get("needs_attention_comment") or ""
					)

				# Recompute and store the grade from the now-saved RAG state.
				refreshed = {
					r.judgement_area_id: r
					for r in InDepthResponse.objects.filter(
						review=review, judgement_area__isnull=False
					)
				}
				review.overall_grade = conclude_indepth_grade(
					_rags_by_key(refreshed), is_safeguarding=is_safeguarding
				)
				review.step = "review"
				review.updated_by = request.user
				review.save()
			messages.success(request, "In-depth review saved.")
			# 'Save & continue' takes the user from the ladder to the write-up.
			target = "commentary" if (page == "rag" and request.POST.get("save_continue")) else page
			return redirect(f"{reverse('review:indepth_review')}{_build_params(target)}")

	# ── Build formset for GET (or re-render after an invalid POST) ───────────────
	if formset is None:
		initial = [
			{
				"judgement_area_id": ja.id,
				"rag": existing[ja.id].rag if ja.id in existing else "",
				"commentary": existing[ja.id].evidence_text if ja.id in existing else "",
				"next_steps": existing[ja.id].next_steps if ja.id in existing else "",
			}
			for ja in page_jas
		]
		formset = FormSetClass(initial=initial)

	if not can_edit:
		for f in formset.forms:
			for field in f.fields.values():
				field.disabled = True

	# Map each rendered form to its judgement area by id, so rendering stays
	# correct whether the formset came from initial data or a (possibly partial)
	# POST re-render.
	form_by_ja = {}
	for f in formset.forms:
		raw = f["judgement_area_id"].value()
		try:
			form_by_ja[int(raw)] = f
		except (TypeError, ValueError):
			continue

	# Group forms under their rung for rendering.
	rich_blocks = []
	for s, jas in rung_jas:
		rows = []
		for ja in jas:
			if ja.id not in form_by_ja:
				continue
			resp = existing.get(ja.id)
			rows.append({
				"ja": ja,
				"form": form_by_ja[ja.id],
				"current_rag": resp.rag if resp else "",
			})
		if not rows:
			continue
		rich_blocks.append({
			"standard": s,
			"key": s.key,
			"label": s.get_key_display(),
			"focus": s.focus,
			"rows": rows,
		})

	overall_grade = review.overall_grade if review else ""
	template = (
		"review/indepth_review_commentary.html"
		if page == "commentary"
		else "review/indepth_review.html"
	)

	return render(
		request,
		template,
		{
			"school": school,
			"schools": schools,
			"areas": areas,
			"area": area,
			"selected_year_value": selected_year_value,
			"academic_year_options": academic_year_options,
			"review": review,
			"rich_blocks": rich_blocks,
			"formset": formset,
			"can_edit": can_edit,
			"is_safeguarding": is_safeguarding,
			"page": page,
			"overall_grade": overall_grade,
			"overall_grade_label": _GRADE_LABELS.get(overall_grade, ""),
			"overall_grade_css": _GRADE_CSS.get(overall_grade, ""),
			"na_bullets": na_bullets,
			"na_comment": na_comment,
		},
	)


@login_required
def reflection(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)

	if request.method == "POST" and not can_edit:
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:reflection",
			[
				("year", request.POST.get("year") or ""),
				("school", school_id or ""),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)

	# Mirror the in-depth review screen: only the standards-backed (new) areas.
	areas = list(
		InDepthArea.objects.filter(standards__isnull=False).distinct().order_by("order", "name")
	)

	# Build a map of area_id -> InDepthReview for the selected school/year
	reviews_qs = InDepthReview.objects.filter(
		school=school, year=selected_year,
	) if school else InDepthReview.objects.none()
	reviews_by_area = {r.area_id: r for r in reviews_qs}

	if request.method == "POST" and can_edit:
		with transaction.atomic():
			for area in areas:
				field_name = f"area_{area.id}"
				text = request.POST.get(field_name, "").strip()
				review = reviews_by_area.get(area.id)
				if review is None:
					if text:
						review = InDepthReview.objects.create(
							school=school, year=selected_year, area=area, updated_by=request.user,
						)
						review.qa_reflection = text
						review.updated_by = request.user
						review.save()
						reviews_by_area[area.id] = review
				else:
					review.qa_reflection = text
					review.updated_by = request.user
					review.save()
		messages.success(request, "Reflections saved.")
		if request.user.is_superuser:
			params = f"?school={school.id}&year={selected_year_value}"
		else:
			params = f"?year={selected_year_value}"
		return redirect(f"{reverse('review:reflection')}{params}")

	# Build per-area context items
	area_items = []
	for area in areas:
		review = reviews_by_area.get(area.id)
		area_items.append({
			"area": area,
			"field_name": f"area_{area.id}",
			"value": review.qa_reflection if review else "",
		})

	return render(
		request,
		"review/reflection.html",
		{
			"school": school,
			"schools": schools,
			"area_items": area_items,
			"selected_year_value": selected_year_value,
			"academic_year_options": academic_year_options,
			"can_edit": can_edit,
		},
	)

# -- Risk register -------------------------------------------------------------

TERM_OPTIONS = [{"value": r, "label": f"{TERM_LABELS[r]} term"} for r in (1, 2, 3)]

# "Show me everything at least this severe" — how the Central Team cuts the
# register into each audience's slice without reformatting a report by hand.
RAG_FILTER_OPTIONS = [
	{"value": "all", "label": "All risks", "min_severity": -1},
	{"value": "yellow", "label": "Yellow and above", "min_severity": SEVERITY["Yellow"]},
	{"value": "amber", "label": "Amber and above", "min_severity": SEVERITY["Amber"]},
	{"value": "red", "label": "Red only", "min_severity": SEVERITY["Red"]},
]


def _period_sort_key(period) -> tuple[int, int]:
	return (period.year, period.round)


def _resolve_term(request: HttpRequest, *, include_post: bool = True) -> int:
	raw = request.GET.get("round")
	if include_post:
		raw = raw or request.POST.get("round")
	try:
		selected = int(raw or 1)
	except (TypeError, ValueError):
		selected = 1
	return selected if selected in (1, 2, 3) else 1


def _resolve_rag_filter(request: HttpRequest) -> tuple[str, int]:
	raw = (request.GET.get("rag") or "all").strip().lower()
	for option in RAG_FILTER_OPTIONS:
		if option["value"] == raw:
			return option["value"], option["min_severity"]
	return "all", -1


def _build_risk_rows(risks, *, year: int, round_number: int, settings) -> list[dict]:
	"""Turn risks into display rows: this term's rating, last term's, and trend.

	"Last term's" is the most recent rating strictly before the selected period,
	not merely the adjacent one, so a term with no entry does not break the
	comparison.
	"""
	current_key = (year, round_number)
	rows = []
	for risk in risks:
		ratings = sorted(risk.ratings.all(), key=lambda r: _period_sort_key(r.period))
		current = next(
			(r for r in ratings if _period_sort_key(r.period) == current_key), None
		)
		previous = None
		for rating in ratings:
			if _period_sort_key(rating.period) < current_key:
				previous = rating

		current_band = current.band if current else None
		trend = trend_for(current_band, previous.band if previous else None)
		escalated = is_escalated(current_band, trend, settings)

		rows.append({
			"risk": risk,
			"category": risk.category,
			"route": risk.route,
			"current": current,
			"previous": previous,
			"latest": current or previous,
			"band": current_band,
			"rag": current.rag if current else "",
			"rag_css": RAG_CSS.get(current.rag, "") if current else "",
			"band_label": BAND_LABELS.get(current_band, "") if current_band else "",
			"trend": trend,
			"trend_label": TREND_LABELS.get(trend, ""),
			"escalated": escalated,
			"severity": SEVERITY.get(current.rag, -1) if current else -1,
			"awaiting_qa": bool(current and current.awaiting_qa),
			"close_awaiting_qa": risk.close_awaiting_qa,
		})
	return rows


def _school_risk_queryset(school):
	return (
		Risk.objects.filter(school=school)
		.select_related("category", "category__indepth_area", "closed_by", "close_qa_by")
		.prefetch_related("ratings__period", "ratings__qa_by")
	)


def _escalated_risk_rows(schools, *, year: int, round_number: int) -> list[dict]:
	"""Rows for the Trust Dashboard exception report — escalating risks only.

	Red only under the agreed starting rule; RiskSettings can widen it without a
	code change.
	"""
	settings = RiskSettings.load()
	risks = (
		Risk.objects.filter(school__in=schools, status=Risk.Status.OPEN)
		.select_related("school", "category", "category__indepth_area")
		.prefetch_related("ratings__period")
	)
	rows = _build_risk_rows(risks, year=year, round_number=round_number, settings=settings)
	escalating = [row for row in rows if row["escalated"]]
	escalating.sort(key=lambda row: (-row["severity"], row["risk"].school.name))
	return escalating


@login_required
def risk_register(request: HttpRequest) -> HttpResponse:
	"""A school's risk register: review what is already open, then add what is new."""
	can_edit = user_can_edit(request.user)
	can_qa = user_can_qa_risk(request.user)

	if request.method == "POST" and not (can_edit or can_qa):
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:risk_register",
			[
				("year", request.POST.get("year") or ""),
				("round", request.POST.get("round") or ""),
				("school", school_id or ""),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)
	selected_round = _resolve_term(request)

	if can_edit or can_qa:
		period_db, _ = ReviewPeriod.objects.get_or_create(
			year=selected_year, round=selected_round
		)
		period = period_db
	else:
		period_db = ReviewPeriod.objects.filter(
			year=selected_year, round=selected_round
		).first()
		period = period_db or ReviewPeriod(year=selected_year, round=selected_round)

	categories = TrustCategory.objects.select_related("indepth_area").all()

	redirect_params = [
		("year", selected_year_value),
		("round", str(selected_round)),
		("rag", request.POST.get("rag") or request.GET.get("rag") or ""),
	]
	if request.user.is_superuser:
		redirect_params.insert(0, ("school", str(school.id)))

	def _back():
		query = "&".join(f"{k}={v}" for k, v in redirect_params if v)
		return redirect(f"{reverse('review:risk_register')}{'?' + query if query else ''}")

	entry_form = RiskEntryForm(categories=categories)
	close_forms: dict[int, RiskCloseForm] = {}
	action = request.POST.get("action") if request.method == "POST" else None

	if action == "add_risk" and can_edit and period_db is not None:
		entry_form = RiskEntryForm(request.POST, categories=categories)
		if entry_form.is_valid():
			data = entry_form.cleaned_data
			with transaction.atomic():
				risk = Risk.objects.create(
					school=school,
					category=data["category"],
					title=data["title"],
					mitigation=data["mitigation"],
					owner=data["owner"],
					review_point=data["review_point"],
					opened_period=period_db,
					created_by=request.user,
				)
				RiskRating.objects.create(
					risk=risk,
					period=period_db,
					impact=data["impact"],
					likelihood=data["likelihood"],
					recorded_by=request.user,
				)
			messages.success(request, "Risk added to the register.")
			return _back()

	elif action == "save_ratings" and can_edit and period_db is not None:
		RatingFormSet = formset_factory(RiskRatingForm, extra=0)
		posted = RatingFormSet(request.POST, prefix="ratings")
		allowed_ids = set(
			Risk.objects.filter(school=school, status=Risk.Status.OPEN).values_list(
				"id", flat=True
			)
		)
		if posted.is_valid():
			with transaction.atomic():
				for form in posted:
					risk_id = form.cleaned_data.get("risk_id")
					if risk_id not in allowed_ids:
						continue
					impact = form.cleaned_data.get("impact")
					likelihood = form.cleaned_data.get("likelihood")
					if not impact or not likelihood:
						continue
					rating, created = RiskRating.objects.get_or_create(
						risk_id=risk_id,
						period=period_db,
						defaults={
							"impact": impact,
							"likelihood": likelihood,
							"recorded_by": request.user,
						},
					)
					changed = (
						created
						or rating.impact != impact
						or rating.likelihood != likelihood
					)
					rating.impact = impact
					rating.likelihood = likelihood
					rating.note = form.cleaned_data.get("note") or ""
					rating.recorded_by = request.user
					if changed:
						# A changed rating has to be signed off again.
						rating.qa_by = None
						rating.qa_at = None
					rating.save()
			messages.success(request, "Risk ratings saved.")
			return _back()
		messages.error(request, "Set both impact and likelihood, or neither.")

	elif action == "close_risk" and can_edit:
		close_form = RiskCloseForm(request.POST)
		if close_form.is_valid():
			risk = Risk.objects.filter(
				id=close_form.cleaned_data["risk_id"], school=school
			).first()
			if risk is not None:
				risk.status = Risk.Status.CLOSED
				risk.closed_at = timezone.now()
				risk.closed_by = request.user
				risk.close_reason = close_form.cleaned_data["close_reason"]
				risk.close_qa_by = None
				risk.close_qa_at = None
				risk.save()
				messages.success(
					request,
					"Risk closed. It stays on the register and now awaits CFO sign-off.",
				)
			return _back()
		try:
			close_forms[int(close_form.data.get("risk_id"))] = close_form
		except (TypeError, ValueError):
			pass
		messages.error(request, "Give a reason before closing this risk.")

	elif action in ("qa_rating", "qa_close") and can_qa:
		_apply_risk_qa(request, action, allowed_schools=School.objects.filter(id=school.id))
		return _back()

	settings = RiskSettings.load()
	rows = _build_risk_rows(
		_school_risk_queryset(school),
		year=selected_year,
		round_number=selected_round,
		settings=settings,
	)

	rag_filter, min_severity = _resolve_rag_filter(request)
	if min_severity >= 0:
		rows = [row for row in rows if row["severity"] >= min_severity]

	# Closed risks stay visible, greyed out — never deleted, never filtered away
	# by default.
	open_rows = [row for row in rows if not row["risk"].is_closed]
	closed_rows = [row for row in rows if row["risk"].is_closed]
	open_rows.sort(key=lambda row: (-row["severity"], row["risk"].title))
	closed_rows.sort(key=lambda row: row["risk"].closed_at or timezone.now(), reverse=True)

	RatingFormSet = formset_factory(RiskRatingForm, extra=0)
	rating_formset = RatingFormSet(
		prefix="ratings",
		initial=[
			{
				"risk_id": row["risk"].id,
				"impact": row["current"].impact if row["current"] else "",
				"likelihood": row["current"].likelihood if row["current"] else "",
				"note": row["current"].note if row["current"] else "",
			}
			for row in open_rows
		],
	)
	for row, form in zip(open_rows, rating_formset.forms):
		if not can_edit:
			for field in form.fields.values():
				field.disabled = True
		row["rating_form"] = form
		row["close_form"] = close_forms.get(row["risk"].id) or RiskCloseForm(
			initial={"risk_id": row["risk"].id}
		)

	awaiting_qa_count = sum(
		1 for row in open_rows + closed_rows if row["awaiting_qa"] or row["close_awaiting_qa"]
	)

	return render(
		request,
		"review/risk.html",
		{
			"school": school,
			"schools": schools,
			"period": period,
			"selected_year_value": selected_year_value,
			"selected_round": selected_round,
			"round_options": TERM_OPTIONS,
			"academic_year_options": academic_year_options,
			"matrix_rows": matrix_rows(),
			"rag_legend": RAG_LEGEND,
			"matrix_lookup_json": json.dumps(matrix_lookup()),
			"open_rows": open_rows,
			"closed_rows": closed_rows,
			"rating_formset": rating_formset,
			"entry_form": entry_form,
			"rag_filter": rag_filter,
			"rag_filter_options": RAG_FILTER_OPTIONS,
			"can_edit": can_edit,
			"can_qa": can_qa,
			"awaiting_qa_count": awaiting_qa_count,
		},
	)


def _apply_risk_qa(request: HttpRequest, action: str, *, allowed_schools) -> None:
	"""Record a CFO sign-off on a rating or on a closure, within school scope."""
	try:
		target_id = int(request.POST.get("target_id") or 0)
	except (TypeError, ValueError):
		target_id = 0

	if action == "qa_rating":
		rating = RiskRating.objects.filter(
			id=target_id, risk__school__in=allowed_schools
		).first()
		if rating is None:
			messages.error(request, "Could not find that rating.")
			return
		rating.qa_by = request.user
		rating.qa_at = timezone.now()
		rating.save()
		messages.success(request, "Rating signed off.")
		return

	risk = Risk.objects.filter(
		id=target_id, school__in=allowed_schools, status=Risk.Status.CLOSED
	).first()
	if risk is None:
		messages.error(request, "Could not find that closed risk.")
		return
	risk.close_qa_by = request.user
	risk.close_qa_at = timezone.now()
	risk.save()
	messages.success(request, "Closure signed off.")


@login_required
def risk_qa(request: HttpRequest) -> HttpResponse:
	"""Cross-school "awaiting QA" queue.

	Risk has one Trust-wide owner rather than each function lead seeing only
	their own slice, so this view spans schools — but only the schools the
	account is provisioned for. It does not bypass school scoping.
	"""
	if not user_can_qa_risk(request.user):
		return HttpResponseForbidden(
			"You do not have permission to QA risk register entries."
		)

	if request.user.is_superuser:
		schools = list(School.objects.order_by("name").all())
	else:
		_, schools, error = _get_allowed_schools(request)
		if error is not None:
			return error

	if not schools:
		messages.error(request, "No schools are available.")
		return redirect("home")

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)
	selected_round = _resolve_term(request)

	if request.method == "POST":
		action = request.POST.get("action")
		if action in ("qa_rating", "qa_close"):
			_apply_risk_qa(
				request,
				action,
				allowed_schools=School.objects.filter(id__in=[s.id for s in schools]),
			)
		return redirect(
			f"{reverse('review:risk_qa')}?year={selected_year_value}&round={selected_round}"
		)

	settings = RiskSettings.load()
	risks = (
		Risk.objects.filter(school__in=schools)
		.select_related("school", "category", "category__indepth_area")
		.prefetch_related("ratings__period", "ratings__recorded_by")
	)
	rows = _build_risk_rows(
		risks, year=selected_year, round_number=selected_round, settings=settings
	)

	rating_rows = [
		row for row in rows if row["awaiting_qa"] and not row["risk"].is_closed
	]
	closure_rows = [row for row in rows if row["close_awaiting_qa"]]
	rating_rows.sort(key=lambda row: (-row["severity"], row["risk"].school.name))
	closure_rows.sort(key=lambda row: row["risk"].closed_at or timezone.now())

	return render(
		request,
		"review/risk_qa.html",
		{
			"schools": schools,
			"selected_year_value": selected_year_value,
			"selected_round": selected_round,
			"round_options": TERM_OPTIONS,
			"academic_year_options": academic_year_options,
			"rating_rows": rating_rows,
			"closure_rows": closure_rows,
		},
	)


# -- Operations & Resources ----------------------------------------------------

def _visible_metric_ids(school, year: int) -> set[int]:
	"""Metric ids switched on for this school and year.

	Default is OFF: a metric with no visibility row is hidden. Hidden means
	absent from the page entirely, and out of every roll-up denominator.
	"""
	return set(
		OperationsMetricVisibility.objects.filter(
			school=school, year=year, is_visible=True
		).values_list("metric_id", flat=True)
	)


def _period_key(period) -> tuple[int, int]:
	return (period.year, period.round)


def _complaints_history(entries, current_key) -> list[int]:
	"""Counts for earlier terms, oldest first, for the complaints trend."""
	prior = [
		e for e in entries
		if _period_key(e.period) < current_key and e.value is not None
	]
	prior.sort(key=lambda e: _period_key(e.period))
	return [int(e.value) for e in prior]


def _computed_rag(metric, school, year, entry, entries_for_metric, current_key):
	"""RAG for the metrics that are derived rather than entered."""
	if metric.rule == RULE_STATUTORY_DATES:
		return statutory_rag(list(school.statutory_items.all()))
	if metric.rule == RULE_GRANT_PUBLICATION:
		return grant_rag(school, list(school.grant_publications.filter(year=year)))
	if metric.rule == RULE_COMPLAINTS_TREND:
		band = metric.band_for_phase(school.phase)
		step = band.step_change if band else 3
		current = int(entry.value) if (entry and entry.value is not None) else None
		return complaints_rag(
			current, _complaints_history(entries_for_metric, current_key), step_change=step
		)
	return OPS_BLUE


def _operations_domains(school, *, year: int, period, can_edit: bool):
	"""Domain cards for the page.

	A domain with no visible metric produces no card at all — not an empty one.
	An empty "IT" card would read as a failure rather than as "not in the pilot".
	"""
	visible_ids = _visible_metric_ids(school, year)
	if not visible_ids:
		return [], []

	metrics = list(
		OperationsMetric.objects.filter(id__in=visible_ids)
		.select_related("domain", "domain__indepth_area")
		.prefetch_related("bands")
	)

	entries = list(
		OperationsEntry.objects.filter(school=school, metric_id__in=visible_ids)
		.select_related("period", "metric", "theme")
	)
	by_metric: dict[int, list] = {}
	for entry in entries:
		by_metric.setdefault(entry.metric_id, []).append(entry)

	current_key = (period.year, period.round)
	tiles_by_domain: dict[int, list] = {}
	all_rags = []

	for metric in metrics:
		mine = by_metric.get(metric.id, [])
		entry = next((e for e in mine if _period_key(e.period) == current_key), None)

		# An annual-cycle metric is not chased for an entry every term: fall
		# back to the most recent entry in the same academic year.
		carried_from = None
		if entry is None and metric.cycle == OperationsMetric.Cycle.ANNUAL:
			in_year = [e for e in mine if e.period.year == period.year]
			if in_year:
				entry = max(in_year, key=lambda e: _period_key(e.period))
				carried_from = entry.period

		band = metric.band_for_phase(school.phase)

		if metric.is_computed:
			rag = _computed_rag(metric, school, year, entry, mine, current_key)
		else:
			rag = rag_for_entry(metric, entry, band) if entry else OPS_BLUE

		# Start-of-year baseline: this year's Autumn entry, so the governor
		# question "has this improved since September?" can be answered.
		baseline = next(
			(e for e in mine if e.period.year == period.year and e.period.round == 1), None
		)

		tile = {
			"metric": metric,
			"entry": entry,
			"band": band,
			"rag": rag,
			"rag_label": OPS_RAG_LABELS.get(rag, ""),
			"is_blue": rag == OPS_BLUE,
			"baseline": baseline if baseline and baseline is not entry else None,
			"carried_from": carried_from,
			"value": entry.value if entry else None,
			"commentary": entry.commentary if entry else "",
			"theme": entry.theme if entry else None,
			"evidence_label": metric.get_evidence_display(),
			"is_annual": metric.cycle == OperationsMetric.Cycle.ANNUAL,
			"no_band_for_phase": band is None,
		}

		# On a judgement-based metric the three band statements *are* the
		# picker: a Principal reads the statement they are choosing rather than
		# matching a colour in a dropdown to a paragraph further up the tile.
		if not metric.is_computed and not metric.is_numeric:
			chosen = entry.band_choice if entry else ""
			tile["band_options"] = [
				{
					"value": value,
					"label": label,
					"descriptor": getattr(band, f"{value}_descriptor", "") if band else "",
					"selected": chosen == value,
				}
				for value, label in OPS_BAND_CHOICES
			]
			tile["band_unset"] = not chosen

		# Statutory compliance expands to show which item is overdue — the
		# whole point of storing the five dates separately.
		if metric.rule == RULE_STATUTORY_DATES:
			today = timezone.now().date()
			items = list(school.statutory_items.all())
			tile["statutory_items"] = [
				{
					"label": i.label,
					"next_due_date": i.next_due_date,
					"action_plan_in_place": i.action_plan_in_place,
					"overdue": bool(i.next_due_date and i.next_due_date < today),
					"days_overdue": (today - i.next_due_date).days if (i.next_due_date and i.next_due_date < today) else 0,
				}
				for i in items
			]

		# The grant checklist is derived from phase and type, not fixed.
		if metric.rule == RULE_GRANT_PUBLICATION:
			records = {g.grant: g for g in school.grant_publications.filter(year=year)}
			tile["grants"] = [
				{
					"label": GRANT_LABELS[g],
					"status": records[g].get_status_display() if g in records else "Not recorded",
					"recorded": g in records,
				}
				for g in applicable_grants(school)
			]

		tiles_by_domain.setdefault(metric.domain_id, []).append(tile)
		all_rags.append(rag)

	domains = []
	seen = {}
	for metric in metrics:
		seen[metric.domain_id] = metric.domain
	for domain_id, domain in sorted(seen.items(), key=lambda kv: kv[1].order):
		tiles = tiles_by_domain.get(domain_id, [])
		if not tiles:
			# Cannot happen today, but keeps the "no empty cards" rule local.
			continue
		domains.append({
			"domain": domain,
			"tiles": tiles,
			"count": len(tiles),
			"summary": ops_summarise(t["rag"] for t in tiles),
		})

	return domains, all_rags


def _operations_scope(school, year: int) -> dict:
	"""What a school's Operations position is based on, for the roll-up.

	Hidden metrics are excluded from the denominator, and the visible count is
	shown, so a Board member never compares two schools that measured different
	things without knowing it.
	"""
	visible = len(_visible_metric_ids(school, year))
	total = OperationsMetric.objects.count()
	return {
		"visible": visible,
		"total": total,
		"in_pilot": 0 < visible < total,
		"label": f"{visible} of {total} metrics" + (" — pilot" if 0 < visible < total else ""),
	}


def _operations_summary_rows(schools, *, year: int, round_number: int) -> list[dict]:
	"""Trust Dashboard roll-up: one row per school, with its pilot scope."""
	period = ReviewPeriod.objects.filter(year=year, round=round_number).first()
	if period is None:
		period = ReviewPeriod(year=year, round=round_number)

	rows = []
	for school in schools:
		domains, rags = _operations_domains(school, year=year, period=period, can_edit=False)
		if not rags:
			continue
		summary = ops_summarise(rags)
		reds = [
			t["metric"].name
			for d in domains for t in d["tiles"] if t["rag"] == OPS_RED
		]
		ambers = [
			t["metric"].name
			for d in domains for t in d["tiles"] if t["rag"] == OPS_AMBER
		]
		rows.append({
			"school": school,
			"summary": summary,
			"scope": _operations_scope(school, year),
			"reds": reds,
			"ambers": ambers,
			"domains": domains,
		})
	return rows


def _operations_executive_summary(rows) -> list[str]:
	"""A short written summary to sit alongside the RAG grid, not replace it.

	Generated from the same data as the tiles so it cannot drift out of step
	with them.
	"""
	if not rows:
		return []

	lines = []
	schools_with_red = [r for r in rows if r["summary"]["red"]]
	schools_with_amber = [r for r in rows if r["summary"]["amber"] and not r["summary"]["red"]]
	blue_total = sum(r["summary"]["blue"] for r in rows)
	piloting = [r for r in rows if r["scope"]["in_pilot"]]

	lines.append(
		f"{len(rows)} school{'s' if len(rows) != 1 else ''} reporting Operations & Resources "
		f"this term; {len(piloting)} of them on a partial set of metrics."
	)
	if schools_with_red:
		for row in schools_with_red:
			lines.append(
				f"{row['school'].name}: red on {', '.join(row['reds'])} "
				f"({row['scope']['label']})."
			)
	else:
		lines.append("No school is showing red on any visible metric.")
	if schools_with_amber:
		lines.append(
			"Amber to monitor: "
			+ "; ".join(f"{r['school'].name} — {', '.join(r['ambers'])}" for r in schools_with_amber)
			+ "."
		)
	if blue_total:
		lines.append(
			f"{blue_total} tile{'s' if blue_total != 1 else ''} not yet benchmarked (blue); "
			"these are not green and should not be read as such."
		)
	return lines


@login_required
def operations(request: HttpRequest) -> HttpResponse:
	"""A school's Operations & Resources position for one term."""
	can_edit = user_can_edit(request.user)

	if request.method == "POST" and not can_edit:
		school_id = request.POST.get("school_id") if request.user.is_superuser else None
		return _readonly_redirect(
			request,
			"review:operations",
			[
				("year", request.POST.get("year") or ""),
				("round", request.POST.get("round") or ""),
				("school", school_id or ""),
			],
		)

	school, schools, error = _resolve_school_selection(request)
	if error is not None:
		return error

	selected_year, selected_year_value, academic_year_options = _academic_year_context(request)
	selected_round = _resolve_term(request)

	if can_edit:
		period_db, _ = ReviewPeriod.objects.get_or_create(
			year=selected_year, round=selected_round
		)
		period = period_db
	else:
		period_db = ReviewPeriod.objects.filter(
			year=selected_year, round=selected_round
		).first()
		period = period_db or ReviewPeriod(year=selected_year, round=selected_round)

	if request.method == "POST" and can_edit and period_db is not None:
		_save_operations(request, school=school, period=period_db, year=selected_year)
		params = [("year", selected_year_value), ("round", str(selected_round))]
		if request.user.is_superuser:
			params.insert(0, ("school", str(school.id)))
		query = "&".join(f"{k}={v}" for k, v in params if v)
		return redirect(f"{reverse('review:operations')}?{query}")

	domains, all_rags = _operations_domains(
		school, year=selected_year, period=period, can_edit=can_edit
	)
	scope = _operations_scope(school, selected_year)

	note = None
	if period_db is not None:
		note = OperationsNote.objects.filter(school=school, period=period_db).first()

	# Earlier terms' notes stay visible, so the free text forms a record rather
	# than something that vanishes at the end of the term.
	current_key = (selected_year, selected_round)
	earlier_notes = [
		n
		for n in OperationsNote.objects.filter(school=school)
		.exclude(text="")
		.select_related("period", "updated_by")
		if (n.period.year, n.period.round) < current_key
	]
	earlier_notes.sort(key=lambda n: (n.period.year, n.period.round), reverse=True)
	earlier_notes = earlier_notes[:4]

	# Read-only summary of the two highest-scoring open risks. This reads the
	# Phase 1 register directly and never keeps its own copy.
	risk_rows = _build_risk_rows(
		Risk.objects.filter(school=school, status=Risk.Status.OPEN)
		.select_related("category", "category__indepth_area")
		.prefetch_related("ratings__period"),
		year=selected_year,
		round_number=selected_round,
		settings=RiskSettings.load(),
	)
	risk_rows = [r for r in risk_rows if r["current"]]
	risk_rows.sort(key=lambda r: -r["severity"])
	top_risks = risk_rows[:2]

	themes = ComplaintTheme.objects.filter(is_active=True)

	return render(
		request,
		"review/operations.html",
		{
			"school": school,
			"schools": schools,
			"period": period,
			"selected_year_value": selected_year_value,
			"selected_round": selected_round,
			"round_options": TERM_OPTIONS,
			"academic_year_options": academic_year_options,
			"domains": domains,
			"scope": scope,
			"summary": ops_summarise(all_rags),
			"note": note,
			"earlier_notes": earlier_notes,
			"top_risks": top_risks,
			"themes": themes,
			"ops_legend": OPS_RAG_LEGEND,
			"legend_standing_text": OPS_LEGEND_STANDING_TEXT,
			"small_print": OPS_SMALL_PRINT,
			"can_edit": can_edit,
		},
	)


def _save_operations(request: HttpRequest, *, school, period, year: int) -> None:
	"""Save the term's entries and the free-text note.

	Only metrics visible for this school and year are writable: a hidden metric
	cannot be written to even if its field is forged into the POST.
	"""
	visible_ids = _visible_metric_ids(school, year)
	metrics = {
		m.id: m
		for m in OperationsMetric.objects.filter(id__in=visible_ids).prefetch_related("bands")
	}

	saved = 0
	with transaction.atomic():
		for metric_id, metric in metrics.items():
			prefix = f"metric-{metric_id}-"
			if not any(k.startswith(prefix) for k in request.POST):
				continue

			raw_value = (request.POST.get(prefix + "value") or "").strip()
			band_choice = (request.POST.get(prefix + "band_choice") or "").strip()
			commentary = (request.POST.get(prefix + "commentary") or "").strip()
			red_reason = (request.POST.get(prefix + "red_reason") or "").strip()
			theme_id = (request.POST.get(prefix + "theme") or "").strip()

			value = None
			if raw_value:
				try:
					value = Decimal(raw_value)
				except (InvalidOperation, ValueError):
					messages.error(
						request, f"{metric.name}: “{raw_value}” is not a number."
					)
					continue

			if band_choice and band_choice not in dict(OPS_BAND_CHOICES):
				band_choice = ""

			theme = None
			if theme_id:
				theme = ComplaintTheme.objects.filter(id=theme_id, is_active=True).first()

			entry, _ = OperationsEntry.objects.get_or_create(
				school=school, period=period, metric=metric
			)
			entry.value = value
			entry.band_choice = band_choice
			entry.commentary = commentary
			entry.manual_red_reason = red_reason
			entry.theme = theme
			entry.source = OperationsEntry.Source.MANUAL
			entry.recorded_by = request.user
			entry.save()
			saved += 1

		if "anything_else" in request.POST:
			text = (request.POST.get("anything_else") or "").strip()
			note, _ = OperationsNote.objects.get_or_create(school=school, period=period)
			note.text = text
			note.updated_by = request.user
			note.save()

	messages.success(request, "Operations & Resources saved.")
