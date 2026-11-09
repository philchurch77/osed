---
name: risk-register-access-pattern
description: How risk_register enforces school scoping and edit rights; what was audited clean on 2026-11-09 (risk edit feature)
metadata:
  type: project
---

risk_register (review/views.py) resolves the school once via _resolve_school_selection
(GET `school` wins over POST `school_id`; non-superusers by list membership) before any
branch. Every write branch then looks the Risk up with `school=school` (+ `status=OPEN`
for edit, close, save_ratings). Writes gate on `can_edit` (user_can_edit; governor returns
False first); QA branches gate on `can_qa`. QA-only users pass the read-only POST guard but
cannot reach edit/add/close branches.

Audited clean 2026-11-09 (risk details edit, `?edit=` GET + `action=edit_risk` POST):
same error text for not-found / other-school / closed (no existence oracle); GET writes
nothing new; RiskDetailsForm has no school field; category is a ModelChoiceField over the
trust-wide TrustCategory list (shared, not school-owned); Risk has updated_at + history.
RiskEditTests: 11 tests, ran OK.

Open Low, pre-existing: `_back()` echoes raw POST `rag` into the redirect query string
unvalidated (the legit form posts the validated value). Re-checked on the way in, so
cosmetic only.

**Why:** future audits of the risk tab can start from this rather than re-deriving it.
**How to apply:** if a new risk branch appears, check it uses `school=school` in its
lookup and the right can_edit/can_qa gate; re-verify the line numbers, they move.
