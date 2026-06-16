from __future__ import annotations

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from .models import (
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



class InDepthJudgementAreaFlowTests(TestCase):
	"""The new standard -> judgement-area review flow."""

	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.staff = User.objects.create_user(username="staff", email="staff@example.com")
		SchoolProfile.objects.create(user=self.staff, school=self.school)
		self.staff.schoolprofile.schools.add(self.school)
		for codename in ("add_indepthresponse", "change_indepthresponse"):
			self.staff.user_permissions.add(
				Permission.objects.get(content_type__app_label="review", codename=codename)
			)

		self.area = InDepthArea.objects.create(name="Achievement", order=4)
		self.expected = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.ja1 = InDepthJudgementArea.objects.create(
			standard=self.expected, statement="Pupils achieve well.", order=1
		)
		self.ja2 = InDepthJudgementArea.objects.create(
			standard=self.expected, statement="Pupils are ready for the next stage.", order=2
		)
		ui = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.URGENT_IMPROVEMENT, order=1
		)
		InDepthJudgementArea.objects.create(
			standard=ui, statement="Pupils lack foundations.", is_flat=True, order=1
		)

	def _post(self, **overrides):
		data = {
			"school_id": str(self.school.id),
			"year": "2025-2026",
			"area_id": str(self.area.id),
			"form-TOTAL_FORMS": "2",
			"form-INITIAL_FORMS": "2",
			"form-MIN_NUM_FORMS": "0",
			"form-MAX_NUM_FORMS": "1000",
			"form-0-judgement_area_id": str(self.ja1.id),
			"form-0-rag": "green",
			"form-0-commentary": "Strong, triangulated evidence.",
			"form-0-next_steps": "Sustain and share practice.",
			"form-1-judgement_area_id": str(self.ja2.id),
			"form-1-rag": "amber",
			"form-1-commentary": "Some gaps remain.",
			"form-1-next_steps": "Close the gaps.",
			"overall_grade": "expected_standard",
		}
		data.update(overrides)
		url = f"{reverse('review:indepth_review')}?area={self.area.id}"
		return self.client.post(url, data=data)

	def test_staff_saves_judgement_area_responses(self):
		self.client.force_login(self.staff)
		resp = self._post()
		self.assertEqual(resp.status_code, 302)

		review = InDepthReview.objects.get(school=self.school, year=2025, area=self.area)
		self.assertEqual(review.overall_grade, "expected_standard")

		responses = InDepthResponse.objects.filter(review=review, judgement_area__isnull=False)
		self.assertEqual(responses.count(), 2)
		r1 = responses.get(judgement_area=self.ja1)
		self.assertEqual(r1.rag, "green")
		self.assertEqual(r1.evidence_text, "Strong, triangulated evidence.")
		self.assertEqual(r1.grade, "")

	def test_resave_updates_without_duplicating(self):
		self.client.force_login(self.staff)
		self._post()
		self._post(**{"form-0-rag": "amber", "overall_grade": "strong_standard"})

		review = InDepthReview.objects.get(school=self.school, year=2025, area=self.area)
		self.assertEqual(InDepthResponse.objects.filter(review=review).count(), 2)
		self.assertEqual(review.overall_grade, "strong_standard")
		self.assertEqual(
			InDepthResponse.objects.get(review=review, judgement_area=self.ja1).rag, "amber"
		)

	def test_commentary_word_limit_blocks_save(self):
		self.client.force_login(self.staff)
		resp = self._post(**{"form-0-commentary": " ".join(["word"] * 151)})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(InDepthReview.objects.count(), 0)

	def test_blank_form_creates_no_response_rows(self):
		self.client.force_login(self.staff)
		resp = self._post(**{
			"form-0-rag": "", "form-0-commentary": "", "form-0-next_steps": "",
			"form-1-rag": "", "form-1-commentary": "", "form-1-next_steps": "",
			"overall_grade": "",
		})
		self.assertEqual(resp.status_code, 302)
		review = InDepthReview.objects.get(school=self.school, year=2025, area=self.area)
		self.assertEqual(InDepthResponse.objects.filter(review=review).count(), 0)

	def test_clearing_a_response_deletes_it(self):
		self.client.force_login(self.staff)
		self._post()
		review = InDepthReview.objects.get(school=self.school, year=2025, area=self.area)
		self.assertEqual(InDepthResponse.objects.filter(review=review).count(), 2)
		# Re-save with judgement area 1 fully cleared.
		self._post(**{"form-0-rag": "", "form-0-commentary": "", "form-0-next_steps": ""})
		self.assertFalse(
			InDepthResponse.objects.filter(review=review, judgement_area=self.ja1).exists()
		)
		self.assertTrue(
			InDepthResponse.objects.filter(review=review, judgement_area=self.ja2).exists()
		)

	def test_invalid_overall_grade_does_not_blank_existing(self):
		self.client.force_login(self.staff)
		self._post(**{"overall_grade": "expected_standard"})
		# A submission carrying an unrecognised grade must not wipe the saved one.
		self._post(**{"overall_grade": "bogus_value"})
		review = InDepthReview.objects.get(school=self.school, year=2025, area=self.area)
		self.assertEqual(review.overall_grade, "expected_standard")
