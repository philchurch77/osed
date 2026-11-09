---
name: word-limit-js-map
description: Which textareas word_limit.js caps, which have server-side word validation, and the in-depth invalid-save re-render gap
metadata:
  type: project
---

word_limit.js (every page) caps every editable textarea at 300 words unless data-max-words is set. Server-side _validate_max_words exists only on forms.py fields: Evaluation judgement_evidence/to_progress (300), InDepth commentary/next_steps (150), Risk mitigation/close_reason (150).
JS-only (no server check): in-depth needs_attention_comment, reflection textareas, operations metric commentary, operations anything_else.
JS and server both count /\S+/ on stripped text — consistent (NBSP treated as space by both).

From 2026-11-09 the init-time trim is gone and over-limit-on-load fields are never trimmed. Remaining JS loss path: an under-limit field still silently cuts its *tail* on input/paste (stored words after the cursor).
In-depth commentary invalid formset re-renders na_comment from the DB, not the POST (views.py ~1508/1627) — typed Needs Attention comment lost on a validation failure.

**Why:** these decide whether a limit change is a loss or a behaviour change.
**How to apply:** check this map before judging any word-limit or textarea change.
