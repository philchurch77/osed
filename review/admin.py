from __future__ import annotations

import csv
import io

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import path

from .models import (
	Branding,
	Category,
	Evaluation,
	InDepthArea,
	InDepthJudgementArea,
	InDepthResponse,
	InDepthReview,
	InDepthStandard,
	InDepthSubSection,
	ReviewPeriod,
	School,
	SchoolProfile,
)


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


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	list_display = ("order", "name", "is_active")
	list_filter = ("is_active",)
	ordering = ("-is_active", "order", "name")
	search_fields = ("name",)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
	list_display = ("name", "phase", "logo")
	search_fields = ("name",)

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
class ReviewPeriodAdmin(admin.ModelAdmin):
	list_display = ("year", "round")
	list_filter = ("year", "round")
	ordering = ("-year", "round")


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
	list_display = (
		"school",
		"period",
		"category",
		"rating",
		"updated_at",
		"updated_by",
	)
	list_filter = ("school", "period", "category")
	search_fields = ("category__name", "judgement_evidence", "to_progress")
	list_select_related = ("school", "period", "category")
	readonly_fields = ("created_at", "updated_at", "updated_by")

	def save_model(self, request, obj, form, change):
		obj.updated_by = request.user
		super().save_model(request, obj, form, change)

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		return qs.filter(school__in=_request_schools(request))


@admin.register(InDepthArea)
class InDepthAreaAdmin(admin.ModelAdmin):
	list_display = ("order", "name", "is_safeguarding")
	list_filter = ("is_safeguarding",)
	ordering = ("order", "name")
	search_fields = ("name",)
	fieldsets = (
		(None, {
			"fields": ("name", "order", "is_safeguarding", "purpose"),
		}),
	)


@admin.register(InDepthSubSection)
class InDepthSubSectionAdmin(admin.ModelAdmin):
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


@admin.register(InDepthReview)
class InDepthReviewAdmin(admin.ModelAdmin):
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
class InDepthResponseAdmin(admin.ModelAdmin):
	list_display = ("review", "judgement_area", "subsection", "rag", "grade", "updated_at")
	list_filter = ("rag", "grade", "judgement_area__standard__area", "subsection__area")
	search_fields = ("evidence_text", "next_steps", "subsection__name", "judgement_area__statement")
	list_select_related = ("review", "subsection", "subsection__area", "judgement_area")


@admin.register(InDepthStandard)
class InDepthStandardAdmin(admin.ModelAdmin):
	list_display = ("area", "key", "order", "judgement_area_count")
	list_filter = ("area", "key")
	ordering = ("area__order", "order")
	list_select_related = ("area",)
	search_fields = ("area__name", "focus")

	@admin.display(description="Judgement areas")
	def judgement_area_count(self, obj):
		return obj.judgement_areas.count()


@admin.register(InDepthJudgementArea)
class InDepthJudgementAreaAdmin(admin.ModelAdmin):
	list_display = ("standard", "order", "is_flat", "short_statement")
	list_filter = ("is_flat", "standard__area", "standard__key")
	ordering = ("standard__area__order", "standard__order", "order")
	list_select_related = ("standard", "standard__area")
	search_fields = ("statement",)

	@admin.display(description="Statement")
	def short_statement(self, obj):
		return obj.statement[:80]


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
