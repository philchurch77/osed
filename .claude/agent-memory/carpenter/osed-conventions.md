---
name: osed-conventions
description: OSED (Django trust self-evaluation tool) — JS house style, script loading pattern, and the test-claim discipline the project runs on
metadata:
  type: project
---

**JS style**: all `review/static/review/*.js` files are ES5 IIFEs — `var`, no
`const`/`let`, `(function () { ... })()`. New JS should match this, not modern
syntax. Reference files: `unsaved_changes.js`, `word_limit.js`, `mobile_nav.js`.

**Global script loading is the norm, not a shortcut.** `word_limit.js`,
`unsaved_changes.js` and `print_export.js` (added Sept 2026, "Save as PDF"
feature) are all loaded unconditionally from `review/base.html`, each guarding
itself with a cheap no-op (missing element → return) rather than being scoped
per-page via `{% block scripts %}`. Do not flag this as a finding on its own —
it's the established pattern here.

**Test-claim discipline (article 11) is taken seriously in this repo** — see
CLAUDE.md's own examples: `GovernorUrlCoverageTests`, `TemplateCommentTests`,
mutation-checked `LoginDoorsTests`. A code comment that says "TestClassName
guards this" or "X greps for this" is a claim, not decoration — always grep
`review/tests.py` for the named class/behaviour before accepting the comment
at face value. Found one gap Sept 2026: `print_export.js`'s docstring claimed
a `PrintExportTests` class enforces its read-only-field guarantee; no such
test existed. Filed as High, not Medium, specifically because the false
claim undermines the project's own guardrail pattern for the next reader.

**Known pre-existing JS interaction to watch for**: `word_limit.js` trims an
over-limit textarea's `.value` on page load (documented in CLAUDE.md's "Known
discrepancies"), which can make any other script that diffs
`.value`/`.defaultValue` to detect "unsaved changes" report a false positive
on page load. `print_export.js`'s own `hasUnsavedChanges()` does exactly this
diff independently of `unsaved_changes.js`'s existing `isDirty` tracking —
flagged as Medium duplication, not fixed (reviewer role, no edits made).
