---
name: decision-indepth-statement-retire-number-spell
description: In-depth statements - number from stored `order` per standard; retire via is_active flag set by _indepth_sync, never delete; spelling = server-side en_GB wordlist warning after save (planned 2026-09-29)
metadata:
  type: project
---

Planned 2026-09-29 (client asked: number statements, drop Safeguarding Met #8, spelling prompt).

**Numbering:** render `ja.order` (per standard), never forloop.counter — commentary page filters by rung and adds kept_for_text blocks, so positions lie. `_indepth_sync.sync_judgement_areas` rewrites order = source index+1 every deploy, so numbers track the workbook row order. Only two templates render statements: indepth_review.html, indepth_review_commentary.html (+ na_bullets list).

**Retiring a statement:** removing it from source alone is NOT enough — sync keeps any leftover with `responses.exists()` (even rag-only) and it keeps rendering AND counting in conclude_indepth_grade. Plan: additive `InDepthJudgementArea.is_active` (0038), sync sets False on kept leftovers / True on matched; views filter is_active for rungs; retired-with-text shown read-only on commentary page. Must remove from BOTH criteria.json and the workbook (load_indepth_criteria runs first, workbook wins). Rich-sheet rows: delete the statement row AND its continuation rows, or they attach to the previous statement.

**Why:** InDepthResponse.judgement_area is CASCADE; a data-migration delete would destroy written work.

**Spelling:** browser red-line state not exposed to JS. Recommended server-side check against a vendored en_GB word list (no package), warn after save via messages, never block. Client-side Typo.js was the alternative (untestable in Django suite; submit interception collides with unsaved_changes.js isSubmitting).
