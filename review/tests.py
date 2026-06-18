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
from .views import conclude_indepth_grade


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

		resp = self.client.get(reverse("review:dashboard"), {"year": "2026-2027"})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(ReviewPeriod.objects.count(), initial_count)

	def test_viewer_dashboard_post_is_blocked(self):
		self.client.force_login(self.viewer)
		self.assertEqual(Evaluation.objects.count(), 0)

		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
			},
		)
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(Evaluation.objects.count(), 0)

	def test_viewer_indepth_get_does_not_create_review(self):
		self.client.force_login(self.viewer)
		self.assertEqual(InDepthReview.objects.count(), 0)

		resp = self.client.get(
			reverse("review:indepth_review"),
			{"year": "2026-2027", "area": str(self.area.id)},
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
		resp = self.client.get(reverse("review:dashboard"), {"year": "2026-2027"})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(ReviewPeriod.objects.filter(year=2026).count(), 3)

		# POST a valid formset for 1 category x 3 rounds.
		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
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
		resp = self.client.get(reverse("review:dashboard"), {"year": "2026-2027"})
		self.assertEqual(resp.status_code, 200)

		# Invalid: Safeguarding cannot be rated 2/3/4.
		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
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
				"year": "2026-2027",
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
			period__year=2026,
			period__round=1,
		)
		self.assertEqual(saved.rating, 1)



class ConcludeGradeTests(TestCase):
	"""The pure RAG-ladder grade computation (views.conclude_indepth_grade)."""

	def test_expected_incomplete_is_unconcluded(self):
		self.assertEqual(conclude_indepth_grade({"expected_standard": ["green", ""]}), "")

	def test_expected_amber_stays_expected(self):
		self.assertEqual(
			conclude_indepth_grade({"expected_standard": ["green", "amber"]}),
			"expected_standard",
		)

	def test_down_path_all_red_is_needs_attention(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["red", "green"],
				"urgent_improvement": ["red", "red"],
			}),
			"needs_attention",
		)

	def test_down_path_any_non_red_is_urgent_improvement(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["red"],
				"urgent_improvement": ["red", "green"],
			}),
			"urgent_improvement",
		)

	def test_down_path_incomplete_is_unconcluded(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["red"],
				"urgent_improvement": ["red", ""],
			}),
			"",
		)

	def test_down_path_without_urgent_rung_falls_to_needs_attention(self):
		self.assertEqual(conclude_indepth_grade({"expected_standard": ["red"]}), "needs_attention")

	def test_up_path_strong_red_drops_to_expected(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green", "green"],
				"strong_standard": ["green", "red"],
			}),
			"expected_standard",
		)

	def test_up_path_strong_amber_is_strong(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green"],
				"strong_standard": ["green", "amber"],
			}),
			"strong_standard",
		)

	def test_up_path_exceptional_red_drops_to_strong(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green"],
				"strong_standard": ["green"],
				"exceptional": ["green", "red"],
			}),
			"strong_standard",
		)

	def test_up_path_all_green_through_exceptional(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green"],
				"strong_standard": ["green"],
				"exceptional": ["green", "green"],
			}),
			"exceptional",
		)

	def test_exceptional_amber_is_exceptional(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green"],
				"strong_standard": ["green"],
				"exceptional": ["amber"],
			}),
			"exceptional",
		)

	def test_no_exceptional_rung_tops_out_at_strong(self):
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["green"],
				"strong_standard": ["green"],
			}),
			"strong_standard",
		)

	def test_safeguarding_met_and_not_met(self):
		self.assertEqual(
			conclude_indepth_grade({"met": ["green", "amber"]}, is_safeguarding=True), "met"
		)
		self.assertEqual(
			conclude_indepth_grade({"met": ["green", "red"]}, is_safeguarding=True), "not_met"
		)
		self.assertEqual(
			conclude_indepth_grade({"met": ["green", ""]}, is_safeguarding=True), ""
		)


class InDepthJudgementAreaFlowTests(TestCase):
	"""The two-page (ratings -> commentary) review flow."""

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
		expected = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.je1 = InDepthJudgementArea.objects.create(
			standard=expected, statement="Pupils achieve well.", order=1
		)
		self.je2 = InDepthJudgementArea.objects.create(
			standard=expected, statement="Pupils are ready for the next stage.", order=2
		)
		strong = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.STRONG_STANDARD, order=4
		)
		self.js1 = InDepthJudgementArea.objects.create(
			standard=strong, statement="Achievement is exceptional over time.", order=1
		)
		exc = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXCEPTIONAL, order=5
		)
		self.jx1 = InDepthJudgementArea.objects.create(
			standard=exc, statement="Transformational outcomes are sustained.", order=1
		)
		ui = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.URGENT_IMPROVEMENT, order=1
		)
		self.ju1 = InDepthJudgementArea.objects.create(
			standard=ui, statement="Pupils lack foundations.", order=1
		)

	def _rag_post(self, rags, save_continue=False):
		"""rags: list of (judgement_area, rag_value)."""
		data = {
			"school_id": str(self.school.id),
			"year": "2026-2027",
			"area_id": str(self.area.id),
			"page": "rag",
			"form-TOTAL_FORMS": str(len(rags)),
			"form-INITIAL_FORMS": str(len(rags)),
			"form-MIN_NUM_FORMS": "0",
			"form-MAX_NUM_FORMS": "1000",
		}
		for i, (ja, rag) in enumerate(rags):
			data[f"form-{i}-judgement_area_id"] = str(ja.id)
			data[f"form-{i}-rag"] = rag
			data[f"form-{i}-commentary"] = ""
			data[f"form-{i}-next_steps"] = ""
		if save_continue:
			data["save_continue"] = "1"
		url = f"{reverse('review:indepth_review')}?area={self.area.id}&page=rag"
		return self.client.post(url, data=data)

	def _commentary_post(self, items):
		"""items: list of (judgement_area, commentary, next_steps)."""
		data = {
			"school_id": str(self.school.id),
			"year": "2026-2027",
			"area_id": str(self.area.id),
			"page": "commentary",
			"form-TOTAL_FORMS": str(len(items)),
			"form-INITIAL_FORMS": str(len(items)),
			"form-MIN_NUM_FORMS": "0",
			"form-MAX_NUM_FORMS": "1000",
		}
		for i, (ja, commentary, next_steps) in enumerate(items):
			data[f"form-{i}-judgement_area_id"] = str(ja.id)
			data[f"form-{i}-rag"] = ""
			data[f"form-{i}-commentary"] = commentary
			data[f"form-{i}-next_steps"] = next_steps
		url = f"{reverse('review:indepth_review')}?area={self.area.id}&page=commentary"
		return self.client.post(url, data=data)

	def _review(self):
		return InDepthReview.objects.get(school=self.school, year=2026, area=self.area)

	def test_rag_concludes_exceptional_and_saves_ratings(self):
		self.client.force_login(self.staff)
		resp = self._rag_post([
			(self.je1, "green"), (self.je2, "green"),
			(self.js1, "green"), (self.jx1, "green"),
		])
		self.assertEqual(resp.status_code, 302)
		review = self._review()
		self.assertEqual(review.overall_grade, "exceptional")
		self.assertEqual(
			InDepthResponse.objects.get(review=review, judgement_area=self.je1).rag, "green"
		)

	def test_rag_down_path_all_red_is_needs_attention(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green"), (self.ju1, "red")])
		self.assertEqual(self._review().overall_grade, "needs_attention")

	def test_rag_down_path_non_red_is_urgent_improvement(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green"), (self.ju1, "green")])
		self.assertEqual(self._review().overall_grade, "urgent_improvement")

	def test_rag_expected_amber_stays_expected(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		self.assertEqual(self._review().overall_grade, "expected_standard")

	def test_save_continue_redirects_to_commentary(self):
		self.client.force_login(self.staff)
		resp = self._rag_post(
			[(self.je1, "green"), (self.je2, "green"), (self.js1, "amber")],
			save_continue=True,
		)
		self.assertEqual(resp.status_code, 302)
		self.assertIn("page=commentary", resp["Location"])

	def test_commentary_saves_and_preserves_rag(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		resp = self._commentary_post([
			(self.je1, "Strong, triangulated evidence.", "Sustain and share practice."),
			(self.je2, "Some gaps remain.", "Close the gaps."),
		])
		self.assertEqual(resp.status_code, 302)
		r1 = InDepthResponse.objects.get(review=self._review(), judgement_area=self.je1)
		self.assertEqual(r1.evidence_text, "Strong, triangulated evidence.")
		self.assertEqual(r1.next_steps, "Sustain and share practice.")
		self.assertEqual(r1.rag, "green")  # carried over, untouched

	def test_commentary_shows_only_awarded_band_statements(self):
		# Expected all green + Strong amber -> grade lands on Strong, so commentary
		# asks for write-ups on the Strong statement only, not the Expected ones.
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "green"), (self.js1, "amber")])
		self.assertEqual(self._review().overall_grade, "strong_standard")
		url = f"{reverse('review:indepth_review')}?area={self.area.id}&page=commentary"
		resp = self.client.get(url)
		shown = {
			row["ja"].id
			for block in resp.context["rich_blocks"]
			for row in block["rows"]
		}
		self.assertEqual(shown, {self.js1.id})

	def test_commentary_word_limit_blocks_save(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		resp = self._commentary_post([(self.je1, " ".join(["word"] * 151), "")])
		self.assertEqual(resp.status_code, 200)
		r1 = InDepthResponse.objects.get(review=self._review(), judgement_area=self.je1)
		self.assertEqual(r1.evidence_text, "")

	def test_changing_path_clears_abandoned_branch_on_save(self):
		self.client.force_login(self.staff)
		# Up-path first: Expected all green + Strong rated.
		self._rag_post([
			(self.je1, "green"), (self.je2, "green"), (self.js1, "green"),
		])
		review = self._review()
		self.assertTrue(
			InDepthResponse.objects.filter(review=review, judgement_area=self.js1).exists()
		)
		# Re-save dropping to the down-path; the Strong rating is submitted blank.
		self._rag_post([
			(self.je1, "red"), (self.je2, "green"),
			(self.js1, ""), (self.ju1, "red"),
		])
		self.assertFalse(
			InDepthResponse.objects.filter(review=review, judgement_area=self.js1).exists()
		)
		self.assertEqual(self._review().overall_grade, "needs_attention")

	def test_blank_rag_creates_no_response_rows(self):
		self.client.force_login(self.staff)
		resp = self._rag_post([(self.je1, ""), (self.je2, "")])
		self.assertEqual(resp.status_code, 302)
		review = self._review()
		self.assertEqual(InDepthResponse.objects.filter(review=review).count(), 0)
		self.assertEqual(review.overall_grade, "")
