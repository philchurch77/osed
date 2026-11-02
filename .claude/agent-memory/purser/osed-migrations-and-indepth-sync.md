---
name: osed-migrations-read
description: OSED migrations audited, in-depth statement sync (criteria.json vs workbooks) churn, withdrawn statements, cascades into InDepthResponse
metadata:
  type: project
---

Audited 2026-09-29 (Safeguarding Met 8 withdrawal change).

- 0038_indepthjudgementarea_is_active: AddField BooleanField default=True. Additive; SQLite rebuilds the table (copies every column), Postgres adds column. Loses nothing.
- Loader order in startup.sh: load_indepth_criteria, then import_indepth_workbooks; each `|| echo continuing`, each its own transaction. criteria.json and the workbooks DISAGREE on wording in most areas (e.g. Safeguarding Met 6 of 7 differ, trailing full stops etc.), so every deploy the criteria pass deletes unanswered workbook statements and the workbook pass recreates them at new pks (pk churn visible locally: 1922-1935 vs 1841/1849). Since is_active, a failed workbook pass leaves answered workbook statements WITHDRAWN.
- Withdrawn (is_active=False) = leftover with any response. View skips ids outside ja_ids silently on POST (both pages) with a success message.
- Cascades (pre-existing, no retention rule stated yet): School->InDepthReview CASCADE, InDepthReview->InDepthResponse CASCADE, InDepthJudgementArea->InDepthResponse CASCADE, InDepthStandard->JA CASCADE, InDepthArea->Review CASCADE. Guarded only by ProtectsWrittenWorkMixin (admin, delete_selected removed) and _indepth_sync's responses.exists() check. load_indepth_criteria --clear still deletes all standards (cascade) - not in startup.sh.
- Census technique that works: `python manage.py shell -c "$(cat <<'EOF' ... EOF)"` (no file), use .values() so it runs before 0038 is applied; SET TRANSACTION READ ONLY on Postgres.
- Hook blocks the Purser writing anywhere but this directory, even when the caller asks for a script file: put the script in the report.

**Why:** next audit of any in-depth loader/migration change starts from here.
**How to apply:** re-run the criteria-vs-workbook identity comparison before trusting "no churn"; see [[osed-client-js-and-free-text]].
