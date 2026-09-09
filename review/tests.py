from __future__ import annotations

import importlib
import io

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib import admin as django_admin
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import RequestFactory, TestCase
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
from .admin import (
	CategoryAdmin,
	EvaluationAdmin,
	InDepthReviewAdmin,
	OperationsMetricAdmin,
	RiskAdmin,
	InDepthAreaAdmin,
	InDepthJudgementAreaAdmin,
	InDepthResponseAdmin,
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
		# Reload the command module between runs so each call starts from a fresh
		# BLUEPRINT, exactly as a real deploy does (Azure runs a new process each
		# time). The command no longer mutates that constant, so this is belt and
		# braces rather than a workaround — keep it, so a future change that does
		# mutate it cannot make these tests pass by accident.
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
		# Only our own templates. The project root holds both `venv` and `.venv`,
		# and only the dotted one was skipped — so this already scanned 200-odd
		# third-party templates, and the first installed package shipping a
		# multi-line {# comment #} would have failed the build pointing at a
		# stranger's file.
		skip = {"staticfiles", "venv", ".venv", "site-packages", "node_modules"}
		for path in sorted(root.glob("**/templates/**/*.html")):
			if skip.intersection(path.parts):
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


# ---------------------------------------------------------------------------
# Data-loss regressions
# ---------------------------------------------------------------------------


class StoredRatingSurvivesRestrictedChoicesTests(TestCase):
	"""A rating the admin allowed but a category's choice list does not.

	Safeguarding offers only Met (1) / Not Met (5), while the admin lets any
	1-5 through. A stored 3 drew no checked radio, so the browser posted no
	`rating` key at all and the save wrote None straight over the judgement.
	`_apply_category_specific_rating_choices` now appends the stored value —
	and only the stored value — to the list.
	"""

	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)
		self.safeguarding = Category.objects.create(name="Safeguarding", order=0, is_active=True)

		self.staff = User.objects.create_user(username="staff", email="staff@example.com")
		SchoolProfile.objects.create(user=self.staff, school=self.school)
		self.staff.schoolprofile.schools.add(self.school)
		for codename in ("add_evaluation", "change_evaluation"):
			self.staff.user_permissions.add(
				Permission.objects.get(content_type__app_label="review", codename=codename)
			)

		self.autumn, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		ReviewPeriod.objects.get_or_create(year=2026, round=2)
		ReviewPeriod.objects.get_or_create(year=2026, round=3)
		self.client.force_login(self.staff)

	def _dashboard_post(self, safeguarding_r1_rating):
		"""Post the full 2 categories x 3 terms grid the template renders."""
		return self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
				"form-TOTAL_FORMS": "6",
				"form-INITIAL_FORMS": "0",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				"form-0-category_id": str(self.safeguarding.id),
				"form-0-round": "1",
				"form-0-rating": safeguarding_r1_rating,
				"form-1-category_id": str(self.safeguarding.id),
				"form-1-round": "2",
				"form-1-rating": "",
				"form-2-category_id": str(self.safeguarding.id),
				"form-2-round": "3",
				"form-2-rating": "",
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

	# Catches: an unrenderable stored rating being rejected on the way back in,
	# so an unrelated edit elsewhere on the grid destroys a Safeguarding grade.
	def test_a_stored_safeguarding_rating_of_three_survives_a_dashboard_save(self):
		Evaluation.objects.create(
			school=self.school,
			period=self.autumn,
			category=self.safeguarding,
			rating=3,
		)

		resp = self._dashboard_post("3")

		self.assertEqual(resp.status_code, 302)
		saved = Evaluation.objects.get(
			school=self.school, period=self.autumn, category=self.safeguarding
		)
		self.assertEqual(saved.rating, 3)

	# Catches: the leak in the other direction — widening the choice list far
	# enough that a user can newly grade Safeguarding on the 1-5 scale.
	def test_a_new_off_list_safeguarding_rating_is_still_rejected(self):
		Evaluation.objects.create(
			school=self.school,
			period=self.autumn,
			category=self.safeguarding,
			rating=1,
		)

		resp = self._dashboard_post("3")

		self.assertEqual(resp.status_code, 200)
		saved = Evaluation.objects.get(
			school=self.school, period=self.autumn, category=self.safeguarding
		)
		self.assertEqual(saved.rating, 1)

	# Catches: the same nulling on the evaluation screen, which shares the helper
	# and would take the commentary's rating with it.
	def test_a_stored_safeguarding_rating_of_three_survives_an_evaluation_save(self):
		Evaluation.objects.create(
			school=self.school,
			period=self.autumn,
			category=self.safeguarding,
			rating=3,
			judgement_evidence="Single central record checked in September.",
		)

		resp = self.client.post(
			reverse("review:evaluation"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
				"round": "1",
				"form-TOTAL_FORMS": "2",
				"form-INITIAL_FORMS": "2",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				"form-0-category_id": str(self.safeguarding.id),
				"form-0-rating": "3",
				"form-0-judgement_evidence": "Single central record checked in September.",
				"form-0-to_progress": "",
				"form-1-category_id": str(self.category.id),
				"form-1-rating": "2",
				"form-1-judgement_evidence": "",
				"form-1-to_progress": "",
			},
		)

		self.assertEqual(resp.status_code, 302)
		saved = Evaluation.objects.get(
			school=self.school, period=self.autumn, category=self.safeguarding
		)
		self.assertEqual(saved.rating, 3)
		self.assertEqual(
			saved.judgement_evidence, "Single central record checked in September."
		)


class StaleWriteGuardTests(TestCase):
	"""A tab left open since yesterday posting over a colleague's newer work.

	Both the evaluation and dashboard forms post every cell they rendered, not
	just the one that changed, so a stale tab's empty commentary boxes were
	written straight over whatever had been saved since. The templates now carry
	`form_rendered_at` and the views skip any row touched after it.
	"""

	TAB_A_TEXT = "Attendance is improving; PA down 4 points on last term."
	TAB_B_TEXT = "Governors reviewed the improvement plan in November."

	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.first = Category.objects.create(name="Leadership", order=1, is_active=True)
		self.second = Category.objects.create(name="Attendance", order=2, is_active=True)

		self.staff = User.objects.create_user(username="staff", email="staff@example.com")
		SchoolProfile.objects.create(user=self.staff, school=self.school)
		self.staff.schoolprofile.schools.add(self.school)
		for codename in ("add_evaluation", "change_evaluation"):
			self.staff.user_permissions.add(
				Permission.objects.get(content_type__app_label="review", codename=codename)
			)

		self.autumn, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		self.client.force_login(self.staff)

		self.now = timezone.now()
		# Tab A's work, saved a minute ago. Tab B was drawn an hour ago.
		self.fresh_row = self._evaluation(self.first, self.TAB_A_TEXT)
		self._touch(self.fresh_row, self.now - timedelta(minutes=1))
		self.old_row = self._evaluation(self.second, "Original next-steps note.")
		self._touch(self.old_row, self.now - timedelta(hours=3))
		self.tab_b_rendered_at = (self.now - timedelta(hours=1)).isoformat()

	def _evaluation(self, category, text):
		return Evaluation.objects.create(
			school=self.school,
			period=self.autumn,
			category=category,
			rating=3,
			judgement_evidence=text,
		)

	@staticmethod
	def _touch(row, when):
		# updated_at is auto_now, so it has to be set with a queryset update.
		Evaluation.objects.filter(pk=row.pk).update(updated_at=when)

	def _evaluation_post(self, *, rendered_at, first_text, second_text):
		data = {
			"school_id": str(self.school.id),
			"year": "2026-2027",
			"round": "1",
			"form-TOTAL_FORMS": "2",
			"form-INITIAL_FORMS": "2",
			"form-MIN_NUM_FORMS": "0",
			"form-MAX_NUM_FORMS": "1000",
			"form-0-category_id": str(self.first.id),
			"form-0-rating": "3",
			"form-0-judgement_evidence": first_text,
			"form-0-to_progress": "",
			"form-1-category_id": str(self.second.id),
			"form-1-rating": "3",
			"form-1-judgement_evidence": second_text,
			"form-1-to_progress": "",
		}
		if rendered_at is not None:
			data["form_rendered_at"] = rendered_at
		return self.client.post(reverse("review:evaluation"), data=data)

	def _text(self, category):
		return Evaluation.objects.get(
			school=self.school, period=self.autumn, category=category
		).judgement_evidence

	# Catches: the whole point — a stale tab blanking commentary saved since.
	def test_a_stale_tab_does_not_blank_commentary_saved_after_it_was_opened(self):
		resp = self._evaluation_post(
			rendered_at=self.tab_b_rendered_at, first_text="", second_text=self.TAB_B_TEXT
		)

		self.assertEqual(resp.status_code, 302)
		self.assertEqual(self._text(self.first), self.TAB_A_TEXT)

	# Catches: over-correcting into a guard that discards the whole submission,
	# so the stale tab's own legitimate edit is silently dropped too.
	def test_a_stale_tab_still_saves_its_edit_to_an_untouched_row(self):
		resp = self._evaluation_post(
			rendered_at=self.tab_b_rendered_at, first_text="", second_text=self.TAB_B_TEXT
		)

		self.assertEqual(resp.status_code, 302)
		self.assertEqual(self._text(self.second), self.TAB_B_TEXT)

	# Catches: a cached template or an external poster losing its writes entirely
	# because the new field is absent.
	def test_a_post_without_the_timestamp_still_saves(self):
		resp = self._evaluation_post(
			rendered_at=None, first_text=self.TAB_B_TEXT, second_text=self.TAB_B_TEXT
		)

		self.assertEqual(resp.status_code, 302)
		self.assertEqual(self._text(self.first), self.TAB_B_TEXT)

	# Catches: the guard freezing a row nobody else has touched, so a real edit
	# looks saved and is not.
	def test_a_freshly_rendered_page_still_overwrites(self):
		resp = self._evaluation_post(
			rendered_at=timezone.now().isoformat(),
			first_text=self.TAB_B_TEXT,
			second_text=self.TAB_B_TEXT,
		)

		self.assertEqual(resp.status_code, 302)
		self.assertEqual(self._text(self.first), self.TAB_B_TEXT)

	# Catches: the dashboard grid, which posts 24 cells, reverting a rating.
	def test_a_stale_dashboard_tab_does_not_revert_a_newer_rating(self):
		Evaluation.objects.filter(pk=self.fresh_row.pk).update(rating=1)
		self._touch(self.fresh_row, self.now - timedelta(minutes=1))

		resp = self.client.post(
			reverse("review:dashboard"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
				"form_rendered_at": self.tab_b_rendered_at,
				"form-TOTAL_FORMS": "6",
				"form-INITIAL_FORMS": "0",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				"form-0-category_id": str(self.first.id),
				"form-0-round": "1",
				"form-0-rating": "4",
				"form-1-category_id": str(self.first.id),
				"form-1-round": "2",
				"form-1-rating": "",
				"form-2-category_id": str(self.first.id),
				"form-2-round": "3",
				"form-2-rating": "",
				"form-3-category_id": str(self.second.id),
				"form-3-round": "1",
				"form-3-rating": "2",
				"form-4-category_id": str(self.second.id),
				"form-4-round": "2",
				"form-4-rating": "",
				"form-5-category_id": str(self.second.id),
				"form-5-round": "3",
				"form-5-rating": "",
			},
		)

		self.assertEqual(resp.status_code, 302)
		self.assertEqual(Evaluation.objects.get(pk=self.fresh_row.pk).rating, 1)
		# The stale tab's edit to the row nobody touched still lands.
		self.assertEqual(Evaluation.objects.get(pk=self.old_row.pk).rating, 2)


class AdminDeleteProtectsWrittenWorkTests(TestCase):
	"""The catalogue models all cascade into a school's written work.

	Deleting a Category takes every school's judgement_evidence for it; an
	InDepthArea takes its reviews and every response beneath them. The admin's
	confirmation page counts objects, not terms of commentary, so nothing on
	screen stops you. `ProtectsWrittenWorkMixin` refuses the delete instead.
	"""

	def setUp(self):
		self.factory = RequestFactory()
		self.superuser = User.objects.create_superuser(
			"root", "root@example.com", "pw12345678"
		)
		self.school = School.objects.create(name="Test School")
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)

		self.used_category = Category.objects.create(name="Leadership", order=1)
		self.unused_category = Category.objects.create(name="Spare", order=9)
		Evaluation.objects.create(
			school=self.school,
			period=self.period,
			category=self.used_category,
			judgement_evidence="Three terms of commentary the admin cannot see.",
		)

		self.area = InDepthArea.objects.create(name="Achievement", order=1)
		standard = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.judgement_area = InDepthJudgementArea.objects.create(
			standard=standard, statement="Pupils achieve well.", order=1
		)
		review = InDepthReview.objects.create(
			school=self.school, year=2026, area=self.area
		)
		InDepthResponse.objects.create(
			review=review,
			judgement_area=self.judgement_area,
			rag="green",
			evidence_text="The school's own evidence write-up.",
		)

	def _request(self):
		request = self.factory.get("/admin/")
		request.user = self.superuser
		return request

	# Catches: deleting a Category taking every school's evaluation commentary.
	def test_a_category_with_an_evaluation_cannot_be_deleted(self):
		model_admin = CategoryAdmin(Category, django_admin.site)
		self.assertFalse(
			model_admin.has_delete_permission(self._request(), obj=self.used_category)
		)

	# Catches: over-blocking, so a genuinely unused catalogue row is undeletable.
	def test_a_category_with_no_evaluations_can_still_be_deleted(self):
		model_admin = CategoryAdmin(Category, django_admin.site)
		self.assertTrue(
			model_admin.has_delete_permission(self._request(), obj=self.unused_category)
		)

	# Catches: deleting an in-depth area cascading through reviews to responses.
	def test_an_indepth_area_with_a_review_cannot_be_deleted(self):
		model_admin = InDepthAreaAdmin(InDepthArea, django_admin.site)
		self.assertFalse(
			model_admin.has_delete_permission(self._request(), obj=self.area)
		)

	# Catches: deleting a single statement taking the evidence written against it.
	def test_a_judgement_area_with_a_response_cannot_be_deleted(self):
		model_admin = InDepthJudgementAreaAdmin(InDepthJudgementArea, django_admin.site)
		self.assertFalse(
			model_admin.has_delete_permission(
				self._request(), obj=self.judgement_area
			)
		)

	# Catches: the bulk action walking past the per-row guard — delete_selected
	# resolves permission per model, not per object.
	def test_bulk_delete_is_not_offered_on_a_protected_model(self):
		model_admin = CategoryAdmin(Category, django_admin.site)
		self.assertNotIn("delete_selected", model_admin.get_actions(self._request()))


class SeedCommandsRespectAdminEditsTests(TestCase):
	"""startup.sh re-runs the seeds on every Azure deploy.

	Their values are admin-editable on purpose — step_change and the turnover
	comparators exist so the client can correct them without a deploy — and
	School.phase selects which OperationsMetricBand rows a RAG is computed
	against. Re-applying the seed on an existing row reverted all of it.
	"""

	# So a failure names every reverted field, not the first one only.
	maxDiff = None

	def setUp(self):
		for order, name in enumerate(OPS_AREA_NAMES, start=1):
			InDepthArea.objects.get_or_create(name=name, defaults={"order": order * 10})
		call_command("seed_trust_categories", verbosity=0)
		call_command("seed_operations_metrics", verbosity=0)

	# Catches: a deploy silently reverting every admin correction. Also proves
	# load_indepth_blueprint survives a second call in one process.
	def test_a_second_deploy_does_not_revert_admin_edits(self):
		call_command("load_indepth_blueprint", verbosity=0)
		call_command("seed_schools", verbosity=0)

		metric = OperationsMetric.objects.get(key="complaints-stage-2")
		band = metric.bands.get(phase="")
		theme = ComplaintTheme.objects.get(name="Admissions")
		school = School.objects.get(name="Rose Hill School")
		area = InDepthArea.objects.get(name="Quality of Education")
		self.assertEqual(school.phase, School.Phase.PRIMARY)

		# The edits an admin would make in the change forms.
		OperationsMetric.objects.filter(pk=metric.pk).update(
			help_text="Trust wording agreed with the CFO."
		)
		OperationsMetricBand.objects.filter(pk=band.pk).update(step_change=5)
		ComplaintTheme.objects.filter(pk=theme.pk).update(is_active=False)
		School.objects.filter(pk=school.pk).update(phase=School.Phase.SECONDARY)
		InDepthArea.objects.filter(pk=area.pk).update(
			purpose="Our own wording for this area."
		)

		call_command("seed_operations_metrics", verbosity=0)
		call_command("seed_schools", verbosity=0)
		call_command("load_indepth_blueprint", verbosity=0)

		# Compared as one mapping so a redeploy that reverts three of the five
		# reports all three, rather than stopping at the first.
		self.assertEqual(
			{
				"metric help_text": OperationsMetric.objects.get(pk=metric.pk).help_text,
				"band step_change": OperationsMetricBand.objects.get(pk=band.pk).step_change,
				"theme is_active": ComplaintTheme.objects.get(pk=theme.pk).is_active,
				"school phase": School.objects.get(pk=school.pk).phase,
				"area purpose": InDepthArea.objects.get(pk=area.pk).purpose,
			},
			{
				"metric help_text": "Trust wording agreed with the CFO.",
				"band step_change": 5,
				"theme is_active": False,
				"school phase": School.Phase.SECONDARY,
				"area purpose": "Our own wording for this area.",
			},
		)

	# Catches: losing the deliberate way back to the seeded values.
	def test_force_restores_the_seed_value(self):
		metric = OperationsMetric.objects.get(key="complaints-stage-2")
		seeded_help_text = metric.help_text
		self.assertTrue(seeded_help_text)
		OperationsMetric.objects.filter(pk=metric.pk).update(help_text="edited")

		call_command("seed_operations_metrics", "--force", verbosity=0)

		self.assertEqual(
			OperationsMetric.objects.get(pk=metric.pk).help_text, seeded_help_text
		)

	# Catches: create-only defaults being applied so narrowly that a fresh
	# database gets an empty catalogue.
	def test_the_seed_still_builds_the_catalogue_from_empty(self):
		OperationsMetricBand.objects.all().delete()
		OperationsMetric.objects.all().delete()
		ComplaintTheme.objects.all().delete()

		call_command("seed_operations_metrics", verbosity=0)

		self.assertEqual(OperationsMetric.objects.count(), 12)
		self.assertEqual(ComplaintTheme.objects.count(), 4)
		band = OperationsMetric.objects.get(key="complaints-stage-2").bands.get(phase="")
		self.assertEqual(band.step_change, 3)
		self.assertTrue(band.green_descriptor)


class InDepthResponseAdminScopingTests(TestCase):
	"""The evidence text itself must not be readable across schools.

	This admin was the one school-linked admin with no `get_queryset`, so an
	is_staff account holding change_indepthresponse could read every school's
	write-ups. Guarding it is also the precondition for giving it a history view,
	which would otherwise expose every version rather than just the current one.
	"""

	def setUp(self):
		self.mine = School.objects.create(name="Mine Primary")
		self.theirs = School.objects.create(name="Theirs Primary")
		self.area = InDepthArea.objects.create(name="Achievement", order=1)
		standard = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.ja = InDepthJudgementArea.objects.create(
			standard=standard, statement="Pupils achieve well.", order=1
		)
		self.responses = {}
		for key, school in (("mine", self.mine), ("theirs", self.theirs)):
			review = InDepthReview.objects.create(school=school, year=2026, area=self.area)
			self.responses[key] = InDepthResponse.objects.create(
				review=review,
				judgement_area=self.ja,
				rag="green",
				evidence_text=f"{key.upper()} EVIDENCE TEXT",
			)

		self.staff = User.objects.create_user(
			username="staff", email="staff@example.com", is_staff=True
		)
		profile = SchoolProfile.objects.create(user=self.staff, school=self.mine)
		profile.schools.add(self.mine)
		self.staff.user_permissions.add(
			Permission.objects.get(
				content_type__app_label="review", codename="change_indepthresponse"
			)
		)

	def _queryset_for(self, user):
		request = RequestFactory().get("/admin/review/indepthresponse/")
		request.user = user
		model_admin = InDepthResponseAdmin(InDepthResponse, django_admin.site)
		return model_admin.get_queryset(request)

	def test_staff_user_sees_only_their_own_schools_evidence(self):
		visible = list(self._queryset_for(self.staff))
		self.assertIn(self.responses["mine"], visible)
		self.assertNotIn(self.responses["theirs"], visible)

	def test_superuser_still_sees_every_school(self):
		root = User.objects.create_superuser(
			username="root", email="root@example.com", password="x"
		)
		visible = list(self._queryset_for(root))
		self.assertIn(self.responses["mine"], visible)
		self.assertIn(self.responses["theirs"], visible)


class EvaluationVersionHistoryTests(TestCase):
	"""The version trail itself — is an edit recoverable afterwards?

	The feature exists so commentary lost to an overwrite, or taken out by a
	cascade from a catalogue row, can still be read back. These prove the trail
	is written, is readable at a point in time, survives the live row, and
	records who made the change.
	"""

	ORIGINAL = "Attendance is improving; PA down 4 points on last term."
	REVISED = "Attendance has stalled; PA flat since September."

	def setUp(self):
		self.school = School.objects.create(name="Test School")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		self.evaluation = Evaluation.objects.create(
			school=self.school,
			period=self.period,
			category=self.category,
			rating=3,
			judgement_evidence=self.ORIGINAL,
		)

	def _edit(self, text=REVISED):
		self.evaluation.judgement_evidence = text
		self.evaluation.save()

	# Catches: no trail being written at all — the manager dropped from the
	# model, or migration 0034 never applied.
	def test_editing_commentary_records_a_new_version(self):
		self.assertEqual(self.evaluation.history.count(), 1)

		self._edit()

		self.assertEqual(self.evaluation.history.count(), 2)
		self.assertEqual(
			list(
				self.evaluation.history.order_by("history_date").values_list(
					"history_type", flat=True
				)
			),
			["+", "~"],
		)

	# Catches: the trail storing today's values on every row, so a point-in-time
	# read hands back the current text instead of what was live then.
	def test_history_as_of_returns_the_text_that_was_live_at_that_moment(self):
		before_edit = timezone.now()
		self._edit()

		self.assertEqual(
			self.evaluation.history.as_of(before_edit).judgement_evidence,
			self.ORIGINAL,
		)
		snapshot = Evaluation.history.as_of(before_edit).filter(id=self.evaluation.pk).first()
		self.assertEqual(snapshot.judgement_evidence, self.ORIGINAL)
		self.assertEqual(
			Evaluation.objects.get(pk=self.evaluation.pk).judgement_evidence,
			self.REVISED,
		)

	# Catches: excluded_fields being wrong, so a diff either names nothing (the
	# real change swallowed) or names updated_at on every save.
	def test_diff_between_versions_names_the_field_that_changed(self):
		self._edit()

		newest = self.evaluation.history.first()
		changed = [change.field for change in newest.diff_against(newest.prev_record).changes]

		self.assertEqual(changed, ["judgement_evidence"])

	# Catches: the recovery property — a cascade delete (here a ReviewPeriod
	# taking a whole term of commentary with it) also wiping the trail, leaving
	# nothing to recover from. This is the reason the feature exists.
	def test_history_survives_a_cascade_delete_of_the_review_period(self):
		self._edit()
		evaluation_id = self.evaluation.pk

		self.period.delete()

		self.assertFalse(Evaluation.objects.filter(pk=evaluation_id).exists())
		trail = list(Evaluation.history.filter(id=evaluation_id).order_by("history_date"))
		self.assertEqual([row.history_type for row in trail], ["+", "~", "-"])
		self.assertEqual(trail[0].judgement_evidence, self.ORIGINAL)
		self.assertIn(self.REVISED, [row.judgement_evidence for row in trail])

	# Catches: HistoryRequestMiddleware missing or mis-ordered, so every version
	# is anonymous and the trail cannot say who changed what.
	def test_history_user_is_the_logged_in_editor_and_none_for_a_code_change(self):
		editor = User.objects.create_user(username="editor", email="editor@example.com")
		SchoolProfile.objects.create(user=editor, school=self.school)
		editor.schoolprofile.schools.add(self.school)
		for codename in ("add_evaluation", "change_evaluation"):
			editor.user_permissions.add(
				Permission.objects.get(
					content_type__app_label="review", codename=codename
				)
			)
		self.client.force_login(editor)

		resp = self.client.post(
			reverse("review:evaluation"),
			data={
				"school_id": str(self.school.id),
				"year": "2026-2027",
				"round": "1",
				"form-TOTAL_FORMS": "1",
				"form-INITIAL_FORMS": "1",
				"form-MIN_NUM_FORMS": "0",
				"form-MAX_NUM_FORMS": "1000",
				"form-0-category_id": str(self.category.id),
				"form-0-rating": "3",
				"form-0-judgement_evidence": self.REVISED,
				"form-0-to_progress": "",
			},
		)
		self.assertEqual(resp.status_code, 302)

		through_the_request = self.evaluation.history.first()
		self.assertEqual(through_the_request.judgement_evidence, self.REVISED)
		self.assertEqual(through_the_request.history_user, editor)

		# A save with no request behind it (management command, shell, migration)
		# records no user, which is the correct answer rather than a guess.
		self.evaluation.refresh_from_db()
		self.evaluation.judgement_evidence = "Corrected by a management command."
		self.evaluation.save()

		self.assertIsNone(self.evaluation.history.first().history_user)


class AdminHistoryTabScopingTests(TestCase):
	"""The admin History tab must stay inside the user's own schools.

	SimpleHistoryAdmin falls back to rebuilding the object from the history
	table when get_queryset finds nothing, and gates that on a model-level
	permission that ignores the object — so without scoping, a staff user for
	one school reads another school's whole version trail, not merely its
	current row.
	"""

	MINE = "Mine Primary attendance commentary for the autumn term."
	THEIRS = "Theirs Primary safeguarding commentary for the autumn term."
	MINE_EVIDENCE = "Mine Primary in-depth evidence write-up."
	THEIRS_EVIDENCE = "Theirs Primary in-depth evidence write-up."

	def setUp(self):
		self.mine = School.objects.create(name="Mine Primary")
		self.theirs = School.objects.create(name="Theirs Primary")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)

		self.my_eval = self._evaluation(self.mine, self.MINE)
		self.their_eval = self._evaluation(self.theirs, self.THEIRS)

		self.area = InDepthArea.objects.create(name="Achievement", order=1)
		standard = InDepthStandard.objects.create(
			area=self.area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		self.judgement_area = InDepthJudgementArea.objects.create(
			standard=standard, statement="Pupils achieve well.", order=1
		)
		self.my_response = self._response(self.mine, self.MINE_EVIDENCE)
		self.their_response = self._response(self.theirs, self.THEIRS_EVIDENCE)

		self.staff = User.objects.create_user(
			username="staff", email="staff@example.com", is_staff=True
		)
		profile = SchoolProfile.objects.create(user=self.staff, school=self.mine)
		profile.schools.add(self.mine)
		for codename in (
			"view_evaluation",
			"change_evaluation",
			"view_indepthresponse",
			"change_indepthresponse",
		):
			self.staff.user_permissions.add(
				Permission.objects.get(
					content_type__app_label="review", codename=codename
				)
			)

	def _evaluation(self, school, text):
		row = Evaluation.objects.create(
			school=school,
			period=self.period,
			category=self.category,
			rating=3,
			judgement_evidence=text,
		)
		# A second version, so there is a trail to leak rather than one row.
		row.judgement_evidence = f"{text} Revised."
		row.save()
		return row

	def _response(self, school, text):
		review = InDepthReview.objects.create(school=school, year=2026, area=self.area)
		row = InDepthResponse.objects.create(
			review=review,
			judgement_area=self.judgement_area,
			rag="green",
			evidence_text=text,
		)
		row.evidence_text = f"{text} Revised."
		row.save()
		return row

	# Catches: over-filtering — a scope so tight the user cannot read the trail
	# for their own school's row either.
	def test_scoped_staff_user_can_open_their_own_schools_evaluation_history(self):
		self.client.force_login(self.staff)

		resp = self.client.get(f"/admin/review/evaluation/{self.my_eval.pk}/history/")

		self.assertEqual(resp.status_code, 200)

	# Catches: a staff user for one school reading another school's commentary,
	# including superseded versions, through the History tab.
	def test_staff_user_cannot_open_another_schools_evaluation_history(self):
		self.client.force_login(self.staff)

		resp = self.client.get(f"/admin/review/evaluation/{self.their_eval.pk}/history/")

		self.assertEqual(resp.status_code, 404)
		self.assertNotContains(resp, self.THEIRS, status_code=404)

	# Catches: the scoping being applied to superusers too, who bypass school
	# scoping everywhere else by design.
	def test_superuser_can_open_any_schools_evaluation_history(self):
		root = User.objects.create_superuser(
			username="root", email="root@example.com", password="pw12345678"
		)
		self.client.force_login(root)

		resp = self.client.get(f"/admin/review/evaluation/{self.their_eval.pk}/history/")

		self.assertEqual(resp.status_code, 200)

	# Catches: the two-hop review__school path being wrong or unapplied on the
	# model that holds the in-depth write-ups themselves.
	def test_staff_user_cannot_open_another_schools_indepth_response_history(self):
		self.client.force_login(self.staff)

		resp = self.client.get(
			f"/admin/review/indepthresponse/{self.their_response.pk}/history/"
		)

		self.assertEqual(resp.status_code, 404)
		self.assertNotContains(resp, self.THEIRS_EVIDENCE, status_code=404)

	# Catches: a review__school filter that 404s everything, which would pass the
	# test above while breaking the tab for its owner.
	def test_scoped_staff_user_can_still_open_their_own_indepth_response_history(self):
		self.client.force_login(self.staff)

		resp = self.client.get(
			f"/admin/review/indepthresponse/{self.my_response.pk}/history/"
		)

		self.assertEqual(resp.status_code, 200)


class AdminHistoryRevertScopingTests(TestCase):
	"""The revert view — read and write, on a URL the library leaves open.

	SimpleHistoryAdmin.history_form_view resolves the historical record through
	the default manager and gates it on a model-level permission, then its POST
	branch writes with no change check at all. Before the guard, a staff user
	scoped to one school could GET another school's revert URL, read the
	commentary, and POST to overwrite that school's live row.
	"""

	MINE_ORIGINAL = "Mine Primary attendance commentary, first draft."
	MINE_REVISED = "Mine Primary attendance commentary, second draft."
	THEIRS_ORIGINAL = "Theirs Primary safeguarding commentary, first draft."
	THEIRS_REVISED = "Theirs Primary safeguarding commentary, second draft."
	ATTACKER_TEXT = "Overwritten from another school."

	def setUp(self):
		self.mine = School.objects.create(name="Mine Primary")
		self.theirs = School.objects.create(name="Theirs Primary")
		self.category = Category.objects.create(name="Leadership", order=1, is_active=True)
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)

		self.my_eval = self._evaluation(self.mine, self.MINE_ORIGINAL, self.MINE_REVISED)
		self.their_eval = self._evaluation(
			self.theirs, self.THEIRS_ORIGINAL, self.THEIRS_REVISED
		)
		self.my_first_version = self.my_eval.history.order_by("history_date").first()
		self.their_first_version = self.their_eval.history.order_by("history_date").first()

		self.staff = self._staff_user("staff", ("view_evaluation", "change_evaluation"))
		self.readonly_staff = self._staff_user("readonly", ("view_evaluation",))

	def _evaluation(self, school, original, revised):
		row = Evaluation.objects.create(
			school=school,
			period=self.period,
			category=self.category,
			rating=3,
			judgement_evidence=original,
		)
		row.judgement_evidence = revised
		row.rating = 4
		row.save()
		return row

	def _staff_user(self, username, codenames):
		user = User.objects.create_user(
			username=username, email=f"{username}@example.com", is_staff=True
		)
		profile = SchoolProfile.objects.create(user=user, school=self.mine)
		profile.schools.add(self.mine)
		for codename in codenames:
			user.user_permissions.add(
				Permission.objects.get(
					content_type__app_label="review", codename=codename
				)
			)
		return user

	@staticmethod
	def _revert_url(evaluation, version):
		return f"/admin/review/evaluation/{evaluation.pk}/history/{version.history_id}/"

	@staticmethod
	def _post_data(version, **overrides):
		data = {
			"school": str(version.school_id),
			"period": str(version.period_id),
			"category": str(version.category_id),
			"rating": "" if version.rating is None else str(version.rating),
			"judgement_evidence": version.judgement_evidence,
			"to_progress": version.to_progress,
		}
		data.update(overrides)
		return data

	def _live(self, evaluation):
		return Evaluation.objects.get(pk=evaluation.pk)

	# Catches: the read half of the hole — another school's superseded
	# commentary rendered into a revert form for a user with no access to it.
	def test_user_cannot_get_another_schools_revert_page(self):
		self.client.force_login(self.staff)

		resp = self.client.get(self._revert_url(self.their_eval, self.their_first_version))

		self.assertEqual(resp.status_code, 404)
		self.assertNotContains(resp, self.THEIRS_ORIGINAL, status_code=404)
		self.assertNotContains(resp, self.THEIRS_REVISED, status_code=404)

	# Catches: the write half — a cross-school POST overwriting the victim's
	# live row, which the ordinary change view correctly refuses.
	def test_user_cannot_post_to_another_schools_revert_page(self):
		self.client.force_login(self.staff)

		resp = self.client.post(
			self._revert_url(self.their_eval, self.their_first_version),
			data=self._post_data(
				self.their_first_version, judgement_evidence=self.ATTACKER_TEXT
			),
		)

		self.assertEqual(resp.status_code, 404)
		victim = self._live(self.their_eval)
		self.assertEqual(victim.judgement_evidence, self.THEIRS_REVISED)
		self.assertEqual(victim.rating, 4)
		self.assertNotIn(
			self.ATTACKER_TEXT,
			list(
				Evaluation.history.filter(id=self.their_eval.pk).values_list(
					"judgement_evidence", flat=True
				)
			),
		)

	# Catches: a guard that closes the hole by breaking the feature — the
	# legitimate revert of the user's own school must still work.
	def test_user_can_revert_their_own_schools_row_to_an_earlier_version(self):
		self.client.force_login(self.staff)
		url = self._revert_url(self.my_eval, self.my_first_version)

		self.assertEqual(self.client.get(url).status_code, 200)
		resp = self.client.post(url, data=self._post_data(self.my_first_version))

		self.assertEqual(resp.status_code, 302)
		restored = self._live(self.my_eval)
		self.assertEqual(restored.judgement_evidence, self.MINE_ORIGINAL)
		self.assertEqual(restored.rating, 3)

	# Catches: privilege escalation — the library's POST branch writes without
	# any change-permission check, so a view-only account silently reverted the
	# live row.
	def test_view_only_user_cannot_post_a_revert_of_their_own_schools_row(self):
		self.client.force_login(self.readonly_staff)

		resp = self.client.post(
			self._revert_url(self.my_eval, self.my_first_version),
			data=self._post_data(self.my_first_version),
		)

		self.assertEqual(resp.status_code, 403)
		self.assertEqual(self._live(self.my_eval).judgement_evidence, self.MINE_REVISED)


class HistoryPageSurvivesDeletedParentTests(TestCase):
	"""The recovery case must not 500.

	A historical row outlives its parent on purpose. The admin history page calls
	str() on an instance rebuilt from that row, so a __str__ dereferencing a
	deleted foreign key raised DoesNotExist and the page died -- in exactly the
	situation someone was trying to recover from.
	"""

	def setUp(self):
		self.school = School.objects.create(name="Britannia Primary")
		self.root = User.objects.create_superuser(
			username="root", email="root@example.com", password="pw"
		)
		self.client.force_login(self.root)

	def test_indepth_response_history_renders_after_its_review_is_deleted(self):
		area = InDepthArea.objects.create(name="Achievement", order=1)
		standard = InDepthStandard.objects.create(
			area=area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		ja = InDepthJudgementArea.objects.create(
			standard=standard, statement="Pupils achieve well.", order=1
		)
		review = InDepthReview.objects.create(school=self.school, year=2026, area=area)
		response = InDepthResponse.objects.create(
			review=review, judgement_area=ja, rag="green",
			evidence_text="THE LOST WRITE UP",
		)
		response.evidence_text = "THE LOST WRITE UP, REVISED"
		response.save()
		pk = response.pk

		review.delete()  # cascades the live response away

		self.assertEqual(InDepthResponse.objects.filter(pk=pk).count(), 0)
		self.assertTrue(InDepthResponse.history.filter(id=pk).exists())
		page = self.client.get(f"/admin/review/indepthresponse/{pk}/history/")
		self.assertEqual(page.status_code, 200)

	def test_str_does_not_raise_when_the_parent_is_gone(self):
		area = InDepthArea.objects.create(name="Inclusion", order=2)
		standard = InDepthStandard.objects.create(
			area=area, key=InDepthStandard.Key.EXPECTED_STANDARD, order=3
		)
		ja = InDepthJudgementArea.objects.create(
			standard=standard, statement="All pupils belong.", order=1
		)
		review = InDepthReview.objects.create(school=self.school, year=2026, area=area)
		response = InDepthResponse.objects.create(
			review=review, judgement_area=ja, evidence_text="text"
		)
		pk = response.pk
		review.delete()
		rebuilt = InDepthResponse.history.filter(id=pk).first().instance
		# The assertion is simply that this does not raise.
		self.assertIn("deleted review", str(rebuilt))


class HistoryDiffIsReadableTests(TestCase):
	"""The diff must show the commentary, not elide it.

	django-simple-history truncates each changed value to 100 characters, so a
	150-word write-up rendered as "Attendance at safeguard[719 chars]uary." --
	the page hid the very text you opened it to recover.
	"""

	def test_a_long_commentary_is_not_truncated_in_the_history_diff(self):
		school = School.objects.create(name="Britannia Primary")
		category = Category.objects.create(name="Safeguarding", order=10)
		period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		long_text = (
			"Attendance at safeguarding training was 100 percent for teaching staff. "
			* 12
		) + "ENDMARKER"
		self.assertGreater(len(long_text), 800)

		evaluation = Evaluation.objects.create(
			school=school, period=period, category=category,
			judgement_evidence="Short note.",
		)
		evaluation.judgement_evidence = long_text
		evaluation.save()

		root = User.objects.create_superuser(
			username="root", email="root@example.com", password="pw"
		)
		self.client.force_login(root)
		page = self.client.get(f"/admin/review/evaluation/{evaluation.pk}/history/")
		self.assertEqual(page.status_code, 200)
		body = page.content.decode()
		self.assertNotIn("chars]", body)
		self.assertIn("ENDMARKER", body)


class AdminSchoolChoicesAreScopedTests(TestCase):
	"""A user must not be able to move their own record into another school.

	get_queryset stops them opening someone else's record; nothing stopped them
	reassigning their own, because the school dropdown listed the whole Trust.
	"""

	def setUp(self):
		self.mine = School.objects.create(name="Mine Primary")
		self.theirs = School.objects.create(name="Theirs Primary")
		self.staff = User.objects.create_user(
			username="staff", email="staff@example.com", is_staff=True
		)
		profile = SchoolProfile.objects.create(user=self.staff, school=self.mine)
		profile.schools.add(self.mine)
		self.staff.user_permissions.add(
			Permission.objects.get(
				content_type__app_label="review", codename="change_evaluation"
			)
		)

	def _school_choices_for(self, user):
		request = RequestFactory().get("/admin/review/evaluation/1/change/")
		request.user = user
		model_admin = EvaluationAdmin(Evaluation, django_admin.site)
		field = model_admin.formfield_for_foreignkey(
			Evaluation._meta.get_field("school"), request
		)
		return list(field.queryset)

	def test_staff_user_is_offered_only_their_own_schools(self):
		self.assertEqual(self._school_choices_for(self.staff), [self.mine])

	def test_superuser_is_offered_every_school(self):
		root = User.objects.create_superuser(
			username="root", email="root@example.com", password="pw"
		)
		self.assertCountEqual(
			self._school_choices_for(root), [self.mine, self.theirs]
		)


class RiskSignOffFieldsAreGatedTests(TestCase):
	"""close_qa_by / close_qa_at are the CFO's signature, not a form field.

	Anyone holding change_risk could set them and manufacture the sign-off the
	Committee relies on.
	"""

	def setUp(self):
		self.school = School.objects.create(name="Britannia Primary")
		self.staff = User.objects.create_user(
			username="principal", email="p@example.com", is_staff=True
		)
		profile = SchoolProfile.objects.create(user=self.staff, school=self.school)
		profile.schools.add(self.school)

	def _readonly_for(self, user):
		request = RequestFactory().get("/admin/review/risk/1/change/")
		request.user = user
		return RiskAdmin(Risk, django_admin.site).get_readonly_fields(request)

	def test_principal_cannot_edit_the_sign_off_fields(self):
		readonly = self._readonly_for(self.staff)
		self.assertIn("close_qa_by", readonly)
		self.assertIn("close_qa_at", readonly)

	def test_a_qa_user_can_edit_them(self):
		self.staff.user_permissions.add(
			Permission.objects.get(
				content_type__app_label="review", codename="qa_risk"
			)
		)
		refreshed = User.objects.get(pk=self.staff.pk)
		readonly = self._readonly_for(refreshed)
		self.assertNotIn("close_qa_by", readonly)
		self.assertNotIn("close_qa_at", readonly)


# ---------------------------------------------------------------------------
# Nothing that runs on a deploy, on a save, or on a history prune may touch a
# row a person has written. These take a snapshot of every version-tracked row
# and diff it, rather than asserting one field on one model.
# ---------------------------------------------------------------------------

_TRACKED_MODELS = (Evaluation, InDepthReview, InDepthResponse, OperationsEntry, OperationsNote, Risk)
_AUTO_STAMPS = {"updated_at", "recorded_at", "created_at"}


def _snapshot_tracked_rows():
	"""Every concrete field of every tracked row, minus the auto timestamps."""
	out = {}
	for model in _TRACKED_MODELS:
		for row in model.objects.all():
			out[(model.__name__, row.pk)] = {
				f.attname: getattr(row, f.attname)
				for f in model._meta.concrete_fields
				if f.name not in _AUTO_STAMPS
			}
	return out


def _run_full_deploy_chain():
	"""The seed commands startup.sh runs, in its order (migrate is implicit)."""
	importlib.reload(importlib.import_module("review.management.commands.load_indepth_blueprint"))
	for command in (
		"ensure_schema", "seed_categories", "load_indepth_blueprint", "load_indepth_criteria",
		"seed_trust_categories", "seed_operations_metrics", "import_indepth_workbooks",
		"seed_schools", "seed_branding",
	):
		call_command(command, verbosity=0)


def _populate_every_tracked_model(school):
	"""Written work on all six tracked models for one school."""
	periods = [ReviewPeriod.objects.get_or_create(year=2026, round=r)[0] for r in (1, 2, 3)]
	for period in periods:
		for category in Category.objects.filter(is_active=True):
			Evaluation.objects.create(
				school=school, period=period, category=category, rating=3,
				judgement_evidence=f"EV {period.round} {category.name}", to_progress="NEXT",
			)
		OperationsNote.objects.create(school=school, period=period, text=f"NOTE {period.round}")
		for metric in OperationsMetric.objects.all()[:3]:
			OperationsEntry.objects.create(
				school=school, period=period, metric=metric, commentary=f"OPS {metric.key}",
			)
	for area in InDepthArea.objects.filter(standards__isnull=False).distinct()[:3]:
		review = InDepthReview.objects.create(
			school=school, year=2026, area=area, overall_grade="expected_standard",
			qa_reflection=f"REFL {area.name}", needs_attention_comment="NA",
		)
		for ja in InDepthJudgementArea.objects.filter(standard__area=area, is_flat=False)[:2]:
			InDepthResponse.objects.create(
				review=review, judgement_area=ja, rag="green",
				evidence_text=f"IDR {ja.pk}", next_steps="NS",
			)
	Risk.objects.create(
		school=school, category=TrustCategory.objects.first(), title="RISK", mitigation="MIT",
	)


class DeployChainLeavesWrittenWorkUntouchedTests(TestCase):
	"""Two consecutive full deploy chains must not alter a single tracked row."""

	def test_two_deploys_change_nothing(self):
		_run_full_deploy_chain()
		school, _ = School.objects.get_or_create(name="Britannia Primary and Nursery School")
		_populate_every_tracked_model(school)
		before = _snapshot_tracked_rows()
		self.assertGreater(len(before), 40)

		_run_full_deploy_chain()
		_run_full_deploy_chain()

		after = _snapshot_tracked_rows()
		self.assertEqual(set(before), set(after), "rows were lost on deploy")
		self.assertEqual(before, after, "row contents changed on deploy")


class EvaluationSaveTouchesOnlyChangedRowsTests(TestCase):
	"""Saving the evaluation page must write only the categories that changed.

	It used to rewrite all eight rows on every save, stamping updated_by on
	seven the user never touched and leaving a no-op history entry on each.
	"""

	def setUp(self):
		call_command("seed_categories", verbosity=0)
		self.school = School.objects.create(name="Britannia Primary")
		self.user = User.objects.create_user(username="head", email="head@example.com")
		profile = SchoolProfile.objects.create(user=self.user, school=self.school)
		profile.schools.add(self.school)
		for codename in ("add_evaluation", "change_evaluation"):
			self.user.user_permissions.add(
				Permission.objects.get(content_type__app_label="review", codename=codename)
			)
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		self.categories = list(Category.objects.filter(is_active=True).order_by("order", "name"))
		for category in self.categories:
			Evaluation.objects.create(
				school=self.school, period=self.period, category=category,
				rating=3, judgement_evidence=f"ORIGINAL {category.name}",
			)

	def test_only_the_edited_category_is_written(self):
		target = self.categories[0]
		data = {
			"school_id": str(self.school.id), "year": "2026-2027", "round": "1",
			"form-TOTAL_FORMS": str(len(self.categories)),
			"form-INITIAL_FORMS": str(len(self.categories)),
			"form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
		}
		for i, category in enumerate(self.categories):
			current = Evaluation.objects.get(school=self.school, period=self.period, category=category)
			data[f"form-{i}-category_id"] = str(category.id)
			data[f"form-{i}-rating"] = str(current.rating)
			data[f"form-{i}-judgement_evidence"] = (
				"EDITED" if category == target else current.judgement_evidence
			)
			data[f"form-{i}-to_progress"] = current.to_progress

		self.client.force_login(self.user)
		self.assertEqual(self.client.post(reverse("review:evaluation"), data=data).status_code, 302)

		for category in self.categories:
			row = Evaluation.objects.get(school=self.school, period=self.period, category=category)
			if category == target:
				self.assertEqual(row.judgement_evidence, "EDITED")
				self.assertEqual(row.updated_by, self.user)
				self.assertEqual(row.history.count(), 2)
			else:
				self.assertEqual(row.judgement_evidence, f"ORIGINAL {category.name}")
				self.assertIsNone(row.updated_by, f"{category.name} was stamped though untouched")
				self.assertEqual(row.history.count(), 1, f"{category.name} gained a no-op version")


class RemainingAdminCascadeGuardsTests(TestCase):
	"""OperationsMetric and InDepthReview cascade into commentary too."""

	def setUp(self):
		call_command("seed_trust_categories", verbosity=0)
		call_command("seed_operations_metrics", verbosity=0)
		root = User.objects.create_superuser(username="root", email="root@example.com", password="pw")
		self.request = RequestFactory().get("/admin/")
		self.request.user = root
		self.school = School.objects.create(name="Britannia Primary")
		self.period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)

	def test_metric_with_entries_cannot_be_deleted(self):
		used, unused = list(OperationsMetric.objects.all()[:2])
		OperationsEntry.objects.create(school=self.school, period=self.period, metric=used, commentary="text")
		model_admin = OperationsMetricAdmin(OperationsMetric, django_admin.site)
		self.assertFalse(model_admin.has_delete_permission(self.request, used))
		self.assertTrue(model_admin.has_delete_permission(self.request, unused))
		self.assertNotIn("delete_selected", model_admin.get_actions(self.request))

	def test_review_with_written_work_cannot_be_deleted(self):
		area = InDepthArea.objects.create(name="Achievement", order=1)
		with_text = InDepthReview.objects.create(school=self.school, year=2026, area=area, qa_reflection="REFL")
		empty = InDepthReview.objects.create(school=self.school, year=2027, area=area)
		model_admin = InDepthReviewAdmin(InDepthReview, django_admin.site)
		self.assertFalse(model_admin.has_delete_permission(self.request, with_text))
		self.assertTrue(model_admin.has_delete_permission(self.request, empty))


class PruneHistoryCommandTests(TestCase):
	"""The retention policy: dry run by default, and never near a live row."""

	def setUp(self):
		self.school = School.objects.create(name="Britannia Primary")
		category = Category.objects.create(name="Safeguarding", order=10)
		period, _ = ReviewPeriod.objects.get_or_create(year=2026, round=1)
		self.evaluation = Evaluation.objects.create(
			school=self.school, period=period, category=category, judgement_evidence="v1",
		)
		self.evaluation.judgement_evidence = "v2"
		self.evaluation.save()
		self.assertEqual(Evaluation.history.count(), 2)

	def test_dry_run_is_the_default_and_deletes_nothing(self):
		out = io.StringIO()
		call_command("prune_history", "--days", "0", stdout=out)
		self.assertEqual(Evaluation.history.count(), 2)
		self.assertIn("DRY RUN", out.getvalue())

	def test_apply_deletes_old_history_but_never_the_live_row(self):
		before = _snapshot_tracked_rows()
		call_command("prune_history", "--days", "0", "--apply", stdout=io.StringIO())
		self.assertEqual(Evaluation.history.count(), 0)
		self.assertEqual(_snapshot_tracked_rows(), before)
		self.evaluation.refresh_from_db()
		self.assertEqual(self.evaluation.judgement_evidence, "v2")

	def test_default_window_is_three_months(self):
		from review.management.commands.prune_history import RETENTION_DAYS
		self.assertEqual(RETENTION_DAYS, 90)
