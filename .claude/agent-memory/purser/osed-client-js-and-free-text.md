---
name: osed-client-js-and-free-text
description: OSED free-text fields and the client JS that touches them (word_limit, unsaved_changes, print_export) - what writes .value and what only reads
metadata:
  type: project
---

Audited 2026-09-22 (Save as PDF feature, no migrations in that change).

- Only `word_limit.js` writes textarea `.value` (init-time `enforce` trims + collapses newlines; known discrepancy, still open). Every other review/*.js only reads fields.
- No JS in review/static or templates walks `nextSibling`/children around a textarea; word_limit keeps its counter by reference, so inserting siblings after a textarea is safe.
- `unsaved_changes.js` goes dirty only on input/change events inside the first POST form; DOM insertion and window.print() fire neither, and do not trigger beforeunload.
- `print_export.js` mirrors (div.print-mirror) sit inside the POST form during print only; a div is not a form control, so never submitted.
- Its "unsaved changes" note compares value vs defaultValue: false negative after a bound invalid re-render (defaultValue is the unsaved text), false positive where word_limit trimmed on load.
- Ratings page rungs carry `.is-hidden` (indepth_ladder.js); print inherits it, so a PDF omits ratings on hidden rungs - same "hidden shape" family as the 17 Sept incident.

Free-text surfaces: Evaluation judgement_evidence/to_progress; InDepthResponse commentary/next_steps; needs_attention_comment on commentary page.

**Why:** next audit of any JS touching these pages can start from what is known to write vs read.
**How to apply:** re-grep `\.value *=` and sibling-walking before trusting this; see [[osed-migrations-read]] when a migration audit happens.
