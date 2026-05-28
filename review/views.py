from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from allauth.account.views import LoginView

from .forms import (
	DashboardRatingForm,
	EvaluationEntryForm,
	InDepthJustificationForm,
	InDepthRAGForm,
	InDepthResponseForm,
	RATING_CHOICES_DEFAULT,
	RATING_CHOICES_SAFEGUARDING,
	ReflectionForm,
)
from .models import (
	Category,
	Evaluation,
	InDepthArea,
	InDepthResponse,
	InDepthReview,
	InDepthStatement,
	ReviewPeriod,
	School,
	SchoolProfile,
	current_academic_year_start,
)
from .permissions import user_can_edit


MIN_ACADEMIC_YEAR_START = 2025


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


def home(request: HttpRequest) -> HttpResponse:
	if not request.user.is_authenticated:
		# Keep the sign-in experience on the homepage.
		return LoginView.as_view(template_name="account/login.html")(request)

	if request.user.is_superuser:
		schools = School.objects.order_by("name").all()
		return render(request, "review/home.html", {"schools": schools})

	try:
		school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
			"schools"
		).get(user=request.user)
	except SchoolProfile.DoesNotExist:
		return render(
			request,
			"review/no_school_profile.html",
			{"user": request.user},
			status=403,
		)

	allowed_schools = list(school_profile.schools.order_by("name").all())
	if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
		allowed_schools.insert(0, school_profile.school)
	return render(request, "review/home.html", {"schools": allowed_schools})


@login_required
def respond(request: HttpRequest) -> HttpResponse:
	messages.info(request, "Statement entry has been retired. Use the School Dashboard instead.")
	return redirect("review:dashboard")


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
			return redirect("review:home")
	else:
		try:
			school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
				"schools"
			).get(
				user=request.user
			)
		except SchoolProfile.DoesNotExist:
			return render(
				request,
				"review/no_school_profile.html",
				{"user": request.user},
				status=403,
			)

		allowed_schools = list(school_profile.schools.order_by("name").all())
		if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
			allowed_schools.insert(0, school_profile.school)
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

	default_year = max(current_academic_year_start(), MIN_ACADEMIC_YEAR_START)
	year = _parse_academic_year_start(request.GET.get("year"), default_year)
	year = max(year, MIN_ACADEMIC_YEAR_START)
	selected_year_value = f"{year}-{year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

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
def dashboard(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)
	if request.method == "POST" and not can_edit:
		messages.error(request, "You have read-only access and cannot save changes.")
		selected_year_value = request.POST.get("year") or ""
		params = f"?year={selected_year_value}" if selected_year_value else ""
		if request.user.is_superuser:
			school_id = request.POST.get("school_id")
			if school_id:
				params = f"?school={school_id}&year={selected_year_value}" if selected_year_value else f"?school={school_id}"
		return redirect(f"{reverse('review:dashboard')}{params}")

	school = None
	schools = None

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
			return redirect("review:home")
	else:
		try:
			school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
				"schools"
			).get(
				user=request.user
			)
		except SchoolProfile.DoesNotExist:
			return render(
				request,
				"review/no_school_profile.html",
				{"user": request.user},
				status=403,
			)

		allowed_schools = list(school_profile.schools.order_by("name").all())
		if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
			allowed_schools.insert(0, school_profile.school)
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

	default_year = max(current_academic_year_start(), MIN_ACADEMIC_YEAR_START)
	selected_year = _parse_academic_year_start(
		request.GET.get("year") or request.POST.get("year"),
		default_year,
	)
	selected_year = max(selected_year, MIN_ACADEMIC_YEAR_START)
	selected_year_value = f"{selected_year}-{selected_year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, selected_year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

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


@login_required
def evaluation(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)
	if request.method == "POST" and not can_edit:
		messages.error(request, "You have read-only access and cannot save changes.")
		year = request.POST.get("year") or ""
		round_value = request.POST.get("round") or ""
		params = "?"
		params += f"year={year}" if year else ""
		if round_value:
			params += ("&" if params != "?" and params != "" else "") + f"round={round_value}"
		if params == "?":
			params = ""
		if request.user.is_superuser:
			school_id = request.POST.get("school_id")
			if school_id:
				joiner = "&" if params else "?"
				params = f"{params}{joiner}school={school_id}"
		return redirect(f"{reverse('review:evaluation')}{params}")

	school = None
	schools = None
	period = None

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
			return redirect("review:home")
	else:
		try:
			school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
				"schools"
			).get(
				user=request.user
			)
		except SchoolProfile.DoesNotExist:
			return render(
				request,
				"review/no_school_profile.html",
				{"user": request.user},
				status=403,
			)

		allowed_schools = list(school_profile.schools.order_by("name").all())
		if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
			allowed_schools.insert(0, school_profile.school)
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

	# Period selection (academic year start + round)
	default_year = max(current_academic_year_start(), MIN_ACADEMIC_YEAR_START)
	selected_year = _parse_academic_year_start(
		request.GET.get("year") or request.POST.get("year"),
		default_year,
	)
	selected_year = max(selected_year, MIN_ACADEMIC_YEAR_START)

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
	selected_year_value = f"{selected_year}-{selected_year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, selected_year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

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
		},
	)


@login_required
def indepth_review(request: HttpRequest) -> HttpResponse:
	can_edit = user_can_edit(request.user)
	if request.method == "POST" and not can_edit:
		messages.error(request, "You have read-only access and cannot save changes.")
		year = request.POST.get("year") or ""
		area_id = request.POST.get("area_id") or ""
		step = request.POST.get("step") or ""
		params = "?"
		params += f"year={year}" if year else ""
		if area_id:
			params += ("&" if params != "?" and params != "" else "") + f"area={area_id}"
		if step:
			params += ("&" if params not in ("?", "") else "") + f"step={step}"
		if params == "?":
			params = ""
		if request.user.is_superuser:
			school_id = request.POST.get("school_id")
			if school_id:
				joiner = "&" if params else "?"
				params = f"{params}{joiner}school={school_id}"
		return redirect(f"{reverse('review:indepth_review')}{params}")

	# ── RAG step helpers ─────────────────────────────────────────────────────────
	_RAG_STEPS = ("expected", "urgent_improvement", "strong_standard", "exceptional")
	_VALID_STEPS = _RAG_STEPS + ("justification", "reflection")

	school = None
	schools = None

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
			return redirect("review:home")
	else:
		try:
			school_profile = SchoolProfile.objects.select_related("school").prefetch_related(
				"schools"
			).get(
				user=request.user
			)
		except SchoolProfile.DoesNotExist:
			return render(
				request,
				"review/no_school_profile.html",
				{"user": request.user},
				status=403,
			)

		allowed_schools = list(school_profile.schools.order_by("name").all())
		if school_profile.school_id and all(s.id != school_profile.school_id for s in allowed_schools):
			allowed_schools.insert(0, school_profile.school)
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

	default_year = max(current_academic_year_start(), MIN_ACADEMIC_YEAR_START)
	selected_year = _parse_academic_year_start(
		request.GET.get("year") or request.POST.get("year"),
		default_year,
	)
	selected_year = max(selected_year, MIN_ACADEMIC_YEAR_START)
	selected_year_value = f"{selected_year}-{selected_year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, selected_year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

	areas = list(InDepthArea.objects.order_by("order", "name").all())
	area = None
	selected_area = request.GET.get("area") or request.POST.get("area_id")
	if selected_area:
		try:
			area = InDepthArea.objects.get(id=selected_area)
		except InDepthArea.DoesNotExist:
			area = None
	if area is None and areas:
		area = areas[0]

	if not areas or area is None:
		messages.error(
			request,
			"No in-depth review statements have been loaded yet. Ask an admin to import the Excel statements.",
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
				"current_step": "expected",
				"review": None,
				"rows": [],
				"formset": None,
				"can_edit": can_edit,
				"is_safeguarding": False,
			},
		)

	is_safeguarding = area.is_safeguarding

	# Expected-standard statements for this area
	statements = list(
		InDepthStatement.objects.filter(
			area=area, standard_type=InDepthStatement.StandardType.EXPECTED
		).order_by("statement_number")
	)
	statement_ids = {s.id for s in statements}

	# ── Step resolution ─────────────────────────────────────────────────────────
	step_param = (request.POST.get("step") or request.GET.get("step") or "").strip().lower()
	# Map legacy "secondary" value from old data
	if step_param == "secondary":
		step_param = "justification"

	review = InDepthReview.objects.filter(
		school=school,
		year=selected_year,
		area=area,
	).first()

	# Resolve current_step from param, then saved review step, then default
	effective_review_step = (review.step if review else "expected")
	if effective_review_step == "secondary":
		effective_review_step = "justification"

	if step_param in _VALID_STEPS:
		current_step = step_param
	else:
		current_step = effective_review_step

	existing = {} if review is None else {
		r.statement_id: r
		for r in InDepthResponse.objects.filter(review=review, statement__area=area)
	}

	# ── Area capability helpers ──────────────────────────────────────────────────
	def _has_type(standard_type: str) -> bool:
		return InDepthStatement.objects.filter(area=area, standard_type=standard_type).exists()

	def _stmts_for(standard_type: str):
		return list(
			InDepthStatement.objects.filter(area=area, standard_type=standard_type)
			.order_by("statement_number")
		)

	def _build_params(step: str) -> str:
		if request.user.is_superuser:
			return f"?school={school.id}&year={selected_year_value}&area={area.id}&step={step}"
		return f"?year={selected_year_value}&area={area.id}&step={step}"

	# ── POST handlers ───────────────────────────────────────────────────────────
	if request.method == "POST" and can_edit:
		post_step = (request.POST.get("step") or "").strip().lower()

		# ── Expected Standard ──
		if post_step == "expected":
			if is_safeguarding:
				# Safeguarding: Met / Not met
				FormSetClass = formset_factory(InDepthResponseForm, extra=0)
				formset = FormSetClass(request.POST)
				if formset.is_valid():
					with transaction.atomic():
						if review is None:
							review = InDepthReview.objects.create(
								school=school, year=selected_year, area=area, updated_by=request.user,
							)
						else:
							review.updated_by = request.user
						for form in formset:
							stmt_id = form.cleaned_data["statement_id"]
							if stmt_id not in statement_ids:
								continue
							InDepthResponse.objects.update_or_create(
								review=review, statement_id=stmt_id,
								defaults={"applies": form.cleaned_data["applies"]},
							)
						review.secondary_level = "expected"
						review.step = "justification"
						review.save()
					return redirect(f"{reverse('review:indepth_review')}{_build_params('justification')}")
				current_step = "expected"
			else:
				# Standard areas: RAG
				FormSetClass = formset_factory(InDepthRAGForm, extra=0)
				formset = FormSetClass(request.POST)
				if formset.is_valid():
					with transaction.atomic():
						if review is None:
							review = InDepthReview.objects.create(
								school=school, year=selected_year, area=area, updated_by=request.user,
							)
						else:
							review.updated_by = request.user
						for form in formset:
							stmt_id = form.cleaned_data["statement_id"]
							if stmt_id not in statement_ids:
								continue
							InDepthResponse.objects.update_or_create(
								review=review, statement_id=stmt_id,
								defaults={"rag": form.cleaned_data["rag"]},
							)
						# Determine next step
						saved_rags = list(
							InDepthResponse.objects.filter(review=review, statement__in=statements)
							.values_list("rag", flat=True)
						)
						has_red = any(r == "red" for r in saved_rags)
						if has_red:
							if _has_type(InDepthStatement.StandardType.URGENT_IMPROVEMENT):
								review.step = "urgent_improvement"
							else:
								review.secondary_level = "needs_attention"
								review.step = "justification"
						else:
							# All green/amber
							if _has_type(InDepthStatement.StandardType.STRONG_STANDARD):
								review.step = "strong_standard"
							else:
								review.secondary_level = "expected"
								review.step = "justification"
						review.save()
					return redirect(f"{reverse('review:indepth_review')}{_build_params(review.step)}")
				current_step = "expected"

		# ── Urgent Improvement ──
		elif post_step == "urgent_improvement":
			urgent_stmts = _stmts_for(InDepthStatement.StandardType.URGENT_IMPROVEMENT)
			urgent_stmt_ids = {s.id for s in urgent_stmts}
			FormSetClass = formset_factory(InDepthRAGForm, extra=0)
			formset = FormSetClass(request.POST)
			if formset.is_valid():
				with transaction.atomic():
					for form in formset:
						stmt_id = form.cleaned_data["statement_id"]
						if stmt_id not in urgent_stmt_ids:
							continue
						InDepthResponse.objects.update_or_create(
							review=review, statement_id=stmt_id,
							defaults={"rag": form.cleaned_data["rag"]},
						)
					saved_rags = list(
						InDepthResponse.objects.filter(review=review, statement__in=urgent_stmts)
						.values_list("rag", flat=True)
					)
					all_red = all(r == "red" for r in saved_rags if r)
					review.secondary_level = "needs_attention" if all_red else "expected"
					review.step = "justification"
					review.updated_by = request.user
					review.save()
				return redirect(f"{reverse('review:indepth_review')}{_build_params('justification')}")
			current_step = "urgent_improvement"

		# ── Strong Standard ──
		elif post_step == "strong_standard":
			strong_stmts = _stmts_for(InDepthStatement.StandardType.STRONG_STANDARD)
			strong_stmt_ids = {s.id for s in strong_stmts}
			FormSetClass = formset_factory(InDepthRAGForm, extra=0)
			formset = FormSetClass(request.POST)
			if formset.is_valid():
				with transaction.atomic():
					for form in formset:
						stmt_id = form.cleaned_data["statement_id"]
						if stmt_id not in strong_stmt_ids:
							continue
						InDepthResponse.objects.update_or_create(
							review=review, statement_id=stmt_id,
							defaults={"rag": form.cleaned_data["rag"]},
						)
					saved_rags = list(
						InDepthResponse.objects.filter(review=review, statement__in=strong_stmts)
						.values_list("rag", flat=True)
					)
					has_red = any(r == "red" for r in saved_rags if r)
					if has_red:
						review.secondary_level = "expected"
						review.step = "justification"
					else:
						# All green/amber — try exceptional
						if _has_type(InDepthStatement.StandardType.EXCEPTIONAL):
							review.step = "exceptional"
						else:
							review.secondary_level = "strong_standard"
							review.step = "justification"
					review.updated_by = request.user
					review.save()
				return redirect(f"{reverse('review:indepth_review')}{_build_params(review.step)}")
			current_step = "strong_standard"

		# ── Exceptional ──
		elif post_step == "exceptional":
			exceptional_stmts = _stmts_for(InDepthStatement.StandardType.EXCEPTIONAL)
			exceptional_stmt_ids = {s.id for s in exceptional_stmts}
			FormSetClass = formset_factory(InDepthRAGForm, extra=0)
			formset = FormSetClass(request.POST)
			if formset.is_valid():
				with transaction.atomic():
					for form in formset:
						stmt_id = form.cleaned_data["statement_id"]
						if stmt_id not in exceptional_stmt_ids:
							continue
						InDepthResponse.objects.update_or_create(
							review=review, statement_id=stmt_id,
							defaults={"rag": form.cleaned_data["rag"]},
						)
					saved_rags = list(
						InDepthResponse.objects.filter(review=review, statement__in=exceptional_stmts)
						.values_list("rag", flat=True)
					)
					has_red = any(r == "red" for r in saved_rags if r)
					review.secondary_level = "strong_standard" if has_red else "exceptional"
					review.step = "justification"
					review.updated_by = request.user
					review.save()
				return redirect(f"{reverse('review:indepth_review')}{_build_params('justification')}")
			current_step = "exceptional"

		# ── Justification ──
		elif post_step == "justification":
			determined_level = (review.secondary_level if review else "") or "expected"
			just_stmts = _stmts_for(determined_level)
			if not just_stmts:
				just_stmts = statements
			just_stmt_ids = {s.id for s in just_stmts}
			JustFormSet = formset_factory(InDepthJustificationForm, extra=0)
			formset = JustFormSet(request.POST)
			if formset.is_valid():
				with transaction.atomic():
					for form in formset:
						stmt_id = form.cleaned_data["statement_id"]
						if stmt_id not in just_stmt_ids:
							continue
						InDepthResponse.objects.update_or_create(
							review=review, statement_id=stmt_id,
							defaults={
								"justification": form.cleaned_data["justification"],
								"next_steps": form.cleaned_data["next_steps"],
							},
						)
					review.updated_by = request.user
					review.save()
				messages.success(request, "In-depth review saved.")
				return redirect(f"{reverse('review:indepth_review')}{_build_params('reflection')}")
			current_step = "justification"

		# ── Reflection ──
		elif post_step == "reflection":
			form = ReflectionForm(request.POST)
			if form.is_valid():
				with transaction.atomic():
					if review is None:
						review = InDepthReview.objects.create(
							school=school, year=selected_year, area=area, updated_by=request.user,
						)
					review.qa_reflection = form.cleaned_data["qa_reflection"]
					review.updated_by = request.user
					review.save()
				messages.success(request, "Reflection saved.")
				return redirect(f"{reverse('review:indepth_review')}{_build_params('reflection')}")
			current_step = "reflection"

	# ── Build context for GET (or a POST with invalid form) ─────────────────────
	formset = None
	rows = []
	step_title = ""
	rag_legend = [
		{"value": "red", "label": "Red", "description": "Insufficient evidence to meet the standard"},
		{"value": "amber", "label": "Amber", "description": "Partial evidence; you believe the standard is met but gaps remain"},
		{"value": "green", "label": "Green", "description": "Strong, comprehensive evidence supports your judgement"},
	]

	_STEP_TITLES = {
		"expected": "Expected Standard",
		"urgent_improvement": "Urgent Improvement",
		"strong_standard": "Strong Standard",
		"exceptional": "Exceptional",
		"justification": "Justification & Next Steps",
	}

	if current_step in _RAG_STEPS or (current_step == "expected" and is_safeguarding):
		# Determine which statements to show
		if current_step == "expected":
			step_stmts = statements
		else:
			step_stmts = _stmts_for(current_step)
		step_title = _STEP_TITLES.get(current_step, current_step.replace("_", " ").title())

		if is_safeguarding and current_step == "expected":
			# Safeguarding: Met / Not met
			FormSetClass = formset_factory(InDepthResponseForm, extra=0)
			initial = []
			for statement in step_stmts:
				resp = existing.get(statement.id)
				if resp is None or resp.applies is None:
					applies_value = ""
				elif resp.applies is True:
					applies_value = "1"
				else:
					applies_value = "0"
				initial.append({"statement_id": statement.id, "applies": applies_value})
			formset = FormSetClass(initial=initial)
		else:
			# RAG
			FormSetClass = formset_factory(InDepthRAGForm, extra=0)
			initial = [
				{"statement_id": s.id, "rag": existing.get(s.id).rag if existing.get(s.id) else ""}
				for s in step_stmts
			]
			formset = FormSetClass(initial=initial)

		if not can_edit:
			for form in formset.forms:
				for field in form.fields.values():
					field.disabled = True
		rows = [{"statement": s, "form": f} for s, f in zip(step_stmts, formset.forms)]

	elif current_step == "justification":
		determined_level = (review.secondary_level if review else "") or "expected"
		just_stmts = _stmts_for(determined_level)
		if not just_stmts:
			just_stmts = statements
		step_title = f"Justification & Next Steps — {_STEP_TITLES.get(determined_level, determined_level.replace('_', ' ').title())}"
		JustFormSet = formset_factory(InDepthJustificationForm, extra=0)
		initial = [
			{
				"statement_id": s.id,
				"justification": existing.get(s.id).justification if existing.get(s.id) else "",
				"next_steps": existing.get(s.id).next_steps if existing.get(s.id) else "",
			}
			for s in just_stmts
		]
		formset = JustFormSet(initial=initial)
		if not can_edit:
			for form in formset.forms:
				for field in form.fields.values():
					field.disabled = True
		rows = [
			{
				"statement": s,
				"form": f,
				"rag": existing.get(s.id).rag if existing.get(s.id) else "",
				"applies": existing.get(s.id).applies if existing.get(s.id) else None,
			}
			for s, f in zip(just_stmts, formset.forms)
		]

	# ── Build step indicator ─────────────────────────────────────────────────────
	def _build_step_nav():
		steps = []

		if review is None:
			# Show full possible journey for this area; only step 1 is accessible yet.
			num = 1
			steps.append({"key": "expected", "label": f"{num}. Expected Standard", "accessible": True})
			num += 1
			if not is_safeguarding:
				if _has_type(InDepthStatement.StandardType.URGENT_IMPROVEMENT):
					steps.append({"key": "urgent_improvement", "label": f"{num}. Urgent Improvement", "accessible": False})
					num += 1
				if _has_type(InDepthStatement.StandardType.STRONG_STANDARD):
					steps.append({"key": "strong_standard", "label": f"{num}. Strong Standard", "accessible": False})
					num += 1
				if _has_type(InDepthStatement.StandardType.EXCEPTIONAL):
					steps.append({"key": "exceptional", "label": f"{num}. Exceptional", "accessible": False})
					num += 1
			steps.append({"key": "justification", "label": f"{num}. Justification", "accessible": False})
			num += 1
			steps.append({"key": "reflection", "label": f"{num}. Reflection", "accessible": False})
			return steps

		rev_step = review.step
		if rev_step == "secondary":
			rev_step = "justification"

		num = 1
		steps.append({"key": "expected", "label": f"{num}. Expected Standard", "accessible": True})
		num += 1

		if not is_safeguarding:
			if rev_step in ("urgent_improvement", "justification") and _has_type(InDepthStatement.StandardType.URGENT_IMPROVEMENT):
				if rev_step == "urgent_improvement" or (
					rev_step == "justification" and review.secondary_level in ("needs_attention", "expected")
					and _has_type(InDepthStatement.StandardType.URGENT_IMPROVEMENT)
				):
					steps.append({"key": "urgent_improvement", "label": f"{num}. Urgent Improvement", "accessible": True})
					num += 1

			if rev_step in ("strong_standard", "exceptional", "justification") and _has_type(InDepthStatement.StandardType.STRONG_STANDARD):
				if rev_step == "strong_standard" or (
					rev_step in ("exceptional", "justification") and review.secondary_level in ("strong_standard", "exceptional", "")
				):
					steps.append({"key": "strong_standard", "label": f"{num}. Strong Standard", "accessible": True})
					num += 1

			if rev_step in ("exceptional", "justification") and _has_type(InDepthStatement.StandardType.EXCEPTIONAL):
				if rev_step == "exceptional" or (
					rev_step == "justification" and review.secondary_level in ("exceptional", "strong_standard")
					and _has_type(InDepthStatement.StandardType.EXCEPTIONAL)
				):
					steps.append({"key": "exceptional", "label": f"{num}. Exceptional", "accessible": True})
					num += 1

		if rev_step == "justification":
			determined = review.secondary_level or "expected"
			label_map = {
				"needs_attention": "Needs Attention",
				"expected": "Expected Standard",
				"strong_standard": "Strong Standard",
				"exceptional": "Exceptional",
			}
			steps.append({
				"key": "justification",
				"label": f"{num}. Justification ({label_map.get(determined, determined.replace('_', ' ').title())})",
				"accessible": True,
			})
			num += 1
			steps.append({"key": "reflection", "label": f"{num}. Reflection", "accessible": True})
		else:
			# Still in RAG steps — show locked placeholders so user can see what's ahead.
			steps.append({"key": "justification", "label": f"{num}. Justification", "accessible": False})
			num += 1
			steps.append({"key": "reflection", "label": f"{num}. Reflection", "accessible": False})

		return steps

	step_nav = _build_step_nav()

	# ── Review completion status ─────────────────────────────────────────────────
	_LEVEL_LABELS = {
		"needs_attention": "Needs Attention",
		"expected": "Expected Standard",
		"strong_standard": "Strong Standard",
		"exceptional": "Exceptional",
	}
	review_is_complete = review is not None and review.step in ("justification", "secondary")
	determined_level_display = ""
	if review_is_complete:
		_lvl = review.secondary_level or "expected"
		determined_level_display = _LEVEL_LABELS.get(_lvl, _lvl.replace("_", " ").title())

	# ── Build reflection form (always needed for context) ───────────────────────
	if current_step == "reflection":
		step_title = "Reflection on QA & Feedback"
	reflection_value = review.qa_reflection if review else ""
	reflection_form = ReflectionForm(initial={"qa_reflection": reflection_value})
	if not can_edit:
		reflection_form.fields["qa_reflection"].disabled = True

	# determined_level is only set inside the justification branch; default for all other steps
	try:
		determined_level  # noqa: referenced below in context
	except UnboundLocalError:
		determined_level = ""

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
			"current_step": current_step,
			"review": review,
			"rows": rows,
			"formset": formset,
			"step_title": step_title,
			"step_nav": step_nav,
			"rag_legend": rag_legend,
			"can_edit": can_edit,
			"is_safeguarding": is_safeguarding,
			"reflection_form": reflection_form,
			"determined_level": determined_level if current_step == "justification" else "",
			"review_is_complete": review_is_complete,
			"determined_level_display": determined_level_display,
		},
	)