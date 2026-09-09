from __future__ import annotations

import importlib

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone

from .models import (
	Category,
	Evaluation,
	InDepthArea,
	InDepthJudgementArea,
	InDepthResponse,
	InDepthReview,
	InDepthStandard,
	InDepthSubSection,
	ComplaintTheme,
	GrantPublication,
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
)
from .management.commands._indepth_sync import sync_judgement_areas
from .operations import (
	GRANT_DRAFTED,
	GRANT_INCLUSIVE_MAINSTREAM,
	GRANT_MISSED,
	GRANT_PE_SPORT,
	GRANT_PUBLISHED,
	GRANT_PUPIL_PREMIUM,
	LEGEND_STANDING_TEXT,
	RULE_BAND_CHOICE,
	SMALL_PRINT,
	STATUTORY_ITEMS,
	applicable_grants,
	complaints_rag,
	grant_rag,
	statutory_rag,
)
from .permissions import user_can_qa_risk
from .risk import rag_for, trend_for
from .views import (
	_build_risk_rows,
	_escalated_risk_rows,
	_operations_summary_rows,
	_school_risk_queryset,
	_visible_metric_ids,
	conclude_indepth_grade,
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

	def test_any_red_at_expected_is_needs_attention(self):
		self.assertEqual(
			conclude_indepth_grade({"expected_standard": ["red", "green"]}),
			"needs_attention",
		)

	def test_single_red_at_expected_is_needs_attention(self):
		self.assertEqual(conclude_indepth_grade({"expected_standard": ["red"]}), "needs_attention")

	def test_red_at_expected_ignores_any_urgent_improvement_input(self):
		# Urgent Improvement is no longer evaluated: whatever it holds, a red at
		# Expected Standard concludes Needs Attention.
		self.assertEqual(
			conclude_indepth_grade({
				"expected_standard": ["red"],
				"urgent_improvement": ["red", "green", ""],
			}),
			"needs_attention",
		)

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
		na = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.NEEDS_ATTENTION, order=2
		)
		self.jna1 = InDepthJudgementArea.objects.create(
			standard=na, statement="Progress is inconsistent across groups.",
			is_flat=True, order=1,
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

	def test_rag_red_at_expected_is_needs_attention(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green")])
		self.assertEqual(self._review().overall_grade, "needs_attention")

	def test_rag_red_at_expected_ignores_urgent_improvement(self):
		# Urgent Improvement statements are no longer rated; a value posted for one
		# is ignored and the grade stays Needs Attention.
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green"), (self.ju1, "green")])
		review = self._review()
		self.assertEqual(review.overall_grade, "needs_attention")
		self.assertFalse(
			InDepthResponse.objects.filter(review=review, judgement_area=self.ju1).exists()
		)

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

	def test_needs_attention_commentary_shows_expected_statements_and_na_bullets(self):
		# A red at Expected concludes Needs Attention; the commentary page then
		# writes up the Expected Standard statements and offers the flat Needs
		# Attention bullets plus a comment box.
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green")])
		self.assertEqual(self._review().overall_grade, "needs_attention")
		url = f"{reverse('review:indepth_review')}?area={self.area.id}&page=commentary"
		resp = self.client.get(url)
		shown = {
			row["ja"].id
			for block in resp.context["rich_blocks"]
			for row in block["rows"]
		}
		self.assertEqual(shown, {self.je1.id, self.je2.id})
		self.assertEqual([b.id for b in resp.context["na_bullets"]], [self.jna1.id])
		self.assertContains(resp, "needs_attention_comment")

	def test_needs_attention_comment_persists(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "red"), (self.je2, "green")])
		data = {
			"school_id": str(self.school.id),
			"year": "2026-2027",
			"area_id": str(self.area.id),
			"page": "commentary",
			"form-TOTAL_FORMS": "0",
			"form-INITIAL_FORMS": "0",
			"form-MIN_NUM_FORMS": "0",
			"form-MAX_NUM_FORMS": "1000",
			"needs_attention_comment": "Two of the listed statements also apply.",
		}
		url = f"{reverse('review:indepth_review')}?area={self.area.id}&page=commentary"
		resp = self.client.post(url, data=data)
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(
			self._review().needs_attention_comment,
			"Two of the listed statements also apply.",
		)

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

	# Clearing a rating used to call resp.delete(), destroying the commentary and
	# next steps written against that statement. The ladder JS unchecks a rung it
	# hides, so an ordinary edit posted other statements back blank and silently
	# binned their write-ups.
	def test_clearing_a_rating_keeps_the_write_up_on_that_statement(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		self._commentary_post([
			(self.je1, "Books show secure knowledge over time.", "Moderate across the trust."),
			(self.je2, "Gaps remain in year 9.", "Target year 9 in the spring."),
		])
		review = self._review()
		before = InDepthResponse.objects.get(review=review, judgement_area=self.je1)

		# Re-post the ladder with that statement's rating blank.
		resp = self._rag_post([(self.je1, ""), (self.je2, "amber")])
		self.assertEqual(resp.status_code, 302)

		after = InDepthResponse.objects.filter(
			review=review, judgement_area=self.je1
		).first()
		self.assertIsNotNone(
			after, "the row was deleted when the rating was cleared, taking the write-up"
		)
		self.assertEqual(after.pk, before.pk)
		self.assertEqual(after.evidence_text, "Books show secure knowledge over time.")
		self.assertEqual(after.next_steps, "Moderate across the trust.")
		self.assertEqual(after.rag, "")

	# Keeping de-rated rows must not extend to empty ones: a rated statement with
	# nothing written against it still goes when its rating is cleared.
	def test_clearing_a_rating_still_deletes_a_row_with_no_write_up(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		review = self._review()
		self.assertTrue(
			InDepthResponse.objects.filter(review=review, judgement_area=self.je2).exists()
		)
		self._rag_post([(self.je1, "green"), (self.je2, "")])
		self.assertFalse(
			InDepthResponse.objects.filter(review=review, judgement_area=self.je2).exists()
		)

	# A row kept for its write-up carries rag="" and must count as un-rated, or the
	# grade would stay frozen at the value the cleared rating produced.
	def test_grade_recomputes_when_a_rating_is_cleared_but_the_write_up_stays(self):
		self.client.force_login(self.staff)
		self._rag_post([(self.je1, "green"), (self.je2, "amber")])
		self._commentary_post([(self.je1, "Triangulated evidence.", "Sustain practice.")])
		self.assertEqual(self._review().overall_grade, "expected_standard")

		self._rag_post([(self.je1, ""), (self.je2, "amber")])

		review = self._review()
		self.assertEqual(review.overall_grade, "")  # rung incomplete again
		kept = InDepthResponse.objects.get(review=review, judgement_area=self.je1)
		self.assertEqual(kept.rag, "")
		self.assertEqual(kept.evidence_text, "Triangulated evidence.")
		self.assertEqual(kept.next_steps, "Sustain practice.")


class GradeOverrideTests(TestCase):
	"""Over-writing an evaluation grade with the in-depth-review-derived grade."""

	def setUp(self):
		self.school = School.objects.create(name="Test School")
		# Category name must match the in-depth area name for the link to resolve.
		self.category = Category.objects.create(name="Achievement", order=4, is_active=True)
		self.area = InDepthArea.objects.create(name="Achievement", order=4)

		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)

		self.staff = User.objects.create_user(username="staff", email="staff@example.com")
		SchoolProfile.objects.create(user=self.staff, school=self.school)
		self.staff.schoolprofile.schools.add(self.school)
		for codename in ("add_evaluation", "change_evaluation"):
			self.staff.user_permissions.add(
				Permission.objects.get(content_type__app_label="review", codename=codename)
			)

		self.viewer = User.objects.create_user(username="viewer", email="viewer@example.com")
		SchoolProfile.objects.create(user=self.viewer, school=self.school)
		self.viewer.schoolprofile.schools.add(self.school)

		# An in-depth review that concluded "exceptional" -> rating 1.
		InDepthReview.objects.create(
			school=self.school, year=2026, area=self.area, overall_grade="exceptional"
		)
		# A manual evaluation currently sitting at "expected" (rating 3).
		self.evaluation = Evaluation.objects.create(
			school=self.school, period=self.period, category=self.category, rating=3
		)

	def _override_post(self, user, reason=""):
		self.client.force_login(user)
		return self.client.post(
			reverse("review:evaluation"),
			data={
				"action": "override_grade",
				"school_id": str(self.school.id),
				"year": "2026-2027",
				"round": "1",
				"category_id": str(self.category.id),
				"reason": reason,
			},
		)

	def test_override_sets_rating_and_records_audit(self):
		resp = self._override_post(self.staff, reason="In-depth review evidence is stronger.")
		self.assertEqual(resp.status_code, 302)

		self.evaluation.refresh_from_db()
		self.assertEqual(self.evaluation.rating, 1)  # exceptional
		self.assertEqual(self.evaluation.system_rating, 3)  # prior rating preserved
		self.assertTrue(self.evaluation.rating_overridden)
		self.assertEqual(self.evaluation.overridden_by, self.staff)
		self.assertIsNotNone(self.evaluation.overridden_at)
		self.assertEqual(self.evaluation.override_reason, "In-depth review evidence is stronger.")

	def test_override_reason_is_optional(self):
		resp = self._override_post(self.staff, reason="")
		self.assertEqual(resp.status_code, 302)
		self.evaluation.refresh_from_db()
		self.assertEqual(self.evaluation.rating, 1)
		self.assertEqual(self.evaluation.override_reason, "")

	def test_viewer_cannot_override(self):
		resp = self._override_post(self.viewer)
		self.assertEqual(resp.status_code, 302)
		self.evaluation.refresh_from_db()
		self.assertEqual(self.evaluation.rating, 3)  # unchanged
		self.assertFalse(self.evaluation.rating_overridden)

	def test_override_offered_only_when_grades_differ(self):
		self.client.force_login(self.staff)
		# Differs (in-depth=1 vs current=3): offered.
		resp = self.client.get(
			reverse("review:evaluation"), {"year": "2026-2027", "round": "1"}
		)
		self.assertTrue(any(o["category"].id == self.category.id for o in resp.context["override_rows"]))

		# Make them match -> no longer offered.
		self.evaluation.rating = 1
		self.evaluation.save(update_fields=["rating"])
		resp = self.client.get(
			reverse("review:evaluation"), {"year": "2026-2027", "round": "1"}
		)
		self.assertFalse(any(o["category"].id == self.category.id for o in resp.context["override_rows"]))


class ImportWorkbooksTests(TestCase):
	"""The .xlsx supporting-tool importer is idempotent and per-tool aware."""

	def _import(self):
		from django.core.management import call_command
		call_command("import_indepth_workbooks", verbosity=0)

	def test_import_is_idempotent_and_parses_per_tool_columns(self):
		import os
		from django.conf import settings

		wb_dir = os.path.join(settings.BASE_DIR, "review", "data", "workbooks")
		if not os.path.isdir(wb_dir) or not any(f.endswith(".xlsx") for f in os.listdir(wb_dir)):
			self.skipTest("No workbooks present to import.")

		self._import()
		lg = InDepthArea.objects.get(name="Leadership and Governance")
		first_counts = {
			a.name: InDepthJudgementArea.objects.filter(standard__area=a).count()
			for a in InDepthArea.objects.filter(
				name__in=["Achievement", "Inclusion", "Leadership and Governance"]
			)
		}
		# Leadership's extra "How do we know this?" column is captured.
		self.assertTrue(
			InDepthJudgementArea.objects.filter(standard__area=lg)
			.exclude(how_we_know=[])
			.exists()
		)

		# Re-running must not duplicate rows.
		self._import()
		second_counts = {
			a.name: InDepthJudgementArea.objects.filter(standard__area=a).count()
			for a in InDepthArea.objects.filter(
				name__in=["Achievement", "Inclusion", "Leadership and Governance"]
			)
		}
		self.assertEqual(first_counts, second_counts)


class IndepthDeployReloadTests(TestCase):
	"""startup.sh re-runs load_indepth_blueprint -> load_indepth_criteria ->
	import_indepth_workbooks on every Azure deploy. All three used to rebuild
	their rows by deleting first, cascading InDepthArea -> InDepthReview ->
	InDepthResponse and taking every school's written work with it."""

	# In criteria.json but NOT in load_indepth_blueprint's BLUEPRINT: the purge
	# used to delete these seven areas outright on every deploy.
	UNBLUEPRINTED_AREA = "Achievement"
	# In both, so it survived the purge and only lost its judgement areas.
	BLUEPRINTED_AREA = "Safeguarding"

	@staticmethod
	def _reload_blueprint_module():
		# load_indepth_blueprint pops "subsections" off its module-level BLUEPRINT
		# constant, so a second call in one process raises KeyError. On Azure each
		# deploy is a fresh process; reloading the module reproduces that.
		importlib.reload(
			importlib.import_module("review.management.commands.load_indepth_blueprint")
		)

	@staticmethod
	def _workbooks_present():
		from django.conf import settings

		folder = Path(settings.BASE_DIR) / "review" / "data" / "workbooks"
		return folder.is_dir() and any(folder.glob("*.xlsx"))

	@classmethod
	def _run_deploy_sequence(cls):
		cls._reload_blueprint_module()
		call_command("load_indepth_blueprint", verbosity=0)
		call_command("load_indepth_criteria", verbosity=0)
		if cls._workbooks_present():
			call_command("import_indepth_workbooks", verbosity=0)

	@classmethod
	def setUpTestData(cls):
		cls._run_deploy_sequence()
		cls.school = School.objects.create(name="Deploy Test School")
		cls.written_work = {}
		for name in (cls.UNBLUEPRINTED_AREA, cls.BLUEPRINTED_AREA):
			area = InDepthArea.objects.get(name=name)
			ja = (
				InDepthJudgementArea.objects.filter(standard__area=area)
				.order_by("standard__order", "order", "id")
				.first()
			)
			assert ja is not None, f"no judgement areas loaded for {name}"
			review = InDepthReview.objects.create(
				school=cls.school,
				year=2026,
				area=area,
				qa_reflection=f"QA reflection for {name} — written by the school.",
			)
			response = InDepthResponse.objects.create(
				review=review,
				judgement_area=ja,
				rag="green",
				evidence_text=f"Evidence write-up for {name}.",
				next_steps=f"Next steps agreed for {name}.",
			)
			cls.written_work[name] = {
				"review_pk": review.pk,
				"response_pk": response.pk,
				"judgement_area_pk": ja.pk,
			}

	def _assert_written_work_intact(self, area_name):
		saved = self.written_work[area_name]
		review = InDepthReview.objects.filter(pk=saved["review_pk"]).first()
		self.assertIsNotNone(
			review, f"the {area_name} review was deleted by the deploy sequence"
		)
		self.assertEqual(
			review.qa_reflection, f"QA reflection for {area_name} — written by the school."
		)
		response = InDepthResponse.objects.filter(pk=saved["response_pk"]).first()
		self.assertIsNotNone(
			response, f"the {area_name} response was deleted by the deploy sequence"
		)
		self.assertEqual(response.evidence_text, f"Evidence write-up for {area_name}.")
		self.assertEqual(response.next_steps, f"Next steps agreed for {area_name}.")

	# The whole deploy path, run a second time, used to wipe every review and
	# response and rebuild the statements at fresh pks so nothing looked wrong.
	def test_redeploy_does_not_destroy_reviews_or_written_work(self):
		self._run_deploy_sequence()
		self._assert_written_work_intact(self.UNBLUEPRINTED_AREA)
		self._assert_written_work_intact(self.BLUEPRINTED_AREA)

	# The blueprint purge ran outside the --clear guard, so an area that exists
	# only in criteria.json was deleted on every deploy, cascading to its reviews.
	def test_blueprint_reload_no_longer_purges_areas_it_does_not_list(self):
		self._reload_blueprint_module()
		call_command("load_indepth_blueprint", verbosity=0)
		self.assertTrue(
			InDepthArea.objects.filter(name=self.UNBLUEPRINTED_AREA).exists(),
			f"{self.UNBLUEPRINTED_AREA} was purged by load_indepth_blueprint",
		)
		self._assert_written_work_intact(self.UNBLUEPRINTED_AREA)

	# load_indepth_criteria rebuilt each standard's judgement areas with a blind
	# delete + bulk_create; InDepthResponse.judgement_area is a CASCADE.
	def test_criteria_reload_keeps_judgement_area_pks_and_their_responses(self):
		call_command("load_indepth_criteria", verbosity=0)
		for name in (self.UNBLUEPRINTED_AREA, self.BLUEPRINTED_AREA):
			saved = self.written_work[name]
			self.assertTrue(
				InDepthJudgementArea.objects.filter(pk=saved["judgement_area_pk"]).exists(),
				f"the {name} statement was deleted and rebuilt at a new pk",
			)
			self._assert_written_work_intact(name)


class SyncJudgementAreasTests(TestCase):
	"""The shared in-place reload behind both loaders (_indepth_sync)."""

	def setUp(self):
		self.school = School.objects.create(name="Sync Test School")
		self.area = InDepthArea.objects.create(name="Achievement", order=4)
		self.standard = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.review = InDepthReview.objects.create(
			school=self.school, year=2026, area=self.area
		)

	def _ja(self, statement, order):
		return InDepthJudgementArea.objects.create(
			standard=self.standard, statement=statement, order=order
		)

	def _response(self, ja):
		return InDepthResponse.objects.create(
			review=self.review,
			judgement_area=ja,
			rag="green",
			evidence_text="Written work that must survive a reload.",
			next_steps="Agreed next steps.",
		)

	# The reload must update a re-supplied statement in place; recreating it at a
	# new pk cascades its responses away.
	def test_unchanged_statement_keeps_its_pk_and_its_responses(self):
		ja = self._ja("Pupils achieve well.", 1)
		response = self._response(ja)

		# Same statement, whitespace and casing churn only.
		sync_judgement_areas(self.standard, [{"statement": "  pupils  achieve well. "}])

		ja.refresh_from_db()
		response.refresh_from_db()
		self.assertEqual(self.standard.judgement_areas.count(), 1)
		self.assertEqual(response.judgement_area_id, ja.pk)
		self.assertEqual(response.evidence_text, "Written work that must survive a reload.")
		self.assertEqual(response.next_steps, "Agreed next steps.")

	def test_retired_statement_with_no_responses_is_deleted(self):
		kept = self._ja("Pupils achieve well.", 1)
		retired = self._ja("A statement that has been withdrawn.", 2)

		written, deleted, kept_count = sync_judgement_areas(
			self.standard, [{"statement": "Pupils achieve well."}]
		)

		self.assertEqual((written, deleted, kept_count), (1, 1, 0))
		self.assertFalse(InDepthJudgementArea.objects.filter(pk=retired.pk).exists())
		self.assertTrue(InDepthJudgementArea.objects.filter(pk=kept.pk).exists())

	# Losing a leader's write-up is worse than carrying a retired statement, so a
	# retired statement that holds responses is kept and reported.
	def test_retired_statement_with_responses_is_kept_not_deleted(self):
		self._ja("Pupils achieve well.", 1)
		retired = self._ja("A statement that has been withdrawn.", 2)
		response = self._response(retired)

		written, deleted, kept_count = sync_judgement_areas(
			self.standard, [{"statement": "Pupils achieve well."}]
		)

		self.assertEqual((written, deleted, kept_count), (1, 0, 1))
		self.assertTrue(InDepthJudgementArea.objects.filter(pk=retired.pk).exists())
		response.refresh_from_db()
		self.assertEqual(response.evidence_text, "Written work that must survive a reload.")


class RiskMatrixTests(TestCase):
	"""The matrix is the specification. The mockup's own rows disagree with it
	in four of six cases, so these assert every cell directly."""

	def test_all_nine_cells(self):
		expected = {
			("High", "Unlikely"): "Yellow",
			("High", "Possible"): "Amber",
			("High", "Highly probable"): "Red",
			("Medium", "Unlikely"): "Green",
			("Medium", "Possible"): "Yellow",
			("Medium", "Highly probable"): "Amber",
			("Low", "Unlikely"): "Green",
			("Low", "Possible"): "Green",
			("Low", "Highly probable"): "Yellow",
		}
		for key, colour in expected.items():
			self.assertEqual(rag_for(*key), colour, msg=str(key))

	def test_band_is_recomputed_on_save_and_never_trusted_from_input(self):
		env = _risk_env()
		rating = RiskRating(
			risk=env["risk"], period=env["autumn"], impact="Low", likelihood="Unlikely"
		)
		# Even a hand-set band is overwritten from the matrix.
		rating.band = "critical"
		rating.save()
		rating.refresh_from_db()
		self.assertEqual(rating.band, "low_risk")
		self.assertEqual(rating.rag, "Green")

	def test_trend_needs_history_and_persisting_is_amber_or_worse(self):
		self.assertIsNone(trend_for("critical", None))
		self.assertEqual(trend_for("critical", "high_priority"), "worsening")
		self.assertEqual(trend_for("low_risk", "high_priority"), "improving")
		self.assertEqual(trend_for("high_priority", "high_priority"), "persisting")
		# An unchanged Green is not a concern, so it is not "persisting".
		self.assertIsNone(trend_for("low_risk", "low_risk"))


def _risk_env(*, phase="SECONDARY"):
	"""A school, a category, a risk and three terms of periods."""
	school = School.objects.create(name="Test High School", phase=phase)
	area = InDepthArea.objects.create(name="Safeguarding", order=10)
	category = TrustCategory.objects.create(
		group=TrustCategory.Group.EVALUATION_AREA,
		indepth_area=area,
		routes_to=TrustCategory.Route.SIV,
		order=10,
	)
	# Migration 0008 already creates the current year's Round 1 period, so these
	# must be get_or_create rather than create.
	autumn, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
	spring, _ = ReviewPeriod.objects.get_or_create(year=2026, round=2)
	summer, _ = ReviewPeriod.objects.get_or_create(year=2026, round=3)
	risk = Risk.objects.create(
		school=school,
		category=category,
		title="Perimeter fencing damaged",
		owner="Site Manager",
		opened_period=autumn,
	)
	return {
		"school": school,
		"area": area,
		"category": category,
		"risk": risk,
		"autumn": autumn,
		"spring": spring,
		"summer": summer,
	}


def _make_user(username, *, school, group_name=None, superuser=False):
	if superuser:
		user = User.objects.create_superuser(username, f"{username}@x.test", "pw123456")
	else:
		user = User.objects.create_user(username, f"{username}@x.test", "pw123456")
	profile = SchoolProfile.objects.create(user=user, school=school)
	profile.schools.add(school)
	if group_name:
		user.groups.add(Group.objects.get(name=group_name))
	return user


class RiskEscalationTests(TestCase):
	"""Red only, and the threshold is a setting rather than a code change."""

	def setUp(self):
		self.env = _risk_env()
		self.settings_obj = RiskSettings.load()

	def _rate(self, period, impact, likelihood):
		return RiskRating.objects.create(
			risk=self.env["risk"], period=period, impact=impact, likelihood=likelihood
		)

	def test_red_escalates(self):
		self._rate(self.env["autumn"], "High", "Highly probable")
		rows = _escalated_risk_rows([self.env["school"]], year=2026, round_number=1)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["rag"], "Red")

	def test_amber_does_not_escalate_on_its_first_term(self):
		self._rate(self.env["autumn"], "High", "Possible")
		rows = _escalated_risk_rows([self.env["school"]], year=2026, round_number=1)
		self.assertEqual(rows, [])

	def test_amber_does_not_escalate_after_three_terms(self):
		for period in ("autumn", "spring", "summer"):
			self._rate(self.env[period], "High", "Possible")
		rows = _escalated_risk_rows([self.env["school"]], year=2026, round_number=3)
		self.assertEqual(rows, [], "Persisting Amber must not escalate under the default rule")

	def test_flipping_the_setting_escalates_persisting_amber_with_no_code_change(self):
		for period in ("autumn", "spring", "summer"):
			self._rate(self.env[period], "High", "Possible")

		self.settings_obj.escalate_persisting_amber = True
		self.settings_obj.save()

		rows = _escalated_risk_rows([self.env["school"]], year=2026, round_number=3)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["trend"], "persisting")

	def test_closed_risks_are_never_on_the_exception_report(self):
		self._rate(self.env["autumn"], "High", "Highly probable")
		self.env["risk"].status = Risk.Status.CLOSED
		self.env["risk"].save()
		rows = _escalated_risk_rows([self.env["school"]], year=2026, round_number=1)
		self.assertEqual(rows, [])


class RiskCarryForwardTests(TestCase):
	def setUp(self):
		self.env = _risk_env()

	def test_risk_carries_into_the_next_term_and_reports_worsening(self):
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="Medium",
			likelihood="Possible",
		)
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["spring"],
			impact="High",
			likelihood="Possible",
		)

		rows = _build_risk_rows(
			_school_risk_queryset(self.env["school"]),
			year=2026,
			round_number=2,
			settings=RiskSettings.load(),
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["rag"], "Amber")
		self.assertEqual(row["previous"].rag, "Yellow")
		self.assertEqual(row["trend"], "worsening")

	def test_a_term_with_no_entry_still_compares_against_the_last_rating(self):
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="Medium",
			likelihood="Possible",
		)
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["summer"],
			impact="High",
			likelihood="Possible",
		)
		rows = _build_risk_rows(
			_school_risk_queryset(self.env["school"]),
			year=2026,
			round_number=3,
			settings=RiskSettings.load(),
		)
		self.assertEqual(rows[0]["trend"], "worsening")

	def test_route_is_derived_from_category_never_stored_on_the_risk(self):
		self.assertEqual(self.env["risk"].route, "SIV")
		self.assertFalse(
			any(f.name == "route" for f in Risk._meta.get_fields()),
			"Route must be derived from the category, not a field",
		)

		estates = TrustCategory.objects.create(
			group=TrustCategory.Group.OPERATIONS_DOMAIN,
			domain_key="estates-operations",
			domain_name="Estates & Operations",
			routes_to=TrustCategory.Route.TFORS,
			order=120,
		)
		tfors_risk = Risk.objects.create(
			school=self.env["school"], category=estates, title="Fire risk assessment due"
		)
		self.assertEqual(tfors_risk.route, "TFORS")

		# Both routes live in the same register.
		titles = {
			row["risk"].title
			for row in _build_risk_rows(
				_school_risk_queryset(self.env["school"]),
				year=2026,
				round_number=1,
				settings=RiskSettings.load(),
			)
		}
		self.assertIn("Perimeter fencing damaged", titles)
		self.assertIn("Fire risk assessment due", titles)


class RiskRegisterViewTests(TestCase):
	def setUp(self):
		call_command("ensure_osed_staff_group")
		call_command("ensure_risk_qa_group")
		self.env = _risk_env()
		self.principal = _make_user(
			"principal", school=self.env["school"], group_name="OSED Staff"
		)
		self.viewer = _make_user("lab.member", school=self.env["school"])
		self.cfo = _make_user("cfo", school=self.env["school"], group_name="Risk QA")

	def _url(self, **params):
		query = "&".join(f"{k}={v}" for k, v in params.items())
		return f"/review/risk/{'?' + query if query else ''}"

	def test_term_view_lists_open_risks_rather_than_an_empty_form(self):
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="High",
			likelihood="Possible",
		)
		self.client.force_login(self.principal)
		response = self.client.get(self._url(year="2026-2027", round=1))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.context["open_rows"]), 1)
		self.assertContains(response, "Perimeter fencing damaged")
		self.assertContains(response, "These risks are already open")

	def test_adding_a_risk_records_the_first_rating(self):
		self.client.force_login(self.principal)
		response = self.client.post(
			self._url(),
			{
				"action": "add_risk",
				"year": "2026-2027",
				"round": "1",
				"title": "Two unfilled teaching vacancies",
				"category": self.env["category"].id,
				"impact": "Medium",
				"likelihood": "Highly probable",
				"mitigation": "Advertising via three routes",
				"owner": "Principal",
				"review_point": "Spring 1",
			},
		)
		self.assertEqual(response.status_code, 302)
		risk = Risk.objects.get(title="Two unfilled teaching vacancies")
		self.assertEqual(risk.ratings.count(), 1)
		self.assertEqual(risk.ratings.first().rag, "Amber")

	def test_closing_a_risk_needs_a_reason_and_keeps_it_on_the_register(self):
		self.client.force_login(self.principal)

		response = self.client.post(
			self._url(),
			{
				"action": "close_risk",
				"year": "2026-2027",
				"round": "1",
				"risk_id": self.env["risk"].id,
				"close_reason": "",
			},
		)
		self.env["risk"].refresh_from_db()
		self.assertEqual(self.env["risk"].status, Risk.Status.OPEN, "Blank reason must not close")

		self.client.post(
			self._url(),
			{
				"action": "close_risk",
				"year": "2026-2027",
				"round": "1",
				"risk_id": self.env["risk"].id,
				"close_reason": "Fencing replaced and signed off by the contractor.",
			},
		)
		self.env["risk"].refresh_from_db()
		self.assertEqual(self.env["risk"].status, Risk.Status.CLOSED)
		self.assertIsNotNone(self.env["risk"].closed_at)
		self.assertTrue(self.env["risk"].close_awaiting_qa)

		response = self.client.get(self._url(year="2026-2027", round=1))
		self.assertEqual(len(response.context["closed_rows"]), 1)
		self.assertContains(response, "Fencing replaced")

	def test_a_principal_cannot_see_or_edit_another_schools_register(self):
		other = School.objects.create(name="Other School", phase="PRIMARY")
		other_risk = Risk.objects.create(
			school=other, category=self.env["category"], title="Not yours"
		)
		self.client.force_login(self.principal)

		response = self.client.get(self._url(school=other.id, year="2026-2027", round=1))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["school"], self.env["school"])
		self.assertNotContains(response, "Not yours")

		self.client.post(
			self._url(),
			{
				"action": "close_risk",
				"year": "2026-2027",
				"round": "1",
				"school_id": other.id,
				"risk_id": other_risk.id,
				"close_reason": "Trying to close someone else's risk.",
			},
		)
		other_risk.refresh_from_db()
		self.assertEqual(other_risk.status, Risk.Status.OPEN)

	def test_read_only_viewer_sees_the_register_but_cannot_post(self):
		self.client.force_login(self.viewer)
		response = self.client.get(self._url(year="2026-2027", round=1))
		self.assertEqual(response.status_code, 200)
		self.assertFalse(response.context["can_edit"])
		self.assertContains(response, "Perimeter fencing damaged")

		self.client.post(
			self._url(),
			{
				"action": "close_risk",
				"year": "2026-2027",
				"round": "1",
				"risk_id": self.env["risk"].id,
				"close_reason": "Should not be allowed.",
			},
		)
		self.env["risk"].refresh_from_db()
		self.assertEqual(self.env["risk"].status, Risk.Status.OPEN)

	def test_read_only_get_does_not_create_review_periods(self):
		ReviewPeriod.objects.all().delete()
		self.client.force_login(self.viewer)
		self.client.get(self._url(year="2026-2027", round=2))
		self.assertFalse(ReviewPeriod.objects.filter(year=2026, round=2).exists())

	def test_rag_threshold_filter_cuts_the_register(self):
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="Low",
			likelihood="Unlikely",
		)
		self.client.force_login(self.principal)
		response = self.client.get(self._url(year="2026-2027", round=1, rag="red"))
		self.assertEqual(response.context["open_rows"], [])
		response = self.client.get(self._url(year="2026-2027", round=1, rag="all"))
		self.assertEqual(len(response.context["open_rows"]), 1)


class RiskQaPermissionTests(TestCase):
	def setUp(self):
		call_command("ensure_osed_staff_group")
		call_command("ensure_risk_qa_group")
		self.env = _risk_env()
		self.principal = _make_user(
			"principal", school=self.env["school"], group_name="OSED Staff"
		)
		self.cfo = _make_user("cfo", school=self.env["school"], group_name="Risk QA")
		self.rating = RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="High",
			likelihood="Possible",
		)

	def test_editor_is_not_a_qa_and_is_refused_the_queue(self):
		self.assertFalse(user_can_qa_risk(self.principal))
		self.client.force_login(self.principal)
		response = self.client.get("/review/risk/qa/")
		self.assertEqual(response.status_code, 403)

	def test_qa_member_sees_the_queue_and_can_sign_off(self):
		self.assertTrue(user_can_qa_risk(self.cfo))
		self.client.force_login(self.cfo)

		response = self.client.get("/review/risk/qa/?year=2026-2027&round=1")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.context["rating_rows"]), 1)

		self.client.post(
			"/review/risk/qa/",
			{
				"action": "qa_rating",
				"year": "2026-2027",
				"round": "1",
				"target_id": self.rating.id,
			},
		)
		self.rating.refresh_from_db()
		self.assertEqual(self.rating.qa_by, self.cfo)
		self.assertIsNotNone(self.rating.qa_at)

	def test_qa_member_can_sign_off_from_the_school_register_too(self):
		self.client.force_login(self.cfo)
		response = self.client.get("/review/risk/?year=2026-2027&round=1")
		self.assertContains(response, "Sign off this term")

		self.client.post(
			"/review/risk/",
			{
				"action": "qa_rating",
				"year": "2026-2027",
				"round": "1",
				"target_id": self.rating.id,
			},
		)
		self.rating.refresh_from_db()
		self.assertEqual(self.rating.qa_by, self.cfo)

	def test_register_sign_off_cannot_reach_another_school(self):
		other = School.objects.create(name="Unscoped School", phase="PRIMARY")
		other_risk = Risk.objects.create(
			school=other, category=self.env["category"], title="Out of scope"
		)
		other_rating = RiskRating.objects.create(
			risk=other_risk,
			period=self.env["autumn"],
			impact="High",
			likelihood="Possible",
		)
		self.client.force_login(self.cfo)
		self.client.post(
			"/review/risk/",
			{
				"action": "qa_rating",
				"year": "2026-2027",
				"round": "1",
				"target_id": other_rating.id,
			},
		)
		other_rating.refresh_from_db()
		self.assertIsNone(other_rating.qa_at)

	def test_qa_queue_still_respects_school_scoping(self):
		other = School.objects.create(name="Unscoped School", phase="PRIMARY")
		other_risk = Risk.objects.create(
			school=other, category=self.env["category"], title="Out of scope"
		)
		other_rating = RiskRating.objects.create(
			risk=other_risk,
			period=self.env["autumn"],
			impact="High",
			likelihood="Highly probable",
		)
		self.client.force_login(self.cfo)

		response = self.client.get("/review/risk/qa/?year=2026-2027&round=1")
		self.assertNotContains(response, "Out of scope")

		self.client.post(
			"/review/risk/qa/",
			{
				"action": "qa_rating",
				"year": "2026-2027",
				"round": "1",
				"target_id": other_rating.id,
			},
		)
		other_rating.refresh_from_db()
		self.assertIsNone(other_rating.qa_at)

	def test_changing_a_rating_clears_its_sign_off(self):
		self.rating.qa_by = self.cfo
		self.rating.qa_at = timezone.now()
		self.rating.save()

		self.client.force_login(self.principal)
		self.client.post(
			"/review/risk/",
			{
				"action": "save_ratings",
				"year": "2026-2027",
				"round": "1",
				"ratings-TOTAL_FORMS": "1",
				"ratings-INITIAL_FORMS": "1",
				"ratings-MIN_NUM_FORMS": "0",
				"ratings-MAX_NUM_FORMS": "1000",
				"ratings-0-risk_id": self.env["risk"].id,
				"ratings-0-impact": "High",
				"ratings-0-likelihood": "Highly probable",
				"ratings-0-note": "",
			},
		)
		self.rating.refresh_from_db()
		self.assertEqual(self.rating.rag, "Red")
		self.assertIsNone(self.rating.qa_at, "A changed rating must be signed off again")


class TrustCategorySeedTests(TestCase):
	def test_seed_is_idempotent_and_keys_the_nine_areas_off_indeptharea(self):
		call_command("load_indepth_criteria")
		call_command("seed_trust_categories")
		call_command("seed_trust_categories")

		self.assertEqual(TrustCategory.objects.count(), 14)
		self.assertEqual(
			TrustCategory.objects.filter(
				group=TrustCategory.Group.EVALUATION_AREA
			).count(),
			9,
		)
		self.assertEqual(
			TrustCategory.objects.filter(routes_to=TrustCategory.Route.TFORS).count(), 5
		)
		self.assertFalse(
			TrustCategory.objects.filter(
				group=TrustCategory.Group.EVALUATION_AREA, indepth_area__isnull=True
			).exists(),
			"Evaluation-area categories must reference InDepthArea, not copy its name",
		)

		# A rename in InDepthArea flows through rather than forking the list.
		area = InDepthArea.objects.get(name="Post-16")
		area.name = "Post-16 Provision"
		area.save()
		category = TrustCategory.objects.get(indepth_area=area)
		self.assertEqual(category.name, "Post-16 Provision")


class TrustDashboardRiskTests(TestCase):
	def setUp(self):
		call_command("ensure_osed_staff_group")
		self.env = _risk_env()
		self.user = _make_user(
			"principal", school=self.env["school"], group_name="OSED Staff"
		)

	def test_red_appears_on_the_board_and_amber_does_not(self):
		amber = Risk.objects.create(
			school=self.env["school"],
			category=self.env["category"],
			title="Amber risk",
		)
		RiskRating.objects.create(
			risk=amber, period=self.env["autumn"], impact="High", likelihood="Possible"
		)
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="High",
			likelihood="Highly probable",
		)

		self.client.force_login(self.user)
		response = self.client.get("/review/board/?year=2026-2027&round=1")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Perimeter fencing damaged")
		self.assertNotContains(response, "Amber risk")

	def test_board_labels_every_chip_so_it_survives_greyscale(self):
		RiskRating.objects.create(
			risk=self.env["risk"],
			period=self.env["autumn"],
			impact="High",
			likelihood="Highly probable",
		)
		self.client.force_login(self.user)
		response = self.client.get("/review/board/?year=2026-2027&round=1")
		self.assertContains(response, 'risk-chip risk-chip--red">Red<')

	def test_risk_colours_do_not_reuse_the_evaluation_grade_classes(self):
		base = Path(__file__).resolve().parent
		for name in ("risk.html", "risk_qa.html"):
			markup = (base / "templates" / "review" / name).read_text(encoding="utf-8")
			self.assertNotIn("rag-pill", markup)
			self.assertNotIn("rag-current", markup)
			self.assertNotIn("score--", markup)


class TermLabelTests(TestCase):
	def test_rounds_are_labelled_as_terms(self):
		period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		self.assertEqual(period.term_label, "Autumn")
		self.assertEqual(str(period), "2026/2027 - Autumn term")
		self.assertEqual(ReviewPeriod(year=2026, round=3).term_label, "Summer")


# ---------------------------------------------------------------------------
# Operations & Resources (phase two)
# ---------------------------------------------------------------------------

OPS_AREA_NAMES = [
	"Safeguarding", "Inclusion", "Curriculum and Teaching", "Achievement",
	"Attendance and Behaviour", "Personal Development and Wellbeing",
	"Early Years", "Post-16", "Leadership and Governance",
]


def _ops_env(*, phase="SECONDARY", is_mainstream=True):
	# The areas are created directly rather than via load_indepth_criteria: these
	# tests only need the names TrustCategory keys off, and parsing nine
	# workbooks per test makes the suite crawl.
	for order, name in enumerate(OPS_AREA_NAMES, start=1):
		InDepthArea.objects.get_or_create(name=name, defaults={"order": order * 10})
	call_command("seed_trust_categories", verbosity=0)
	call_command("seed_operations_metrics", verbosity=0)
	call_command("ensure_osed_staff_group", verbosity=0)

	school = School.objects.create(
		name="Ops Test School", phase=phase, is_mainstream=is_mainstream
	)
	autumn, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
	spring, _ = ReviewPeriod.objects.get_or_create(year=2026, round=2)
	summer, _ = ReviewPeriod.objects.get_or_create(year=2026, round=3)
	return {"school": school, "autumn": autumn, "spring": spring, "summer": summer}


def _show(school, *keys, year=2026):
	for key in keys:
		OperationsMetricVisibility.objects.update_or_create(
			school=school,
			year=year,
			metric=OperationsMetric.objects.get(key=key),
			defaults={"is_visible": True},
		)


def _ops_user(name, school, group="OSED Staff"):
	user = User.objects.create_user(name, f"{name}@x.test", "pw12345678")
	profile = SchoolProfile.objects.create(user=user, school=school)
	profile.schools.add(school)
	if group:
		user.groups.add(Group.objects.get(name=group))
	return user


class OperationsSeedTests(TestCase):
	def setUp(self):
		self.env = _ops_env()

	def test_twelve_rated_metrics_across_five_domains(self):
		self.assertEqual(OperationsMetric.objects.count(), 12)
		domains = set(
			OperationsMetric.objects.values_list("domain__domain_name", flat=True)
		)
		self.assertEqual(len(domains), 5)

	def test_revenue_reserves_is_seeded_but_switched_off(self):
		metric = OperationsMetric.objects.get(key="revenue-reserves-pct-gag")
		self.assertTrue(metric.bands.exists())
		# Off means: no visibility row at all, and not visible anywhere.
		self.assertFalse(
			OperationsMetricVisibility.objects.filter(
				metric=metric, is_visible=True
			).exists()
		)
		self.assertNotIn(metric.id, _visible_metric_ids(self.env["school"], 2026))

	def test_every_metric_defaults_to_hidden(self):
		self.assertEqual(_visible_metric_ids(self.env["school"], 2026), set())

	def test_seed_is_idempotent(self):
		call_command("seed_operations_metrics", verbosity=0)
		call_command("seed_operations_metrics", verbosity=0)
		self.assertEqual(OperationsMetric.objects.count(), 12)

	def test_complaint_themes_are_seeded_and_admin_editable(self):
		names = set(ComplaintTheme.objects.values_list("name", flat=True))
		self.assertEqual(names, {"SEND", "Behaviour", "Communication", "Admissions"})

	def test_no_ownership_field_anywhere(self):
		"""Principal-owned / Trust-owned was dropped by the client."""
		for model in (OperationsMetric, OperationsEntry, OperationsMetricBand):
			names = {f.name for f in model._meta.get_fields()}
			for banned in ("owner_type", "principal_owned", "trust_owned", "ownership"):
				self.assertNotIn(banned, names, f"{model.__name__}.{banned}")

		base = Path(__file__).resolve().parent
		markup = (base / "templates" / "review" / "operations.html").read_text(encoding="utf-8")
		for banned in (">TRUST<", ">SCHOOL<", "owner_type", "principal_owned", "trust_owned"):
			self.assertNotIn(banned, markup)


class OperationsVisibilityTests(TestCase):
	def setUp(self):
		self.env = _ops_env()
		self.user = _ops_user("head", self.env["school"])
		self.client.force_login(self.user)

	def _get(self):
		return self.client.get("/review/operations/?year=2026-2027&round=1")

	def test_hidden_domain_renders_no_card_at_all(self):
		response = self._get()
		self.assertEqual(response.context["domains"], [])
		self.assertNotContains(response, "Cyber Essentials")

	def test_one_hidden_one_visible_renders_a_card_with_one_row(self):
		_show(self.env["school"], "cyber-essentials")
		response = self._get()
		domains = response.context["domains"]
		self.assertEqual(len(domains), 1)
		self.assertEqual(domains[0]["count"], 1)
		self.assertContains(response, "Cyber Essentials")
		self.assertNotContains(response, "Digital and Technology Standards")

	def test_hiding_everything_in_a_domain_removes_the_card(self):
		_show(self.env["school"], "cyber-essentials", "digital-technology-standards")
		self.assertEqual(len(self._get().context["domains"]), 1)

		OperationsMetricVisibility.objects.filter(school=self.env["school"]).update(
			is_visible=False
		)
		response = self._get()
		self.assertEqual(response.context["domains"], [])
		self.assertNotContains(response, "Cyber Essentials")

	def test_visibility_is_per_year(self):
		_show(self.env["school"], "cyber-essentials", year=2026)
		self.assertEqual(len(self._get().context["domains"]), 1)
		later = self.client.get("/review/operations/?year=2027-2028&round=1")
		self.assertEqual(later.context["domains"], [])

	def test_a_hidden_metric_cannot_be_written_to(self):
		hidden = OperationsMetric.objects.get(key="cyber-essentials")
		self.client.post(
			"/review/operations/",
			{
				"year": "2026-2027",
				"round": "1",
				f"metric-{hidden.id}-band_choice": "green",
			},
		)
		self.assertFalse(OperationsEntry.objects.filter(metric=hidden).exists())

	def test_toggling_visibility_changes_the_page_with_no_restart(self):
		self.assertNotContains(self._get(), "Cyber Essentials")
		_show(self.env["school"], "cyber-essentials")
		self.assertContains(self._get(), "Cyber Essentials")


class OperationsRagTests(TestCase):
	"""The acceptance checks that pin the evaluation logic."""

	def setUp(self):
		self.env = _ops_env()
		self.user = _ops_user("head", self.env["school"])

	def _entry(self, key, *, school=None, period=None, **kwargs):
		return OperationsEntry.objects.create(
			school=school or self.env["school"],
			period=period or self.env["autumn"],
			metric=OperationsMetric.objects.get(key=key),
			**kwargs,
		)

	def test_secondary_staff_costs_bands(self):
		self.assertEqual(self._entry("staff-costs-pct-income", value=Decimal("74")).rag, "green")
		OperationsEntry.objects.all().delete()
		self.assertEqual(self._entry("staff-costs-pct-income", value=Decimal("79")).rag, "amber")
		OperationsEntry.objects.all().delete()
		self.assertEqual(self._entry("staff-costs-pct-income", value=Decimal("81")).rag, "red")

	def test_primary_staff_costs_is_blue_whatever_the_value(self):
		primary = School.objects.create(name="Primary Test", phase="PRIMARY")
		for value in ("74", "79", "81", "0"):
			OperationsEntry.objects.all().delete()
			entry = self._entry("staff-costs-pct-income", school=primary, value=Decimal(value))
			self.assertEqual(entry.rag, "blue", f"value {value} should be Blue for a primary")

	def test_a_blue_tile_explains_itself(self):
		primary = School.objects.create(name="Primary Test", phase="PRIMARY")
		_show(primary, "staff-costs-pct-income")
		self._entry("staff-costs-pct-income", school=primary, value=Decimal("74"))
		SchoolProfile.objects.get(user=self.user).schools.add(primary)

		self.client.force_login(self.user)
		response = self.client.get(f"/review/operations/?school={primary.id}&year=2026-2027&round=1")
		self.assertContains(response, "Not yet benchmarked")
		self.assertContains(response, "must not be read as green")

	def test_revenue_reserves_bands(self):
		cases = {"5": "green", "2": "amber", "12": "amber", "-1": "red", "20": "red"}
		for value, expected in cases.items():
			OperationsEntry.objects.all().delete()
			entry = self._entry("revenue-reserves-pct-gag", value=Decimal(value))
			self.assertEqual(entry.rag, expected, f"{value}% should be {expected}")

	def test_statutory_compliance_is_computed_from_the_dates(self):
		school = self.env["school"]
		today = timezone.now().date()

		def set_items(offsets, action_plan=True):
			school.statutory_items.all().delete()
			for (item, _label), offset in zip(STATUTORY_ITEMS, offsets):
				StatutoryComplianceItem.objects.create(
					school=school,
					item=item,
					next_due_date=today + timedelta(days=offset),
					action_plan_in_place=action_plan,
				)

		set_items([30, 60, 90, 120, 150])
		self.assertEqual(statutory_rag(list(school.statutory_items.all())), "green")

		set_items([-21, 60, 90, 120, 150])
		self.assertEqual(statutory_rag(list(school.statutory_items.all())), "amber",
						 "one item 3 weeks overdue with a plan is Amber")

		set_items([-42, 60, 90, 120, 150])
		self.assertEqual(statutory_rag(list(school.statutory_items.all())), "red",
						 "one item 6 weeks overdue is Red")

		set_items([-21, 60, 90, 120, 150], action_plan=False)
		self.assertEqual(statutory_rag(list(school.statutory_items.all())), "red",
						 "overdue with no action plan is Red")

	def test_statutory_compliance_is_blue_until_all_five_dates_are_known(self):
		school = self.env["school"]
		StatutoryComplianceItem.objects.create(
			school=school, item="asbestos", next_due_date=timezone.now().date()
		)
		self.assertEqual(statutory_rag(list(school.statutory_items.all())), "blue")

	def test_statutory_tile_names_the_overdue_item(self):
		school = self.env["school"]
		today = timezone.now().date()
		for (item, _), offset in zip(STATUTORY_ITEMS, [-21, 60, 90, 120, 150]):
			StatutoryComplianceItem.objects.create(
				school=school, item=item, next_due_date=today + timedelta(days=offset),
				action_plan_in_place=True,
			)
		_show(school, "statutory-compliance")
		self.client.force_login(self.user)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "Fire risk assessment")
		self.assertContains(response, "overdue by 21 days")

	def test_complaints_with_no_prior_term_is_blue_not_green(self):
		entry = self._entry("complaints-stage-2", value=Decimal("0"))
		_show(self.env["school"], "complaints-stage-2")
		self.client.force_login(self.user)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		tile = response.context["domains"][0]["tiles"][0]
		self.assertEqual(tile["rag"], "blue")
		self.assertNotEqual(tile["rag"], "green")

	def test_complaints_trend(self):
		# Flat or falling is Green.
		self.assertEqual(complaints_rag(2, [4]), "green")
		self.assertEqual(complaints_rag(0, [0]), "green")
		# A first rise is Amber.
		self.assertEqual(complaints_rag(2, [1]), "amber")
		# Two consecutive rises is Red.
		self.assertEqual(complaints_rag(3, [1, 2]), "red")
		# A marked step-change in a single term is Red.
		self.assertEqual(complaints_rag(5, [1]), "red")
		# No history at all is Blue.
		self.assertEqual(complaints_rag(1, []), "blue")

	def test_complaints_trend_uses_the_schools_own_history(self):
		_show(self.env["school"], "complaints-stage-2")
		self._entry("complaints-stage-2", period=self.env["autumn"], value=Decimal("1"))
		self._entry("complaints-stage-2", period=self.env["spring"], value=Decimal("2"))
		self.client.force_login(self.user)

		spring = self.client.get("/review/operations/?year=2026-2027&round=2")
		self.assertEqual(spring.context["domains"][0]["tiles"][0]["rag"], "amber")

		self._entry("complaints-stage-2", period=self.env["summer"], value=Decimal("3"))
		summer = self.client.get("/review/operations/?year=2026-2027&round=3")
		self.assertEqual(summer.context["domains"][0]["tiles"][0]["rag"], "red")

	def test_predominant_theme_is_a_note_not_a_metric(self):
		self.assertEqual(OperationsMetric.objects.filter(name__icontains="theme").count(), 0)
		theme = ComplaintTheme.objects.get(name="SEND")
		self._entry("complaints-stage-2", value=Decimal("1"), theme=theme)
		_show(self.env["school"], "complaints-stage-2")
		self.client.force_login(self.user)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "predominantly SEND-related")

	def test_digital_standards_thresholds(self):
		for count, expected in (("6", "green"), ("5", "amber"), ("4", "amber"), ("3", "red")):
			OperationsEntry.objects.all().delete()
			entry = self._entry("digital-technology-standards", value=Decimal(count))
			self.assertEqual(entry.rag, expected, f"{count} standards -> {expected}")

	def test_sickness_absence_uses_the_national_comparator_and_shows_its_year(self):
		self.assertEqual(self._entry("staff-sickness-absence", value=Decimal("8")).rag, "green")
		OperationsEntry.objects.all().delete()
		self.assertEqual(self._entry("staff-sickness-absence", value=Decimal("9")).rag, "amber")
		OperationsEntry.objects.all().delete()
		self.assertEqual(self._entry("staff-sickness-absence", value=Decimal("11")).rag, "red")

		_show(self.env["school"], "staff-sickness-absence")
		self.client.force_login(self.user)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "2024/25", msg_prefix="the comparator year must be on the tile")

	def test_a_manual_red_reason_forces_red(self):
		entry = self._entry(
			"staff-turnover-vacancy",
			value=Decimal("1"),
			manual_red_reason="Maths vacancy unfilled a full term.",
		)
		self.assertEqual(entry.rag, "red")

	def test_rag_is_recomputed_on_save_never_trusted_from_input(self):
		entry = self._entry("revenue-reserves-pct-gag", value=Decimal("5"))
		entry.rag = "red"
		entry.save()
		entry.refresh_from_db()
		self.assertEqual(entry.rag, "green")


class OperationsGrantTests(TestCase):
	def test_applicable_set_follows_phase_and_type(self):
		primary = School.objects.create(name="P", phase="PRIMARY", is_mainstream=True)
		secondary = School.objects.create(name="S", phase="SECONDARY", is_mainstream=True)
		special = School.objects.create(name="Sp", phase="SECONDARY", is_mainstream=False)

		self.assertIn(GRANT_PE_SPORT, applicable_grants(primary))
		self.assertNotIn(GRANT_PE_SPORT, applicable_grants(secondary))
		self.assertIn(GRANT_INCLUSIVE_MAINSTREAM, applicable_grants(secondary))
		self.assertNotIn(GRANT_INCLUSIVE_MAINSTREAM, applicable_grants(special))
		for school in (primary, secondary, special):
			self.assertIn(GRANT_PUPIL_PREMIUM, applicable_grants(school))

	def test_grant_rag(self):
		env = _ops_env(phase="PRIMARY")
		school = env["school"]
		self.assertEqual(grant_rag(school, []), "blue")

		for grant in applicable_grants(school):
			GrantPublication.objects.create(
				school=school, year=2026, grant=grant, status=GRANT_PUBLISHED
			)
		self.assertEqual(grant_rag(school, list(school.grant_publications.all())), "green")

		school.grant_publications.filter(grant=GRANT_PE_SPORT).update(status=GRANT_DRAFTED)
		self.assertEqual(grant_rag(school, list(school.grant_publications.all())), "amber")

		school.grant_publications.filter(grant=GRANT_PE_SPORT).update(status=GRANT_MISSED)
		self.assertEqual(grant_rag(school, list(school.grant_publications.all())), "red")

	def test_primary_checklist_includes_pe_sport_and_a_secondarys_does_not(self):
		env = _ops_env(phase="PRIMARY")
		primary = env["school"]
		secondary = School.objects.create(name="Secondary Test", phase="SECONDARY")
		_show(primary, "grant-publication")
		_show(secondary, "grant-publication")

		user = _ops_user("head", primary)
		SchoolProfile.objects.get(user=user).schools.add(secondary)
		self.client.force_login(user)

		def checklist(response):
			tile = response.context["domains"][0]["tiles"][0]
			return [g["label"] for g in tile["grants"]]

		p = self.client.get(f"/review/operations/?school={primary.id}&year=2026-2027&round=1")
		self.assertIn("PE and Sport Premium", checklist(p))
		self.assertContains(p, "<li class=\"ops-subitem--overdue\">PE and Sport Premium", html=False)

		s = self.client.get(f"/review/operations/?school={secondary.id}&year=2026-2027&round=1")
		self.assertNotIn("PE and Sport Premium", checklist(s))
		self.assertEqual(checklist(s), ["Pupil Premium", "Inclusive Mainstream Fund"])


class OperationsRollUpTests(TestCase):
	"""Hidden metrics must be out of the denominator, and scope must be shown."""

	def setUp(self):
		self.env = _ops_env()
		call_command("ensure_osed_staff_group", verbosity=0)
		self.partial = self.env["school"]
		self.full = School.objects.create(name="Full Framework School", phase="SECONDARY")
		self.user = _ops_user("head", self.partial)
		SchoolProfile.objects.get(user=self.user).schools.add(self.full)

	def _green_everything(self, school, keys):
		_show(school, *keys)
		for key in keys:
			OperationsEntry.objects.create(
				school=school,
				period=self.env["autumn"],
				metric=OperationsMetric.objects.get(key=key),
				band_choice="green",
			)

	def test_a_partial_school_does_not_look_healthier_than_a_full_one(self):
		band_keys = ["in-year-budget-position", "curriculum-bonus-deficit"]
		self._green_everything(self.partial, band_keys[:1])
		self._green_everything(self.full, band_keys)
		# Give the full school one amber as well.
		_show(self.full, "cyber-essentials")
		OperationsEntry.objects.create(
			school=self.full,
			period=self.env["autumn"],
			metric=OperationsMetric.objects.get(key="cyber-essentials"),
			band_choice="amber",
		)

		rows = _operations_summary_rows(
			[self.partial, self.full], year=2026, round_number=1
		)
		by_school = {r["school"].name: r for r in rows}

		partial = by_school["Ops Test School"]
		full = by_school["Full Framework School"]

		# The denominators differ, and both say so.
		self.assertEqual(partial["summary"]["total"], 1)
		self.assertEqual(full["summary"]["total"], 3)
		self.assertEqual(partial["scope"]["label"], "1 of 12 metrics — pilot")
		self.assertEqual(full["scope"]["label"], "3 of 12 metrics — pilot")

		# The hidden metrics are absent, not counted as green.
		self.assertEqual(partial["summary"]["green"], 1)
		self.assertNotEqual(
			partial["summary"]["green"], OperationsMetric.objects.count()
		)

	def test_hidden_metrics_are_excluded_from_the_denominator(self):
		_show(self.partial, "cyber-essentials")
		OperationsEntry.objects.create(
			school=self.partial,
			period=self.env["autumn"],
			metric=OperationsMetric.objects.get(key="cyber-essentials"),
			band_choice="green",
		)
		rows = _operations_summary_rows([self.partial], year=2026, round_number=1)
		self.assertEqual(rows[0]["summary"]["total"], 1)
		self.assertEqual(sum(rows[0]["summary"]["counts"].values()), 1)

	def test_blue_is_never_counted_as_green(self):
		primary = School.objects.create(name="Primary Roll-up", phase="PRIMARY")
		_show(primary, "staff-costs-pct-income")
		OperationsEntry.objects.create(
			school=primary,
			period=self.env["autumn"],
			metric=OperationsMetric.objects.get(key="staff-costs-pct-income"),
			value=Decimal("74"),
		)
		rows = _operations_summary_rows([primary], year=2026, round_number=1)
		self.assertEqual(rows[0]["summary"]["blue"], 1)
		self.assertEqual(rows[0]["summary"]["green"], 0)

	def test_trust_dashboard_shows_scope_and_an_executive_summary(self):
		_show(self.partial, "cyber-essentials")
		OperationsEntry.objects.create(
			school=self.partial,
			period=self.env["autumn"],
			metric=OperationsMetric.objects.get(key="cyber-essentials"),
			band_choice="red",
		)
		self.client.force_login(self.user)
		response = self.client.get("/review/board/?year=2026-2027&round=1")
		self.assertContains(response, "1 of 12 metrics — pilot")
		self.assertContains(response, "Executive summary")
		self.assertContains(response, "Cyber Essentials")
		# The summary sits alongside the tiles, it does not replace them.
		self.assertContains(response, "ops-summary-tiles")


class OperationsPageTests(TestCase):
	def setUp(self):
		self.env = _ops_env()
		self.user = _ops_user("head", self.env["school"])
		self.viewer = _ops_user("lab", self.env["school"], group=None)
		_show(self.env["school"], "cyber-essentials")
		self.client.force_login(self.user)

	def test_standing_texts_appear_word_for_word(self):
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		# Escaped, because "Finance & ICFP" renders as "Finance &amp; ICFP".
		self.assertContains(response, escape(LEGEND_STANDING_TEXT))
		self.assertContains(response, escape(SMALL_PRINT))

	def test_the_legend_names_blue_as_not_yet_benchmarked(self):
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "Blue — not yet benchmarked")

	def test_free_text_saves_persists_per_term_and_is_never_rolled_up(self):
		self.client.post(
			"/review/operations/",
			{"year": "2026-2027", "round": "1", "anything_else": "Boiler quote chased twice."},
		)
		note = OperationsNote.objects.get(school=self.env["school"], period=self.env["autumn"])
		self.assertEqual(note.text, "Boiler quote chased twice.")

		autumn = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(autumn, "Boiler quote chased twice.")

		# Per term: Spring's own box starts empty, but Autumn's note stays visible
		# in the next term's history rather than vanishing.
		spring = self.client.get("/review/operations/?year=2026-2027&round=2")
		self.assertEqual(spring.context["note"], None)
		self.assertContains(spring, "Earlier terms")
		self.assertContains(spring, "Boiler quote chased twice.")
		self.assertTrue(
			OperationsNote.objects.filter(period=self.env["autumn"], text__contains="Boiler").exists()
		)

		# Never aggregated to the Trust Dashboard.
		board = self.client.get("/review/board/?year=2026-2027&round=1")
		self.assertNotContains(board, "Boiler quote chased twice.")

	def test_free_text_is_not_rag_rated(self):
		names = {f.name for f in OperationsNote._meta.get_fields()}
		self.assertNotIn("rag", names)

	def test_an_entry_records_who_wrote_it_and_how(self):
		metric = OperationsMetric.objects.get(key="cyber-essentials")
		self.client.post(
			"/review/operations/",
			{
				"year": "2026-2027", "round": "1",
				f"metric-{metric.id}-band_choice": "amber",
				f"metric-{metric.id}-commentary": "Renewal booked for January.",
			},
		)
		entry = OperationsEntry.objects.get(metric=metric)
		self.assertEqual(entry.rag, "amber")
		self.assertEqual(entry.source, OperationsEntry.Source.MANUAL)
		self.assertEqual(entry.recorded_by, self.user)

	def test_the_band_statements_are_the_picker_and_are_not_repeated(self):
		"""On a judgement-based metric the three statements are the buttons.

		The descriptor must appear once, as the thing being chosen -- not once
		as reference text and again as a colour word in a dropdown.
		"""
		metric = OperationsMetric.objects.get(key="cyber-essentials")
		band = metric.band_for_phase(self.env["school"].phase)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		html = response.content.decode()

		for colour in ("green", "amber", "red"):
			self.assertRegex(
				html,
				rf'type="radio"[^>]*name="metric-{metric.id}-band_choice"'
				rf'\s*value="{colour}"',
			)
			descriptor = getattr(band, f"{colour}_descriptor")
			self.assertEqual(html.count(escape(descriptor)), 1)

		self.assertNotIn(f'<select name="metric-{metric.id}-band_choice"', html)

	def test_nothing_chosen_stays_selectable_so_a_band_can_be_cleared(self):
		metric = OperationsMetric.objects.get(key="cyber-essentials")
		html = self.client.get("/review/operations/?year=2026-2027&round=1").content.decode()
		self.assertIn("Not yet rated", html)

		self.client.post(
			"/review/operations/",
			{"year": "2026-2027", "round": "1", f"metric-{metric.id}-band_choice": "amber"},
		)
		self.assertEqual(OperationsEntry.objects.get(metric=metric).band_choice, "amber")

		# Posting the empty option puts the tile back to Blue rather than
		# leaving a band that can be set once and never cleared.
		self.client.post(
			"/review/operations/",
			{"year": "2026-2027", "round": "1", f"metric-{metric.id}-band_choice": ""},
		)
		entry = OperationsEntry.objects.get(metric=metric)
		self.assertEqual(entry.band_choice, "")
		self.assertEqual(entry.rag, "blue")

	def test_every_tile_offers_a_not_yet_rated_state(self):
		"""Blue is a band, not the silent absence of the other three.

		Where the Principal chooses, it is the fourth button; where the colour is
		derived from a figure it is a fourth read-only card. The one tile with no
		band at all -- Primary ICFP, which the Trust holds no data for -- says so
		in its own note instead.
		"""
		keys = list(OperationsMetric.objects.values_list("key", flat=True))
		_show(self.env["school"], *keys)
		html = self.client.get("/review/operations/?year=2026-2027&round=1").content.decode()
		tiles = html.split('<div class="ops-row">')[1:]
		self.assertEqual(len(tiles), len(keys))

		for metric in OperationsMetric.objects.all():
			tile = next(t for t in tiles if f">{metric.name}<" in t)
			if metric.rule == RULE_BAND_CHOICE:
				self.assertIn(f'id="metric-{metric.id}-band-none"', tile, metric.key)
				self.assertIn("Not yet rated", tile, metric.key)
			elif "ops-bands" in tile:
				self.assertIn("ops-band--none", tile, metric.key)
				self.assertIn("Not yet rated", tile, metric.key)
			else:
				# No band for this phase: the blue note carries the explanation.
				self.assertIn("ops-blue-note", tile, metric.key)

	def test_the_derived_band_in_force_is_the_one_marked_current(self):
		metric = OperationsMetric.objects.get(key="staff-sickness-absence")
		_show(self.env["school"], metric.key)

		# Nothing entered: the tile is Blue, so Not yet rated is the current band.
		html = self.client.get("/review/operations/?year=2026-2027&round=1").content.decode()
		tile = next(t for t in html.split('<div class="ops-row">')[1:] if f">{metric.name}<" in t)
		self.assertIn("ops-band ops-band--none is-current", tile)

		# A figure lands in a band, and the marker moves off Not yet rated.
		OperationsEntry.objects.create(
			school=self.env["school"], period=self.env["autumn"], metric=metric, value=4.1
		)
		html = self.client.get("/review/operations/?year=2026-2027&round=1").content.decode()
		tile = next(t for t in html.split('<div class="ops-row">')[1:] if f">{metric.name}<" in t)
		self.assertNotIn("ops-band ops-band--none is-current", tile)
		self.assertEqual(tile.count("is-current"), 1)

	def test_a_read_only_user_cannot_save(self):
		self.client.force_login(self.viewer)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertEqual(response.status_code, 200)
		self.assertFalse(response.context["can_edit"])

		self.client.post(
			"/review/operations/",
			{"year": "2026-2027", "round": "1", "anything_else": "Should be refused."},
		)
		self.assertFalse(OperationsNote.objects.filter(text="Should be refused.").exists())

	def test_a_principal_cannot_reach_another_schools_operations_page(self):
		other = School.objects.create(name="Other Ops School", phase="PRIMARY")
		_show(other, "cyber-essentials")
		OperationsEntry.objects.create(
			school=other,
			period=self.env["autumn"],
			metric=OperationsMetric.objects.get(key="cyber-essentials"),
			band_choice="red",
			commentary="OTHER SCHOOL ONLY",
		)
		response = self.client.get(f"/review/operations/?school={other.id}&year=2026-2027&round=1")
		self.assertEqual(response.context["school"], self.env["school"])
		self.assertNotContains(response, "OTHER SCHOOL ONLY")

	def test_the_risk_summary_reads_the_register_and_keeps_no_copy(self):
		area = InDepthArea.objects.get(name="Safeguarding")
		category = TrustCategory.objects.get(indepth_area=area)
		risk = Risk.objects.create(
			school=self.env["school"], category=category, title="Perimeter fencing damaged"
		)
		RiskRating.objects.create(
			risk=risk, period=self.env["autumn"], impact="High", likelihood="Highly probable"
		)
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "Perimeter fencing damaged")
		self.assertContains(response, "Impact: High")
		self.assertContains(response, "View the full risk register")

		# No operations model stores risk text.
		for model in (OperationsEntry, OperationsNote, OperationsMetric):
			names = {f.name for f in model._meta.get_fields()}
			self.assertNotIn("risk", names)

	def test_an_annual_metric_is_not_chased_every_term(self):
		_show(self.env["school"], "estates-condition-grade")
		metric = OperationsMetric.objects.get(key="estates-condition-grade")
		self.assertEqual(metric.cycle, OperationsMetric.Cycle.ANNUAL)
		OperationsEntry.objects.create(
			school=self.env["school"], period=self.env["autumn"], metric=metric,
			band_choice="green",
		)
		spring = self.client.get("/review/operations/?year=2026-2027&round=2")
		tiles = [t for d in spring.context["domains"] for t in d["tiles"] if t["metric"] == metric]
		self.assertEqual(tiles[0]["rag"], "green", "an annual entry carries across terms")
		self.assertIsNotNone(tiles[0]["carried_from"])

	def test_the_baseline_is_shown_alongside_the_current_position(self):
		metric = OperationsMetric.objects.get(key="cyber-essentials")
		OperationsEntry.objects.create(
			school=self.env["school"], period=self.env["autumn"], metric=metric, band_choice="red"
		)
		OperationsEntry.objects.create(
			school=self.env["school"], period=self.env["spring"], metric=metric, band_choice="green"
		)
		spring = self.client.get("/review/operations/?year=2026-2027&round=2")
		tile = spring.context["domains"][0]["tiles"][0]
		self.assertEqual(tile["rag"], "green")
		self.assertIsNotNone(tile["baseline"])
		self.assertEqual(tile["baseline"].rag, "red")
		self.assertContains(spring, "Baseline (Autumn)")

	def test_metrics_are_labelled_benchmarked_or_judgement(self):
		_show(self.env["school"], "digital-technology-standards", "staff-sickness-absence")
		response = self.client.get("/review/operations/?year=2026-2027&round=1")
		self.assertContains(response, "Judgement-based")
		self.assertContains(response, "Hard-benchmarked")


class OperationsAdminGridTests(TestCase):
	def setUp(self):
		self.env = _ops_env()
		self.admin = User.objects.create_superuser("root", "root@x.test", "pw12345678")
		SchoolProfile.objects.create(user=self.admin, school=self.env["school"])
		self.client.force_login(self.admin)
		self.url = "/admin/review/operationsmetricvisibility/grid/"

	def test_the_grid_lists_every_metric_grouped_by_domain(self):
		response = self.client.get(self.url)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Cyber Essentials")
		self.assertContains(response, "Finance &amp; ICFP")
		self.assertContains(response, "0 of 12 metrics currently visible")

	def test_saving_the_grid_switches_metrics_on_without_a_deploy(self):
		metric = OperationsMetric.objects.get(key="cyber-essentials")
		response = self.client.post(
			self.url,
			{
				"action": "save",
				"school": self.env["school"].id,
				"year": "2026",
				"visible": [str(metric.id)],
			},
		)
		self.assertEqual(response.status_code, 302)
		self.assertTrue(
			OperationsMetricVisibility.objects.get(
				school=self.env["school"], year=2026, metric=metric
			).is_visible
		)
		# Everything else stays off.
		self.assertEqual(
			OperationsMetricVisibility.objects.filter(
				school=self.env["school"], year=2026, is_visible=True
			).count(),
			1,
		)

	def test_unticking_switches_a_metric_back_off(self):
		_show(self.env["school"], "cyber-essentials")
		self.client.post(
			self.url,
			{"action": "save", "school": self.env["school"].id, "year": "2026", "visible": []},
		)
		self.assertEqual(_visible_metric_ids(self.env["school"], 2026), set())


class OperationsColourTests(TestCase):
	def test_operations_colours_do_not_reuse_the_evaluation_or_risk_classes(self):
		base = Path(__file__).resolve().parent
		markup = (base / "templates" / "review" / "operations.html").read_text(encoding="utf-8")
		for cls in ("rag-pill", "rag-current", "score--", "overview-score", "sidebar-rating"):
			self.assertNotIn(cls, markup, f"operations.html must not reuse {cls}")

		css = (base / "static" / "review" / "styles.css").read_text(encoding="utf-8")
		ops_block = css[css.index("/* -- Operations & Resources"):]
		self.assertNotIn("var(--rag-", ops_block)
		for token in ("--ops-green", "--ops-amber", "--ops-red", "--ops-blue"):
			self.assertIn(f"{token}:", css)

		# Blue must not borrow the evaluation scale's blue, which is grade 1.
		rag_blue = css.split("--rag-blue:")[1].split(";")[0].strip()
		ops_blue = css.split("--ops-blue:")[1].split(";")[0].strip()
		self.assertNotEqual(rag_blue, ops_blue)


class TemplateCommentTests(TestCase):
	"""`{# ... #}` is single-line only.

	Django does not close a `{#` comment on a later line: the whole thing is
	emitted as page text instead. It has leaked twice, once onto the Trust
	Dashboard, which goes into board packs as a screenshot. Multi-line notes
	must use `{% comment %}`.
	"""

	def test_no_template_opens_a_hash_comment_it_does_not_close(self):
		root = Path(__file__).resolve().parent.parent
		offenders = []
		for path in sorted(root.glob("**/templates/**/*.html")):
			if "staticfiles" in path.parts or ".venv" in path.parts:
				continue
			for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
				if line.count("{#") != line.count("#}"):
					offenders.append(f"{path.relative_to(root)}:{number}")
		self.assertEqual(
			offenders,
			[],
			"a {# comment #} must open and close on one line — use "
			"{% comment %} for anything longer: " + ", ".join(offenders),
		)


class AdminIndexGroupingTests(TestCase):
	"""The admin index splits the single `review` app into named sections."""

	def setUp(self):
		self.admin = User.objects.create_superuser("root", "root@x.test", "pw12345678")
		self.client.force_login(self.admin)

	def test_risk_and_operations_have_their_own_headings(self):
		response = self.client.get("/admin/")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Risk register")
		self.assertContains(response, "Operations &amp; Resources (pilot)")
		self.assertContains(response, "In-depth review")

	def test_every_registered_review_model_appears_exactly_once(self):
		from django.contrib import admin as django_admin
		from django.test import RequestFactory

		request = RequestFactory().get("/admin/")
		request.user = self.admin

		registered = {
			model._meta.object_name
			for model, _ in django_admin.site._registry.items()
			if model._meta.app_label == "review"
		}
		listed = []
		for app in django_admin.site.get_app_list(request):
			if app.get("app_label") != "review":
				continue
			listed.extend(entry["object_name"] for entry in app["models"])

		self.assertEqual(
			sorted(listed),
			sorted(registered),
			"grouping the admin index must not drop or duplicate a model",
		)

	def test_the_single_app_page_still_lists_everything(self):
		response = self.client.get("/admin/review/")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Risks")
		self.assertContains(response, "Schools")



class LoginDoorsTests(TestCase):
	"""Every door into OSED applies the same pre-provisioning rule.

	Before the fix, /accounts/signup/ was open (an anonymous POST created an
	active user with a usable password) and a password login established a
	session for any active user, profile or not — the SchoolProfile gate lived
	only in the Microsoft adapter. Nothing exercised either adapter.
	"""

	PASSWORD = "Str0ng-Passw0rd!2026"

	def setUp(self):
		self.school = School.objects.create(name="Door School")
		# Active, usable password, NO SchoolProfile — the case that used to get in.
		self.orphan = User.objects.create_user(
			"orphan", "orphan@example.com", self.PASSWORD
		)
		# Active, provisioned.
		self.provisioned = User.objects.create_user(
			"provisioned", "provisioned@example.com", self.PASSWORD
		)
		profile = SchoolProfile.objects.create(user=self.provisioned, school=self.school)
		profile.schools.add(self.school)
		# Superuser with no profile — the break-glass path.
		self.super = User.objects.create_superuser(
			"super", "super@example.com", self.PASSWORD
		)
		# Provisioned but deactivated.
		self.inactive = User.objects.create_user(
			"inactive", "inactive@example.com", self.PASSWORD, is_active=False
		)
		inactive_profile = SchoolProfile.objects.create(user=self.inactive, school=self.school)
		inactive_profile.schools.add(self.school)

	def _password_login(self, email):
		return self.client.post(
			reverse("account_login"),
			{"login": email, "password": self.PASSWORD},
		)

	# --- self-registration -------------------------------------------------

	# Catches: /accounts/signup/ rendering a working registration form.
	def test_signup_page_redirects_to_login(self):
		resp = self.client.get(reverse("account_signup"))
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(resp.url, reverse("account_login"))

	# Catches: an anonymous POST to /accounts/signup/ creating a User.
	def test_signup_post_creates_no_user(self):
		before = User.objects.count()
		resp = self.client.post(
			reverse("account_signup"),
			{
				"email": "intruder@example.com",
				"username": "intruder",
				"password1": self.PASSWORD,
				"password2": self.PASSWORD,
			},
		)
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(resp.url, reverse("account_login"))
		self.assertEqual(User.objects.count(), before)
		self.assertFalse(User.objects.filter(email="intruder@example.com").exists())
		self.assertNotIn("_auth_user_id", self.client.session)

	# --- password login ----------------------------------------------------

	# Catches: a password login bypassing the SchoolProfile gate.
	def test_password_login_without_school_profile_gets_no_session(self):
		from .allauth_adapters import NO_SCHOOL

		resp = self._password_login("orphan@example.com")
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(resp.url, reverse("account_login"))
		self.assertNotIn("_auth_user_id", self.client.session)

		followed = self.client.get(reverse("account_login"))
		shown = [str(m) for m in followed.context["messages"]]
		self.assertIn(NO_SCHOOL, shown)

	# Catches: the gate over-reaching and locking out provisioned users.
	def test_password_login_with_school_profile_establishes_session(self):
		resp = self._password_login("provisioned@example.com")
		self.assertEqual(resp.status_code, 302)
		self.assertIn("_auth_user_id", self.client.session)
		self.assertEqual(
			int(self.client.session["_auth_user_id"]), self.provisioned.pk
		)

	# Catches: the break-glass superuser path being closed along with the rest.
	def test_superuser_without_profile_can_still_password_login(self):
		resp = self._password_login("super@example.com")
		self.assertEqual(resp.status_code, 302)
		self.assertIn("_auth_user_id", self.client.session)
		self.assertEqual(int(self.client.session["_auth_user_id"]), self.super.pk)

	# Catches: a deactivated account still able to sign in with its password.
	def test_inactive_user_password_login_gets_no_session(self):
		self._password_login("inactive@example.com")
		self.assertNotIn("_auth_user_id", self.client.session)

	# Catches: the password form reappearing on the public login page.
	def test_login_page_offers_microsoft_only(self):
		resp = self.client.get(reverse("account_login"))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, "Sign in with Microsoft")
		self.assertNotContains(resp, "id_password")
		self.assertNotContains(resp, 'name="password"')

	# --- the shared rule ---------------------------------------------------

	# Catches: the single provisioning rule drifting from what both adapters need.
	def test_provisioning_problem_rule(self):
		from .allauth_adapters import NO_SCHOOL, NOT_PROVISIONED, provisioning_problem

		self.assertEqual(provisioning_problem(None), NOT_PROVISIONED)
		self.assertEqual(provisioning_problem(self.inactive), NOT_PROVISIONED)
		self.assertIsNone(provisioning_problem(self.super))
		self.assertEqual(provisioning_problem(self.orphan), NO_SCHOOL)
		self.assertIsNone(provisioning_problem(self.provisioned))

	# --- Microsoft SSO path -----------------------------------------------

	def _social_request(self):
		from django.contrib.messages.storage.fallback import FallbackStorage
		from django.contrib.sessions.middleware import SessionMiddleware
		from django.test import RequestFactory

		request = RequestFactory().get("/accounts/microsoft/login/callback/")
		SessionMiddleware(lambda r: None).process_request(request)
		request.session.save()
		setattr(request, "_messages", FallbackStorage(request))
		return request

	def _sociallogin(self, email, uid="test-uid"):
		from allauth.socialaccount.models import SocialAccount, SocialLogin

		return SocialLogin(
			user=User(email=email),
			account=SocialAccount(provider="microsoft", uid=uid),
		)

	def _pre_social_login(self, email):
		from .allauth_adapters import RestrictMicrosoftLoginAdapter

		request = self._social_request()
		sociallogin = self._sociallogin(email)
		RestrictMicrosoftLoginAdapter().pre_social_login(request, sociallogin)
		return request, sociallogin

	# Catches: a Microsoft identity with no email being let through.
	def test_sso_rejects_missing_email(self):
		from allauth.core.exceptions import ImmediateHttpResponse

		with self.assertRaises(ImmediateHttpResponse) as ctx:
			self._pre_social_login("")
		self.assertEqual(ctx.exception.response.url, reverse("account_login"))

	# Catches: any tenant Microsoft account being auto-admitted.
	def test_sso_rejects_unknown_email(self):
		from allauth.core.exceptions import ImmediateHttpResponse

		with self.assertRaises(ImmediateHttpResponse) as ctx:
			self._pre_social_login("stranger@example.com")
		self.assertEqual(ctx.exception.response.url, reverse("account_login"))
		self.assertFalse(User.objects.filter(email="stranger@example.com").exists())

	# Catches: a known but unprovisioned user getting through SSO.
	def test_sso_rejects_user_without_school_profile(self):
		from allauth.core.exceptions import ImmediateHttpResponse
		from allauth.socialaccount.models import SocialAccount

		with self.assertRaises(ImmediateHttpResponse):
			self._pre_social_login("orphan@example.com")
		self.assertFalse(SocialAccount.objects.filter(user=self.orphan).exists())

	# Catches: a deactivated user getting through SSO.
	def test_sso_rejects_inactive_user(self):
		from allauth.core.exceptions import ImmediateHttpResponse

		with self.assertRaises(ImmediateHttpResponse):
			self._pre_social_login("inactive@example.com")

	# Catches: SSO admitting a provisioned user but failing to link the account.
	def test_sso_connects_provisioned_user(self):
		from allauth.socialaccount.models import SocialAccount

		_, sociallogin = self._pre_social_login("provisioned@example.com")
		self.assertEqual(sociallogin.user.pk, self.provisioned.pk)
		self.assertTrue(
			SocialAccount.objects.filter(
				user=self.provisioned, provider="microsoft", uid="test-uid"
			).exists()
		)

	# Catches: the superuser SSO path regressing when the profile check moved.
	def test_sso_connects_superuser_without_profile(self):
		from allauth.socialaccount.models import SocialAccount

		_, sociallogin = self._pre_social_login("super@example.com")
		self.assertEqual(sociallogin.user.pk, self.super.pk)
		self.assertTrue(SocialAccount.objects.filter(user=self.super).exists())

	# Catches: Entra returning a differently-cased email and being turned away.
	def test_sso_matches_email_case_insensitively(self):
		cfo = User.objects.create_user("cfo", "cfo@example.com", self.PASSWORD)
		profile = SchoolProfile.objects.create(user=cfo, school=self.school)
		profile.schools.add(self.school)

		_, sociallogin = self._pre_social_login("CFO@Example.com")
		self.assertEqual(sociallogin.user.pk, cfo.pk)
