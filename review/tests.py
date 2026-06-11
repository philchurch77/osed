from __future__ import annotations

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from .models import (
	Category,
	Evaluation,
	InDepthArea,
	InDepthReview,
	InDepthSubSection,
	ReviewPeriod,
	School,
	SchoolProfile,
)


class ViewerAccessTests(TestCase):
	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)

		self.viewer = User.objects.create_user(username="viewer", email="viewer@example.com")
		SchoolProfile.objects.create(user=self.viewer, school=self.school)
		self.viewer.schoolprofile.schools.add(self.school)

		self.area = InDepthArea.objects.create(name="Quality of education", order=1)
		InDepthSubSection.objects.create(area=self.area, name="Sub-section 1", order=1)

	def test_viewer_dashboard_get_does_not_create_periods(self):
		self.client.force_login(self.viewer)
		initial_count = ReviewPeriod.objects.count()

		resp = self.client.get(reverse("review:dashboard"), {"year": "2025-2026"})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(ReviewPeriod.objects.count(), initial_count)

	def test_viewer_dashboard_post_is_blocked(self):
		self.client.force_login(self.viewer)
		self.assertEqual(Evaluation.objects.count(), 0)

		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2025-2026",
			},
		)
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(Evaluation.objects.count(), 0)

	def test_viewer_indepth_get_does_not_create_review(self):
		self.client.force_login(self.viewer)
		self.assertEqual(InDepthReview.objects.count(), 0)

		resp = self.client.get(
			reverse("review:indepth_review"),
			{"year": "2025-2026", "area": str(self.area.id)},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(InDepthReview.objects.count(), 0)


class StaffEditTests(TestCase):
	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)

		self.staff = User.objects.create_user(username="staff", email="staff@example.com")
		SchoolProfile.objects.create(user=self.staff, school=self.school)
		self.staff.schoolprofile.schools.add(self.school)

		add_eval = Permission.objects.get(content_type__app_label="review", codename="add_evaluation")
		change_eval = Permission.objects.get(content_type__app_label="review", codename="change_evaluation")
		self.staff.user_permissions.add(add_eval, change_eval)

	def test_staff_can_post_dashboard_and_creates_periods(self):
		self.client.force_login(self.staff)

		# GET should create periods for editors.
		resp = self.client.get(reverse("review:dashboard"), {"year": "2025-2026"})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(ReviewPeriod.objects.filter(year=2025).count(), 3)

		# POST a valid formset for 1 category x 3 rounds.
		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2025-2026",
				"form-TOTAL_FORMS": "3",
				"form-INITIAL_FORMS": "0",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				"form-0-category_id": str(self.category.id),
				"form-0-round": "1",
				"form-0-rating": "3",
				"form-1-category_id": str(self.category.id),
				"form-1-round": "2",
				"form-1-rating": "",
				"form-2-category_id": str(self.category.id),
				"form-2-round": "3",
				"form-2-rating": "",
			},
		)
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(Evaluation.objects.filter(school=self.school).exists())

	def test_staff_dashboard_safeguarding_allows_only_met_or_not_met(self):
		safeguarding = Category.objects.create(name="Safeguarding", order=0, is_active=True)
		self.client.force_login(self.staff)

		# Create periods for editors.
		resp = self.client.get(reverse("review:dashboard"), {"year": "2025-2026"})
		self.assertEqual(resp.status_code, 200)

		# Invalid: Safeguarding cannot be rated 2/3/4.
		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2025-2026",
				"form-TOTAL_FORMS": "6",
				"form-INITIAL_FORMS": "0",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				# Safeguarding x 3 rounds
				"form-0-category_id": str(safeguarding.id),
				"form-0-round": "1",
				"form-0-rating": "2",
				"form-1-category_id": str(safeguarding.id),
				"form-1-round": "2",
				"form-1-rating": "",
				"form-2-category_id": str(safeguarding.id),
				"form-2-round": "3",
				"form-2-rating": "",
				# Leadership x 3 rounds
				"form-3-category_id": str(self.category.id),
				"form-3-round": "1",
				"form-3-rating": "3",
				"form-4-category_id": str(self.category.id),
				"form-4-round": "2",
				"form-4-rating": "",
				"form-5-category_id": str(self.category.id),
				"form-5-round": "3",
				"form-5-rating": "",
			},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(Evaluation.objects.count(), 0)

		# Valid: Safeguarding can be rated 1 (Met).
		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2025-2026",
				"form-TOTAL_FORMS": "6",
				"form-INITIAL_FORMS": "0",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				# Safeguarding x 3 rounds
				"form-0-category_id": str(safeguarding.id),
				"form-0-round": "1",
				"form-0-rating": "1",
				"form-1-category_id": str(safeguarding.id),
				"form-1-round": "2",
				"form-1-rating": "",
				"form-2-category_id": str(safeguarding.id),
				"form-2-round": "3",
				"form-2-rating": "",
				# Leadership x 3 rounds
				"form-3-category_id": str(self.category.id),
				"form-3-round": "1",
				"form-3-rating": "3",
				"form-4-category_id": str(self.category.id),
				"form-4-round": "2",
				"form-4-rating": "",
				"form-5-category_id": str(self.category.id),
				"form-5-round": "3",
				"form-5-rating": "",
			},
		)
		self.assertEqual(resp.status_code, 302)
		saved = Evaluation.objects.get(
			school=self.school,
			category=safeguarding,
			period__year=2025,
			period__round=1,
		)
		self.assertEqual(saved.rating, 1)

