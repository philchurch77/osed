---
name: print-pdf-repro-harness
description: How to reproduce OSED "Save as PDF" (window.print) output with Edge; what headless does and does not cover; the kiosk-printing hazard
metadata:
  type: project
---

Learned 2026-09-29 (Evaluation PDF "last box cut off" report; NOT reproduced).

- Render a real page: manage.py shell -c "exec(open(script).read())" (piping a script to
  `shell <` breaks on indented blocks). Test Client needs HTTP_HOST="localhost" or it 400s.
  Wrap in transaction.atomic() + raise; verify rollback afterwards.
- Edge 154 at C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe. Node 24 has global
  WebSocket, so CDP needs no packages: --headless=new --remote-debugging-port, Page.printToPDF.
- Headless Page.printToPDF DOES fire beforeprint (print_export.js mirrors present, 16/16) and
  afterprint. So headless exercises print_export.js + @media print faithfully. It does NOT
  exercise the interactive print-preview dialog (settings change, destination switch).
- NEVER use --kiosk-printing on this machine: the default Windows printer is a physical
  Brother MFC; the sticky "Save as PDF" appState in Preferences was not honoured, no PDF
  appeared, and the job's fate could not be determined (PrintService log disabled).
- On Windows, child.kill() on msedge only kills the launcher; kill by CommandLine match on the
  scratch dir or the profile dir stays locked.
- Chromium PDFs with a web font embed several 1-byte subset fonts; text extraction must decode
  per font via each page's Tf + that font's ToUnicode codespace width. Always control-check a
  marker known to be present before trusting "not found".
- Evaluation print geometry: A4 at 15mm margins is ~680 CSS px, so (max-width: 767px) screen
  rules apply in print. No JS sizes textareas (grep style.height/scrollHeight: none).
- Result of 58 headless geometries (last-row length, row-8 start offset, scale .6-1.1,
  Letter, margins 0/1in, header/footer, Inter loaded, multi-paragraph pre-wrap text):
  last row complete every time. Layout/fragmentation in Edge 154 did not cut the final row.

**Why:** the next print report can start from a working harness and skip the dead ends.
**How to apply:** first ask for the client's PDF itself (Producer/Creator metadata = engine and
version, MediaBox = paper, page count) and the preview's page counter; rebuild the harness in
the scratchpad; delete it after.

## Round 2 (2026-09-29, client on Edge 153.0.4234.32: preview said 14 pages, saved 13, 90% scale fine)

- Edge version shape: Edge = 15x.0.42xx; Chrome = 15x.0.7xxx-80xx. Portable Blink of the same
  milestone: Chrome for Testing zip (storage.googleapis.com/chrome-for-testing-public/<ver>/win64/
  chrome-win64.zip; list at googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json).
- SAFE read-only print-preview probe (no printer reached; nothing in the dialog is clicked):
  seed <profile>/Default/Preferences printing.print_preview_sticky_settings.appState =
  {"version":2,"recentDestinations":[{"id":"Save as PDF","origin":"local","account":""}],
  "selectedDestinationId":"Save as PDF"} - honoured by Chrome 153 AND Edge 154 when not kiosk.
  Click the export button via setTimeout (window.print blocks). Preview is target chrome://print
  (Edge: edge://print). Chrome state: print-preview-app .destination_.id / .documentSettings_.pageCount.
  Edge: read shadow-DOM text ("Total: N pages", destination). The PDF viewer is an iframe
  target at chrome-untrusted://print/<uiId>/0/print.pdf; attach to it and
  fetch(location.href.replace('/0/','/-1/')) = COMPLETE document (what Save as PDF writes);
  /<i>/ = per-page drafts. Close with Target.closeTarget (= Cancel).
- Observed: beforeprint fires once when the dialog opens; afterprint only when it closes
  (Chrome 153 and Edge 154). Mirrors live for the whole dialog.
- No repro: preview counter == complete doc, all text present (C153 x9 geometries, Edge154 x1);
  headless 524 one-word-step geometries x 2 engines, plain + paragraph text: all complete.
- Side finding: forced horizontal overflow (a 1000px element) -> shrink-to-fit, and C153 headless
  dropped ALL text from one middle page (content stream had borders, 0 Tf). Not the client's shape.
- Fallback font (no Inter) paginates ~1 page shorter than Inter at 13-14 pages.
- What would settle it: the client's PDF (/Producer; does page 13's stream draw text below the
  MediaBox?), her 16 box word counts, her headers/footers + background-graphics settings.
- Cleanup: rm needs a literal path or "${SP:?}" - a bare "$SP"/* is refused by the safety check.
