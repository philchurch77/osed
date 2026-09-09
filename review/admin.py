from __future__ import annotations

import csv
import io

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import path

from simple_history.admin import SimpleHistoryAdmin

from .models import (
	Branding,
	Category,
	ComplaintTheme,
	Evaluation,
	GrantPublication,
	InDepthArea,
	InDepthJudgementArea,
	InDepthResponse,
	InDepthReview,
	InDepthStandard,
	InDepthSubSection,
	OperationsEntry,
	OperationsMetric,
	OperationsMetricBand,
	OperationsMetricVisibility,
	OperationsNote,
	ReviewPeriod,
	Risk,
	RiskRating,
	RiskSettings,
	School,
	SchoolProfile,
	StatutoryComplianceItem,
	TrustCategory,
	current_academic_year_start,
)
from .views import MIN_ACADEMIC_YEAR_START


def _request_schools(request):
	"""Return a queryset of schools the user may access."""
	if request.user.is_superuser:
		return School.objects.all()
	try:
		profile = (
			SchoolProfile.objects.select_related("school")
			.prefetch_related("schools")
			.get(user=request.user)
		)
	except SchoolProfile.DoesNotExist:
		return School.objects.none()

	allowed_ids = set(profile.schools.values_list("id", flat=True))
	if profile.school_id:
		allowed_ids.add(profile.school_id)
	return School.objects.filter(id__in=allowed_ids)


class ScopedHistoryAdminMixin:
	"""Keep the admin's History tab inside the user's own schools.

	SimpleHistoryAdmin.history_view looks the object up through get_queryset()
	first, which respects this app's per-school scoping. But when that finds
	nothing it falls back to rebuilding the object from the history table, which
	is unscoped, and the permission check behind that is model-level and ignores
	the object. So without this, a staff user scoped to one school could read
	another school's full version trail by visiting the history URL directly.

	Filtering the history queryset closes both paths at once: the fallback finds
	nothing either, and the view 404s.

	The revert view needs guarding separately -- see history_form_view below. It
	resolves the historical record through the model's DEFAULT manager, so
	neither get_queryset nor get_history_queryset applies to it.

	Superusers get the queryset unfiltered, for the same reason they bypass
	school scoping everywhere else in this codebase. It also matters for
	InDepthResponse: its path traverses `review`, so once a parent InDepthReview
	is deleted the join drops its history — precisely the rows you would be
	looking for. The other five filter on a `school_id` column held on the
	historical row itself, so nothing is lost there either way.
	"""

	# Lookup from the historical model to School.
	history_school_path = "school"

	def get_history_queryset(self, request, history_manager, pk_name, object_id):
		qs = super().get_history_queryset(request, history_manager, pk_name, object_id)
		if request.user.is_superuser:
			return qs
		return qs.filter(
			**{f"{self.history_school_path}__in": _request_schools(request)}
		)

	def history_form_view(self, request, object_id, version_id, extra_context=None):
		"""Guard the revert view, which the library leaves wide open.

		`SimpleHistoryAdmin.history_form_view` fetches the historical record with
		`get_object_or_404` against the historical model's default manager, and
		gates it on a model-level permission that ignores the object. Its POST
		branch then calls save_form/save_model with no change-permission check at
		all. Before this override, a staff user scoped to one school could open
		another school's revert URL, read the commentary, and POST to overwrite
		that school's live row — while the ordinary change view correctly refused
		them. Reproduced, then fixed.

		Resolve the record through the scoped history queryset instead, and
		require change permission before any write.
		"""
		history_manager = getattr(
			self.model, self.model._meta.simple_history_manager_attribute
		)
		in_scope = self.get_history_queryset(
			request, history_manager, self.model._meta.pk.attname, object_id
		)
		if not in_scope.filter(history_id=version_id).exists():
			raise Http404
		if request.method == "POST" and not self.has_change_permission(request):
			raise PermissionDenied
		return super().history_form_view(
			request, object_id, version_id, extra_context=extra_context
		)


class ProtectsWrittenWorkMixin:
	"""Refuse to delete a catalogue row that a school's written work hangs off.

	These models all cascade into evidence: deleting a Category takes every
	school's judgement_evidence for it, a ReviewPeriod takes a whole term across
	four features, an InDepthArea takes its reviews and every response beneath
	them. The confirmation page counts objects, not "three terms of Safeguarding
	commentary", so there is nothing on screen to stop you.

	`_indepth_sync.sync_judgement_areas` already refuses to delete a judgement
	area that holds responses. This is the same rule for the admin, which
	performs the identical delete with no guard at all.

	Subclasses define `written_work_count`. Deactivate the row instead, or clear
	the dependent records deliberately first.
	"""

	def written_work_count(self, obj) -> int:
		return 0

	def has_delete_permission(self, request, obj=None):
		if obj is not None and self.written_work_count(obj):
			return False
		return super().has_delete_permission(request, obj=obj)

	def get_actions(self, request):
		# delete_selected resolves permission per model, not per row, so it walks
		# straight past has_delete_permission above. Remove it entirely here and
		# delete one row at a time, where the guard applies.
		actions = super().get_actions(request)
		actions.pop("delete_selected", None)
		return actions


@admin.register(Category)
class CategoryAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("order", "name", "is_active")
	list_filter = ("is_active",)
	ordering = ("-is_active", "order", "name")
	search_fields = ("name",)

	def written_work_count(self, obj) -> int:
		return Evaluation.objects.filter(category=obj).count()


@admin.register(School)
class SchoolAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("name", "phase", "is_mainstream", "logo")
	list_filter = ("phase", "is_mainstream")
	search_fields = ("name",)

	def written_work_count(self, obj) -> int:
		return (
			Evaluation.objects.filter(school=obj).count()
			+ InDepthReview.objects.filter(school=obj).count()
			+ Risk.objects.filter(school=obj).count()
			+ OperationsEntry.objects.filter(school=obj).count()
		)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(id__in=_request_schools(request))


@admin.register(SchoolProfile)
class SchoolProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "school")
	list_display_links = ("user",)
	list_editable = ("school",)
	search_fields = ("user__username", "school__name")
	list_select_related = ("user", "school")
	filter_horizontal = ("schools",)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		school_qs = _request_schools(request)
		return qs.filter(Q(school__in=school_qs) | Q(schools__in=school_qs)).distinct()

	def get_form(self, request, obj=None, **kwargs):
		form = super().get_form(request, obj, **kwargs)
		if not request.user.is_superuser and "school" in form.base_fields:
			form.base_fields["school"].disabled = True
		return form

	def save_model(self, request, obj, form, change):
		if not request.user.is_superuser:
			first = _request_schools(request).order_by("name").first()
			if first is not None:
				obj.school = first
		super().save_model(request, obj, form, change)
		if obj.school_id:
			obj.schools.add(obj.school)


@admin.register(Branding)
class BrandingAdmin(admin.ModelAdmin):
	list_display = ("id", "trust_emblem")

	def has_add_permission(self, request):
		if Branding.objects.exists():
			return False
		return super().has_add_permission(request)


@admin.register(ReviewPeriod)
class ReviewPeriodAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("year", "round")
	list_filter = ("year", "round")
	ordering = ("-year", "round")

	def written_work_count(self, obj) -> int:
		return (
			Evaluation.objects.filter(period=obj).count()
			+ RiskRating.objects.filter(period=obj).count()
			+ OperationsEntry.objects.filter(period=obj).count()
			+ OperationsNote.objects.filter(period=obj).count()
		)


@admin.register(Evaluation)
class EvaluationAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	list_display = (
		"school",
		"period",
		"category",
		"rating",
		"rating_overridden",
		"updated_at",
		"updated_by",
	)
	list_filter = ("school", "period", "category", "rating_overridden")
	search_fields = ("category__name", "judgement_evidence", "to_progress")
	list_select_related = ("school", "period", "category")
	readonly_fields = (
		"created_at",
		"updated_at",
		"updated_by",
		"rating_overridden",
		"system_rating",
		"overridden_by",
		"overridden_at",
		"override_reason",
	)

	def save_model(self, request, obj, form, change):
		obj.updated_by = request.user
		super().save_model(request, obj, form, change)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(InDepthArea)
class InDepthAreaAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("order", "name", "is_safeguarding")
	list_filter = ("is_safeguarding",)
	ordering = ("order", "name")
	search_fields = ("name",)
	fieldsets = (
		(None, {
			"fields": ("name", "order", "is_safeguarding", "purpose"),
		}),
	)

	def written_work_count(self, obj) -> int:
		return InDepthReview.objects.filter(area=obj).count()


@admin.register(InDepthSubSection)
class InDepthSubSectionAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("area", "order", "name")
	list_filter = ("area",)
	ordering = ("area__order", "area__name", "order")
	search_fields = ("name", "overview", "evidence_criteria")
	list_select_related = ("area",)
	fieldsets = (
		(None, {
			"fields": ("area", "name", "order", "overview", "evidence_criteria"),
		}),
		("Grade descriptors — standard areas", {
			"classes": ("collapse",),
			"fields": (
				"urgent_improvement_descriptor",
				"needs_attention_descriptor",
				"expected_descriptor",
				"strong_descriptor",
				"exceptional_descriptor",
			),
		}),
		("Grade descriptors — safeguarding", {
			"classes": ("collapse",),
			"fields": ("not_met_descriptor", "met_descriptor"),
		}),
	)

	def written_work_count(self, obj) -> int:
		return InDepthResponse.objects.filter(subsection=obj).count()


@admin.register(InDepthReview)
class InDepthReviewAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	list_display = ("school", "year", "area", "step", "overall_grade", "has_reflection", "updated_at", "updated_by")
	list_filter = ("year", "area", "school", "step")
	ordering = ("-year", "school__name", "area__order", "area__name")
	list_select_related = ("school", "area", "updated_by")
	readonly_fields = ("created_at", "updated_at", "updated_by")
	fieldsets = (
		(None, {
			"fields": ("school", "year", "area", "step", "overall_grade"),
		}),
		("Reflection on QA & Feedback", {
			"fields": ("qa_reflection",),
		}),
		("Audit", {
			"fields": ("created_at", "updated_at", "updated_by"),
		}),
	)

	@admin.display(boolean=True, description="Reflection")
	def has_reflection(self, obj):
		return bool(obj.qa_reflection)

	def save_model(self, request, obj, form, change):
		obj.updated_by = request.user
		super().save_model(request, obj, form, change)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(InDepthResponse)
class InDepthResponseAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	history_school_path = "review__school"
	list_display = ("review", "judgement_area", "subsection", "rag", "grade", "updated_at")
	list_filter = ("rag", "grade", "judgement_area__standard__area", "subsection__area")
	search_fields = ("evidence_text", "next_steps", "subsection__name", "judgement_area__statement")
	list_select_related = ("review", "subsection", "subsection__area", "judgement_area")

	def get_queryset(self, request):
		# This admin holds the evidence text itself, and was the one school-linked
		# admin with no scoping — an is_staff account with change_indepthresponse
		# read every school's write-ups here. Scoped through the review, matching
		# InDepthReviewAdmin above.
		qs = super().get_queryset(request)
		return qs.filter(review__school__in=_request_schools(request))


@admin.register(InDepthStandard)
class InDepthStandardAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("area", "key", "order", "judgement_area_count")
	list_filter = ("area", "key")
	ordering = ("area__order", "order")
	list_select_related = ("area",)
	search_fields = ("area__name", "focus")

	@admin.display(description="Judgement areas")
	def judgement_area_count(self, obj):
		return obj.judgement_areas.count()

	def written_work_count(self, obj) -> int:
		return InDepthResponse.objects.filter(judgement_area__standard=obj).count()


@admin.register(InDepthJudgementArea)
class InDepthJudgementAreaAdmin(ProtectsWrittenWorkMixin, admin.ModelAdmin):
	list_display = ("standard", "order", "is_flat", "short_statement")
	list_filter = ("is_flat", "standard__area", "standard__key")
	ordering = ("standard__area__order", "standard__order", "order")
	list_select_related = ("standard", "standard__area")
	search_fields = ("statement",)

	@admin.display(description="Statement")
	def short_statement(self, obj):
		return obj.statement[:80]

	def written_work_count(self, obj) -> int:
		return obj.responses.count()



@admin.register(TrustCategory)
class TrustCategoryAdmin(admin.ModelAdmin):
	"""The shared 14-value list. Not the same thing as Category."""

	list_display = ("order", "display_name", "group", "routes_to")
	list_filter = ("group", "routes_to")
	list_editable = ("routes_to",)
	ordering = ("order", "id")
	list_select_related = ("indepth_area",)

	@admin.display(description="Name", ordering="order")
	def display_name(self, obj):
		return obj.name

	def get_readonly_fields(self, request, obj=None):
		# The nine evaluation-area rows take their name from InDepthArea; editing
		# the link here would fork the list.
		if obj is not None and obj.indepth_area_id:
			return ("indepth_area", "domain_key", "domain_name")
		return ()


@admin.register(RiskSettings)
class RiskSettingsAdmin(admin.ModelAdmin):
	list_display = ("__str__", "escalate_bands", "escalate_persisting_amber")

	def has_add_permission(self, request):
		if RiskSettings.objects.exists():
			return False
		return super().has_add_permission(request)

	def has_delete_permission(self, request, obj=None):
		return False


class RiskRatingInline(admin.TabularInline):
	model = RiskRating
	extra = 0
	fields = ("period", "impact", "likelihood", "band", "note", "qa_by", "qa_at")
	readonly_fields = ("band",)
	ordering = ("-period__year", "-period__round")


@admin.register(Risk)
class RiskAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	list_display = (
		"title",
		"school",
		"category",
		"route",
		"status",
		"owner",
		"review_point",
		"updated_at",
	)
	list_filter = ("status", "school", "category__group", "category")
	search_fields = ("title", "mitigation", "owner", "close_reason")
	list_select_related = ("school", "category", "category__indepth_area")
	readonly_fields = ("created_by", "created_at", "updated_at")
	inlines = [RiskRatingInline]
	fieldsets = (
		(None, {
			"fields": ("school", "category", "title", "mitigation", "owner", "review_point"),
		}),
		("Status", {
			"fields": ("status", "opened_period", "closed_at", "closed_by", "close_reason"),
		}),
		("CFO sign-off", {
			"fields": ("close_qa_by", "close_qa_at"),
		}),
		("Audit", {
			"fields": ("created_by", "created_at", "updated_at"),
		}),
	)

	@admin.display(description="Routes to")
	def route(self, obj):
		return obj.route

	def save_model(self, request, obj, form, change):
		if not change:
			obj.created_by = request.user
		super().save_model(request, obj, form, change)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(RiskRating)
class RiskRatingAdmin(admin.ModelAdmin):
	list_display = ("risk", "period", "impact", "likelihood", "band", "qa_by", "qa_at")
	list_filter = ("band", "impact", "likelihood", "period", "risk__school")
	search_fields = ("risk__title", "note")
	list_select_related = ("risk", "risk__school", "period")
	# Derived from the matrix on every save — never editable by hand.
	readonly_fields = ("band", "recorded_at")

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(risk__school__in=_request_schools(request))



class OperationsMetricBandInline(admin.TabularInline):
	model = OperationsMetricBand
	extra = 0
	fields = (
		"phase",
		"green_descriptor", "amber_descriptor", "red_descriptor",
		"green_min", "green_max", "amber_min", "amber_max", "amber_tolerance",
		"comparator_value", "comparator_year", "comparator_source",
		"step_change",
	)


@admin.register(OperationsMetric)
class OperationsMetricAdmin(admin.ModelAdmin):
	list_display = ("order", "name", "domain", "rule", "evidence", "cycle", "band_count")
	list_filter = ("domain", "evidence", "cycle", "rule")
	ordering = ("domain__order", "order")
	search_fields = ("name", "key", "benchmark_source")
	list_select_related = ("domain",)
	prepopulated_fields = {"key": ("name",)}
	inlines = [OperationsMetricBandInline]

	@admin.display(description="Bands")
	def band_count(self, obj):
		phases = [b.get_phase_display() or "All" for b in obj.bands.all()]
		return ", ".join(phases) or "—"


class VisibilityGridForm(forms.Form):
	school = forms.ModelChoiceField(queryset=School.objects.none(), label="School")
	year = forms.ChoiceField(label="Academic year")

	def __init__(self, *args, schools=None, years=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields["school"].queryset = schools if schools is not None else School.objects.none()
		self.fields["year"].choices = years or []


@admin.register(OperationsMetricVisibility)
class OperationsMetricVisibilityAdmin(admin.ModelAdmin):
	"""Per-school pilot switches.

	The grid view is the one the client will actually use between terms: pick a
	school and a year, tick what is in the pilot, save. No deploy involved.
	"""

	change_list_template = "admin/review/operationsmetricvisibility/change_list.html"
	list_display = ("school", "academic_year", "metric", "is_visible")
	list_filter = ("is_visible", "school", "year", "metric__domain")
	list_editable = ("is_visible",)
	list_display_links = ("metric",)
	ordering = ("school__name", "-year", "metric__order")
	list_select_related = ("school", "metric", "metric__domain")

	@admin.display(description="Academic year", ordering="year")
	def academic_year(self, obj):
		return f"{obj.year}/{obj.year + 1}"

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))

	def get_urls(self):
		urls = super().get_urls()
		custom = [
			path(
				"grid/",
				self.admin_site.admin_view(self.grid_view),
				name="review_operationsmetricvisibility_grid",
			),
		]
		return custom + urls

	def grid_view(self, request):
		schools = _request_schools(request).order_by("name")
		if not schools.exists():
			raise PermissionDenied

		this_year = current_academic_year_start()
		start = max(MIN_ACADEMIC_YEAR_START, this_year - 1)
		years = [(str(y), f"{y}/{y + 1}") for y in range(start, this_year + 3)]

		data = request.POST if request.method == "POST" else request.GET
		selector = VisibilityGridForm(
			data if data else None, schools=schools, years=years
		)

		school = None
		year = max(this_year, MIN_ACADEMIC_YEAR_START)
		if selector.is_bound and selector.is_valid():
			school = selector.cleaned_data["school"]
			year = int(selector.cleaned_data["year"])
		else:
			school = schools.first()
			selector = VisibilityGridForm(
				initial={"school": school, "year": str(year)}, schools=schools, years=years
			)

		metrics = list(
			OperationsMetric.objects.select_related("domain").order_by(
				"domain__order", "order"
			)
		)

		if request.method == "POST" and request.POST.get("action") == "save" and school:
			wanted = {
				int(v) for v in request.POST.getlist("visible") if str(v).isdigit()
			}
			with transaction.atomic():
				for metric in metrics:
					OperationsMetricVisibility.objects.update_or_create(
						school=school,
						year=year,
						metric=metric,
						defaults={"is_visible": metric.id in wanted},
					)
			self.message_user(
				request,
				f"Saved. {len(wanted)} of {len(metrics)} metrics visible for "
				f"{school.name} in {year}/{year + 1}.",
			)
			return redirect(
				f"{request.path}?school={school.id}&year={year}"
			)

		visible_ids = set(
			OperationsMetricVisibility.objects.filter(
				school=school, year=year, is_visible=True
			).values_list("metric_id", flat=True)
		)

		grouped = []
		for metric in metrics:
			if not grouped or grouped[-1]["domain"].id != metric.domain_id:
				grouped.append({"domain": metric.domain, "metrics": []})
			grouped[-1]["metrics"].append(
				{"metric": metric, "is_visible": metric.id in visible_ids}
			)

		context = {
			**self.admin_site.each_context(request),
			"opts": self.model._meta,
			"title": "Operations & Resources — pilot visibility",
			"selector": selector,
			"school": school,
			"year": year,
			"year_label": f"{year}/{year + 1}",
			"grouped": grouped,
			"visible_count": len(visible_ids),
			"total_count": len(metrics),
		}
		return render(
			request, "admin/review/operationsmetricvisibility/grid.html", context
		)


@admin.register(OperationsEntry)
class OperationsEntryAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	list_display = ("school", "period", "metric", "value", "band_choice", "rag", "source", "recorded_at")
	list_filter = ("rag", "source", "school", "period", "metric__domain", "metric")
	search_fields = ("commentary", "manual_red_reason", "metric__name")
	list_select_related = ("school", "period", "metric")
	# Derived from the metric's rule and bands on every save.
	readonly_fields = ("rag", "recorded_at")

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(ComplaintTheme)
class ComplaintThemeAdmin(admin.ModelAdmin):
	list_display = ("order", "name", "is_active")
	list_editable = ("is_active",)
	list_display_links = ("name",)
	ordering = ("order", "name")


@admin.register(StatutoryComplianceItem)
class StatutoryComplianceItemAdmin(admin.ModelAdmin):
	list_display = ("school", "label", "next_due_date", "action_plan_in_place", "updated_at")
	list_filter = ("school", "item", "action_plan_in_place")
	ordering = ("school__name", "item")
	list_select_related = ("school",)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(GrantPublication)
class GrantPublicationAdmin(admin.ModelAdmin):
	list_display = ("school", "year", "label", "status", "updated_at")
	list_filter = ("school", "year", "grant", "status")
	ordering = ("school__name", "-year", "grant")
	list_select_related = ("school",)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(OperationsNote)
class OperationsNoteAdmin(ScopedHistoryAdminMixin, SimpleHistoryAdmin):
	list_display = ("school", "period", "updated_at", "updated_by")
	list_filter = ("school", "period")
	search_fields = ("text",)
	list_select_related = ("school", "period", "updated_by")
	readonly_fields = ("updated_at", "updated_by")

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


class SchoolProfileInline(admin.StackedInline):
	model = SchoolProfile
	can_delete = False
	extra = 0
	max_num = 1

	def get_formset(self, request, obj=None, **kwargs):
		formset = super().get_formset(request, obj, **kwargs)
		if not request.user.is_superuser and "school" in formset.form.base_fields:
			formset.form.base_fields["school"].widget = forms.HiddenInput()
		return formset


class UserImportForm(forms.Form):
	csv_file = forms.FileField(
		label="CSV file",
		help_text=(
			"Upload a CSV with two columns: "
			"<strong>email</strong> and <strong>school</strong>. "
			"Include a header row. One row per user per school."
		),
	)


class SSOUserCreationForm(forms.ModelForm):
	password1 = forms.CharField(
		label="Password",
		required=False,
		strip=False,
		widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
	)
	password2 = forms.CharField(
		label="Password confirmation",
		required=False,
		strip=False,
		widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
	)

	class Meta:
		model = User
		fields = ("username", "email", "first_name", "last_name", "is_active")

	def clean(self):
		cleaned_data = super().clean()
		password1 = cleaned_data.get("password1")
		password2 = cleaned_data.get("password2")

		# If left blank, we will create an unusable password (SSO-only).
		if not password1 and not password2:
			return cleaned_data

		if password1 != password2:
			raise ValidationError("Passwords do not match")
		if password1:
			validate_password(password1)
		return cleaned_data

	def save(self, commit=True):
		user = super().save(commit=False)
		password1 = self.cleaned_data.get("password1")
		if password1:
			user.set_password(password1)
		else:
			user.set_unusable_password()
		if commit:
			user.save()
		return user


class UserAdmin(DjangoUserAdmin):
	change_list_template = "admin/review/user/change_list.html"

	def get_urls(self):
		urls = super().get_urls()
		custom = [
			path(
				"import-users/",
				self.admin_site.admin_view(self.import_users_view),
				name="auth_user_import",
			),
		]
		return custom + urls

	def import_users_view(self, request):
		if not request.user.is_superuser:
			raise PermissionDenied

		results = None
		form = UserImportForm()

		if request.method == "POST":
			form = UserImportForm(request.POST, request.FILES)
			if form.is_valid():
				raw = request.FILES["csv_file"].read()
				try:
					text = raw.decode("utf-8-sig")
				except UnicodeDecodeError:
					text = raw.decode("latin-1")

				reader = csv.DictReader(io.StringIO(text))
				rows = list(reader)
				created_count = 0
				updated_count = 0
				errors = []

				with transaction.atomic():
					for i, row in enumerate(rows, start=2):
						norm = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
						email = norm.get("email", "").lower()
						school_name = norm.get("school", "") or norm.get("school_name", "")

						if not email:
							errors.append(f"Row {i}: missing email \u2014 skipped.")
							continue
						if not school_name:
							errors.append(f"Row {i}: missing school for {email} \u2014 skipped.")
							continue

						try:
							school = School.objects.get(name__iexact=school_name)
						except School.DoesNotExist:
							errors.append(f'Row {i}: school not found: "{school_name}" \u2014 skipped.')
							continue

						user = User.objects.filter(email__iexact=email).first()
						if user is None:
							user = User(username=email[:150], email=email, is_active=True)
							user.set_unusable_password()
							user.save()
							created_count += 1
						else:
							updated_count += 1

						profile, _ = SchoolProfile.objects.get_or_create(
							user=user,
							defaults={"school": school},
						)
						profile.schools.add(school)

				results = {
					"created": created_count,
					"updated": updated_count,
					"errors": errors,
					"total": len(rows),
				}

		context = {
			**self.admin_site.each_context(request),
			"opts": self.model._meta,
			"title": "Import users from CSV",
			"form": form,
			"results": results,
		}
		return render(request, "admin/review/user/import_users.html", context)

	@admin.display(description="Schools")
	def schools_access(self, obj: User):
		try:
			profile = obj.schoolprofile
		except SchoolProfile.DoesNotExist:
			return "—"
		schools = list(profile.schools.order_by("name").values_list("name", flat=True))
		if profile.school_id and profile.school.name not in schools:
			schools.insert(0, profile.school.name)
		return ", ".join(schools) if schools else "—"

	inlines = [SchoolProfileInline]
	list_display = ("username", "email", "first_name", "last_name", "is_active", "schools_access")
	add_form = SSOUserCreationForm
	add_fieldsets = (
		(
			None,
			{
				"classes": ("wide",),
				"fields": ("username", "email", "first_name", "last_name", "password1", "password2", "is_active"),
			},
		),
	)

	def get_queryset(self, request):
		qs = (
			super()
			.get_queryset(request)
			.select_related("schoolprofile", "schoolprofile__school")
			.prefetch_related("schoolprofile__schools")
		)
		if request.user.is_superuser:
			return qs
		school_qs = _request_schools(request)
		if not school_qs.exists():
			return qs.none()
		return qs.filter(
			Q(schoolprofile__school__in=school_qs) | Q(schoolprofile__schools__in=school_qs)
		).distinct()

	def get_fieldsets(self, request, obj=None):
		if request.user.is_superuser:
			return super().get_fieldsets(request, obj)
		return (
			(None, {"fields": ("username", "password")}),
			("Personal info", {"fields": ("first_name", "last_name", "email")}),
			("Status", {"fields": ("is_active",)}),
		)

	def get_form(self, request, obj=None, **kwargs):
		form = super().get_form(request, obj, **kwargs)
		if not request.user.is_superuser:
			for field_name in ("is_staff", "is_superuser", "user_permissions", "groups"):
				if field_name in form.base_fields:
					form.base_fields.pop(field_name)
		return form

	def save_model(self, request, obj, form, change):
		if not request.user.is_superuser:
			obj.is_staff = False
			obj.is_superuser = False
		super().save_model(request, obj, form, change)

	def save_formset(self, request, form, formset, change):
		instances = formset.save(commit=False)
		first = None if request.user.is_superuser else _request_schools(request).order_by("name").first()
		for inst in instances:
			if isinstance(inst, SchoolProfile) and first is not None:
				inst.school = first
			inst.save()
		formset.save_m2m()
		for inst in instances:
			if isinstance(inst, SchoolProfile) and inst.school_id:
				inst.schools.add(inst.school)


try:
	admin.site.unregister(User)
except admin.sites.NotRegistered:
	pass
admin.site.register(User, UserAdmin)
