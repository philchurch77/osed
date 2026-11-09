---
name: risk-register-text-and-audit
description: Risk/RiskRating free-text fields, sizes, history coverage, cascades, and the audit gaps found in the Nov 2026 edit_risk review
metadata:
  type: project
---

Risk (models.py ~637): title Char255, owner Char100, review_point Char30, mitigation Text, close_reason Text; sizes unchanged since migration 0030 (create). Has simple_history (updated_at excluded, auto_now) so the stale guard works.
RiskRating: note Text; qa_by/qa_at; **no simple_history** — any qa clear (rating change, category change via .update()) destroys who signed off, unrecoverably.

Cascades seen: Risk.school CASCADE; RiskRating.risk CASCADE, RiskRating.period CASCADE. No retention rule accepted by the developer yet.

Nov 2026 edit_risk review (2026-11-09): QA clear keyed on the *viewed* period, not the current term; edit refused via redirect when the risk is no longer OPEN (typed text discarded).

**Why:** these are the places a Risk's audit trail can thin out.
**How to apply:** on any later risk change, check whether those two were fixed and whether RiskRating gained history.
