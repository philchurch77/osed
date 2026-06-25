from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse
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
)
from .models import (
	Category,
	Evaluation,
	InDepthArea,
	InDepthJudgementArea,
	InDepthResponse,
	InDepthReview,
	InDepthStandard,
	ReviewPeriod,
	School,
	SchoolProfile,
	current_academic_year_start,
)
from .permissions import user_can_edit


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

	round_options = [{"value": r, "label": f"Round {r}"} for r in (1, 2, 3)]

	current_period = ReviewPeriod.objects.filter(year=year, round=selected_round).first()

	# Determine the previous period for trend comparison.
	# Round 1's predecessor is Round 3 of the prior academic year.
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

	return render(
		request,
		"review/board.html",
		{
			"schools": schools,
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
# up-path climbs Expected -> Strong -> Exceptional, the down-path drops to
# Urgent Improvement. Needs Attention is only an outcome label, never RAGed.
_RICH_KEYS_DEFAULT = [
	"expected_standard",
	"strong_standard",
	"exceptional",
	"urgent_improvement",
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
	"urgent_improvement": "urgent_improvement",
	"needs_attention": "urgent_improvement",
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
		# Down-path. Polarity is flipped: on Urgent Improvement, a red means the
		# failing does NOT apply. All red => no failings apply => Needs Attention.
		ui_list = rags_by_key.get("urgent_improvement")
		ui = _rung_state(ui_list)
		if ui == "absent":
			return "needs_attention"
		if ui == "incomplete":
			return ""
		return "needs_attention" if all(r == "red" for r in ui_list) else "urgent_improvement"

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
			"is_downpath": s.key == "urgent_improvement",
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