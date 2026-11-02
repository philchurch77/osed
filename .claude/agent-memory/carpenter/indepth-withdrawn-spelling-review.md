---
name: indepth-withdrawn-spelling-review
description: Findings from reviewing the is_active/withdrawn-statement + spelling-warning change (29 Sept 2026, pre-commit)
metadata:
  type: project
---

Reviewed uncommitted diff adding `InDepthJudgementArea.is_active` (withdrawn
statements), statement-number chips, and `review/spelling.py` (post-save
spelling warning on in-depth commentary).

**What I found and reported** (not re-litigate on a future pass unless the
code changed):
- No test coverage at all for `is_active`/withdrawn behaviour, the view's
  grading exclusion, the read-only withdrawn commentary section, or
  `spelling.py`. The two existing `_indepth_sync` tests
  (`test_retired_statement_with_responses_is_kept_not_deleted` etc., around
  `review/tests.py:1548-1574`) predate this diff and never assert
  `is_active`. Flagged High — check on next pass whether tests were added.
- The chip markup (`<span class="indepth-num">`) is written out 5 times
  across `indepth_review.html` and `indepth_review_commentary.html`, and the
  "label for a judgement area" string (`"<Standard> <order>"`) is
  independently formatted three ways: in `views.py` (`labels = {...
  f"{s.get_key_display()} {ja.order}"}`) and twice in templates
  (`block.label`/`row.ja.order` and, separately for the withdrawn section,
  `r.judgement_area.standard.get_key_display`/`r.judgement_area.order`).
  `InDepthJudgementArea` has no `label` property to unify this. Flagged as
  the place to add one if statement labelling changes again.
- `spelling.py::spelling_warning` rebuilds a `{w.casefold() for w in words}`
  set from scratch on every word checked (quadratic, though n is tiny in
  practice — only commentary + next_steps per label). Low severity, purely a
  tidy.
- A statement withdrawn while it holds only a RAG rating (no commentary/next
  steps) becomes a permanently invisible orphan `InDepthResponse` row: kept
  by `_indepth_sync` (its retention test is `responses.exists()`, not "has
  text"), but excluded from the ratings page (inactive) and from the
  withdrawn section (which only shows rows with `evidence_text or
  next_steps`). Not data loss — no write-up existed to lose — but same shape
  as the 16 Sept 2026 hidden-text incident (see the developer's own note
  under "Before you believe a reported loss, count the cargo" in CLAUDE.md).
  Worth a second look if a future census/audit reports response counts.
- The label-building + spelling-warning assembly (~15 lines) is inlined into
  the POST branch of `indepth_review`, already a 400+ line view. Recommended
  extracting to `spelling.py` or a small helper, paired with the `label`
  property fix above so there's one source of truth.
- Query hygiene was fine: the new `select_related("judgement_area__standard")`
  on the `existing` queryset correctly covers the withdrawn-list sort key
  (`r.judgement_area.standard.order`), no query-in-loop introduced.
  `f.cleaned_data.get("judgement_area_id")` is safe post-`is_valid()` since
  the field is a required `IntegerField`.
- New files (`review/spelling.py`, `review/data/en_GB_words.txt`,
  `review/data/spelling_allow.txt`, migration `0038`) were untracked (`??`)
  in git status at review time — flagged as a one-line deploy-readiness
  note, not a code finding: if not `git add`ed, the feature 500s on first
  commentary save in production (`FileNotFoundError` on `_dictionary()`).
