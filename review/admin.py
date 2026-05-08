from __future__ import annotations

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from django.core.exceptions import ValidationError

from .models import Branding, Category, Evaluation, ReviewPeriod, School, SchoolProfile


def _request_schools(request):
	"""Return a queryset of schools the user may access (or None for superusers)."""
	if request.user.is_superuser:
		return None
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
		school_qs = _request_schools(request)
		return qs if school_qs is None else qs.filter(id__in=school_qs)


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
		if school_qs is None:
			return qs
		return qs.filter(Q(school__in=school_qs) | Q(schools__in=school_qs)).distinct()

	def get_form(self, request, obj=None, **kwargs):
		form = super().get_form(request, obj, **kwargs)
		school_qs = _request_schools(request)
		if school_qs is not None and "school" in form.base_fields:
			form.base_fields["school"].disabled = True
		return form

	def save_model(self, request, obj, form, change):
		school_qs = _request_schools(request)
		if school_qs is not None:
			first = school_qs.order_by("name").first()
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
		school_qs = _request_schools(request)
		return qs if school_qs is None else qs.filter(school__in=school_qs)


class SchoolProfileInline(admin.StackedInline):
	model = SchoolProfile
	can_delete = False
	extra = 0
	max_num = 1

	def get_formset(self, request, obj=None, **kwargs):
		formset = super().get_formset(request, obj, **kwargs)
		school_qs = _request_schools(request)
		if school_qs is not None and "school" in formset.form.base_fields:
			formset.form.base_fields["school"].widget = forms.HiddenInput()
		return formset


class UserAdmin(DjangoUserAdmin):
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
		if school_qs is None or not school_qs.exists():
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
		school_qs = _request_schools(request)
		first = None if school_qs is None else school_qs.order_by("name").first()
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
