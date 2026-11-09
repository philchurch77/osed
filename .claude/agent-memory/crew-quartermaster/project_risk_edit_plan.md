---
name: project-risk-edit-plan
description: Nov 2026 plan for letting Principals edit open risks on the register; options chosen/rejected and client decisions pending
metadata:
  type: project
---

Client asked (Nov 2026) for Principals to edit risks they had logged. Not a permissions change: OSED Staff already holds add_risk/change_risk; the register simply had no edit path for title/category/mitigation/owner/review_point.

Recommended (pending client answers): edit any OPEN risk on the school (not only created_by); details fields only; impact/likelihood stay on the termly rating row (one way to set a rating); closed risks not editable; text edits keep QA, a category change clears the current term's rating QA (routing TFORS/SIV flips).

Rejected: reusing RiskEntryForm as-is (impact/likelihood required); edit forms nested in the save_ratings table form (invalid HTML); one edit form per risk in a details block (page bloat). Chosen UI: per-row "Edit details" link with ?edit=<id>, one scoped form rendered.

Found while planning: close_risk lookup has no status=OPEN filter, so a hand-posted id re-closes a closed risk and wipes its CFO close sign-off. Folded into the same passage.

**Why:** next risk-register plan should not re-open these.
**How to apply:** if the client's answers differ, adjust the scope filter and QA rule only; the UI shape stands. See [[risk-register-patterns]].
