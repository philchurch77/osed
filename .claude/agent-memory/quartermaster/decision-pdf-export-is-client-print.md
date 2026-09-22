---
name: decision-pdf-export-is-client-print
description: PDF export of Evaluation / In-depth pages planned as window.print() + @media print, not server-side PDF; textarea mirror rules
metadata:
  type: project
---

Planned 2026-09-22: "Export PDF" = browser print (window.print), no new route, no WeasyPrint.

**Why:** WeasyPrint needs pango/cairo system libs on Azure App Service Linux (startup.sh apt churn); a new route would need @governor_denied/scoping + GovernorUrlCoverageTests; single gunicorn worker; print shows exactly what is on screen incl. unsaved edits.

**How to apply:**
- Shared partial review/includes/export_pdf.html (button hidden until JS unhides it; data-print-title built from school + page + selected_year_value + term/area).
- New static review/print_export.js loaded globally from base.html; on beforeprint mirrors each textarea's .value into a sibling div.print-mirror (textContent), hides the textarea in print, removes mirrors on afterprint. NEVER writes .value/.checked (static test guards it).
- "Unsaved" print banner computed from value vs defaultValue / checked vs defaultChecked, not from unsaved_changes.js (that binds only the first POST form — wrong form on evaluation.html).
- word_limit.js init-time trim makes value != defaultValue for over-limit stored text; banner will show — honest, and a pointer to that separate fix.
- Governors keep the button on Evaluation (read-only, exposes nothing they cannot already see).
- Rejected: CSS field-sizing:content (no Firefox; textarea does not fragment across pages); server-rendered print-only copy of stored text (would not show unsaved edits, doubles every text in the HTML).
