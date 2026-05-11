from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from allauth.account.views import LoginView

from .forms import DashboardRatingForm, EvaluationEntryForm, InDepthResponseForm
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


MIN_ACADEMIC_YEAR_START = 2025


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

	if request.user.is_superuser:
		schools = list(School.objects.order_by("name").all())
		selected = request.GET.get("school")
		if selected == "all":
			all_schools_selected = True
			if schools:
				# Keep a non-None school in context for template convenience.
				school = schools[0]
		elif selected:
			try:
				school = School.objects.get(id=selected)
			except School.DoesNotExist:
				school = None
		if school is None and schools and not all_schools_selected:
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
		selected = request.GET.get("school")
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
	year = _parse_academic_year_start(request.GET.get("year"), default_year)
	year = max(year, MIN_ACADEMIC_YEAR_START)
	selected_year_value = f"{year}-{year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

	periods = {
		r: ReviewPeriod.objects.get_or_create(year=year, round=r)[0]
		for r in (1, 2, 3)
	}

	rows = []
	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	for category in categories:
		cells = []
		for r in (1, 2, 3):
			ratings_qs = Evaluation.objects.filter(
				period=periods[r],
				category=category,
				rating__isnull=False,
			)
			if not all_schools_selected:
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
		},
	)


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
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

	periods = {
		r: ReviewPeriod.objects.get_or_create(year=selected_year, round=r)[0]
		for r in (1, 2, 3)
	}

	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	category_ids = {c.id for c in categories}

	existing = {
		(e.category_id, e.period.round): e
		for e in Evaluation.objects.filter(
			school=school,
			period__in=list(periods.values()),
			category__in=categories,
		)
	}

	DashboardFormSet = formset_factory(DashboardRatingForm, extra=0)

	if request.method == "POST":
		formset = DashboardFormSet(request.POST)
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
		},
	)


@login_required
def evaluation(request: HttpRequest) -> HttpResponse:
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

	period, _ = ReviewPeriod.objects.get_or_create(year=selected_year, round=selected_round)
	selected_year_value = f"{selected_year}-{selected_year + 1}"

	max_year = max(default_year + 2, MIN_ACADEMIC_YEAR_START + 4, selected_year)
	academic_year_options = [
		{"value": f"{y}-{y + 1}", "label": f"{y}/{y + 1}"}
		for y in range(MIN_ACADEMIC_YEAR_START, max_year + 1)
	]

	categories = list(Category.objects.filter(is_active=True).order_by("order", "name").all())
	category_ids = {c.id for c in categories}

	existing = {
		e.category_id: e
		for e in Evaluation.objects.filter(school=school, period=period, category__in=categories)
	}

	EvaluationFormSet = formset_factory(EvaluationEntryForm, extra=0)

	if request.method == "POST":
		formset = EvaluationFormSet(request.POST)
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
		},
	)


@login_required
def indepth_review(request: HttpRequest) -> HttpResponse:
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
				"rows": [],
				"formset": None,
			},
		)

	statements = list(
		InDepthStatement.objects.filter(area=area).order_by("statement_number").all()
	)
	statement_ids = {s.id for s in statements}

	review, _ = InDepthReview.objects.get_or_create(
		school=school,
		year=selected_year,
		area=area,
	)

	existing = {
		r.statement_id: r
		for r in InDepthResponse.objects.filter(review=review, statement__in=statements)
	}

	InDepthFormSet = formset_factory(InDepthResponseForm, extra=0)

	if request.method == "POST":
		formset = InDepthFormSet(request.POST)
		if formset.is_valid():
			with transaction.atomic():
				review.updated_by = request.user
				review.save()
				for form in formset:
					statement_id = form.cleaned_data["statement_id"]
					if statement_id not in statement_ids:
						continue
					applies = form.cleaned_data["applies"]
					justification = form.cleaned_data["justification"]

					InDepthResponse.objects.update_or_create(
						review=review,
						statement_id=statement_id,
						defaults={
							"applies": applies,
							"justification": justification,
						},
					)

			messages.success(request, "In-depth review saved.")
			params = f"?year={selected_year_value}&area={area.id}"
			if request.user.is_superuser:
				params = f"?school={school.id}&year={selected_year_value}&area={area.id}"
			return redirect(f"{reverse('review:indepth_review')}{params}")
	else:
		initial = []
		for statement in statements:
			current = existing.get(statement.id)
			if current is None or current.applies is None:
				applies_value = ""
			elif current.applies is True:
				applies_value = "1"
			else:
				applies_value = "0"
			initial.append(
				{
					"statement_id": statement.id,
					"applies": applies_value,
					"justification": current.justification if current else "",
				}
			)
		formset = InDepthFormSet(initial=initial)

	rows = []
	for statement, form in zip(statements, formset.forms):
		rows.append({"statement": statement, "form": form})

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
			"rows": rows,
			"formset": formset,
		},
	)
