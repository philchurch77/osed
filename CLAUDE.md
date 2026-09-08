# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**OSED** is a Django 6 self-evaluation tool for a multi-academy trust. Schools record
termly **dashboard ratings** and structured **in-depth reviews** across judgement areas;
trust leaders and trustees view aggregated results. Access is via **Microsoft SSO**, with
authorization handled in-app and scoped per school.

Two further tabs were added in Aug 2026 from the Oxlip TFORS/risk proposal (v7):

- **Risk** — a per-school risk register scored on the Trust's Impact × Likelihood matrix,
  routed to TFORS or SIV by category, QA'd by the CFO, rolled up to the Trust Dashboard as
  a **Red-only** exception report. Live, not behind a flag.
- **Operations & Resources** — five domains of benchmarked termly RAG metrics, shipped as a
  **pilot**: every metric is individually switchable per school and per academic year, and
  defaults to **off**.

Single Django app: `review`. Project package: `osed`.

## Running locally (Windows)

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Local dev uses **SQLite** (`db.sqlite3`) and `DEBUG=1` via a gitignored `.env`
  (copy from `.env.example`). Production uses **Postgres** via `DATABASE_URL`.
- Run tests: `python manage.py test review` (**117 tests** in `review/tests.py`; the suite
  takes ~45s because some tests load the in-depth criteria).
- Pre-deploy security check: `python manage.py check --deploy` with `DEBUG=0`.

> Running with `DEBUG=0` locally needs `DATABASE_URL`, and `settings.py` adds `sslmode`,
> which SQLite rejects. To exercise production settings locally, point
> `DJANGO_SETTINGS_MODULE` at a throwaway module that imports `osed.settings` and
> overrides `DATABASES`, `SECURE_SSL_REDIRECT` and the two `*_COOKIE_SECURE` flags.

## Architecture & key files

- **`osed/settings.py`** — all config is env-driven. `DEBUG` defaults to **False**;
  production raises `ImproperlyConfigured` if `SECRET_KEY` or `DATABASE_URL` is missing.
  `ALLOWED_HOSTS` is derived from the `ALLOWED_HOSTS` env var plus Azure's
  `WEBSITE_HOSTNAME`, and `CSRF_TRUSTED_ORIGINS` is derived from `ALLOWED_HOSTS` — so a
  custom domain is added in one place. Production HTTPS hardening (HSTS, secure cookies,
  SSL redirect) is gated behind `if not DEBUG`.
- **`review/views.py`** — function-based views (dashboard, overview, board, evaluation,
  in-depth review, reflection, **risk_register, risk_qa, operations**). The in-depth grade
  is derived from a RAG "ladder" by `conclude_indepth_grade`.
- **`review/models.py`** — `School`, `Category`, `SchoolProfile`, `ReviewPeriod`,
  `Evaluation`, the in-depth models (`InDepthArea` → `InDepthStandard` →
  `InDepthJudgementArea`; `InDepthReview` → `InDepthResponse`), and the risk/operations
  models below. No pupil-level PII — only staff emails and school-level text.
- **`review/risk.py`** — the Impact × Likelihood matrix and RAG derivation, in **one
  place**. `rag_for(impact, likelihood)`, `band_for`, `trend_for`, `is_escalated`.
- **`review/operations.py`** — Operations RAG evaluation: the four-state enum (Blue is
  first-class), the per-rule evaluation functions, the statutory/complaints/grant
  computations, and the two verbatim standing texts.
- **`review/permissions.py`** — `user_can_edit(user)` (superusers + `EDIT_PERMS`) and
  `user_can_qa_risk(user)` (superusers + the `review.qa_risk` permission).
- **`review/allauth_adapters.py`** — `RestrictMicrosoftLoginAdapter`: SSO only admits
  pre-provisioned users (existing active `User` + `SchoolProfile`).
- **`review/admin.py`** — multi-tenant admin; includes a CSV user-import view
  (`import-users/`, superuser only) and the **pilot visibility grid**
  (`/admin/review/operationsmetricvisibility/grid/`).
- **`review/admin_site.py`** — `OsedAdminSite.get_app_list` splits the one `review` app
  block on the admin index into named sections (Schools & settings / Dashboard evaluation /
  In-depth review / Risk register / Operations & Resources). It is wired in by listing
  **`review.admin_site.OsedAdminConfig` in place of `django.contrib.admin`** in
  `INSTALLED_APPS` — no proxy models, no migrations. Add a new admin-registered model to
  `ADMIN_SECTIONS` or it falls into the "Review — other" catch-all;
  `AdminIndexGroupingTests` fails if grouping ever drops or duplicates a model.

## Risk tab

- **`TrustCategory`** is the shared 14-value list: the nine OSED evaluation areas (routing
  to **SIV**) plus the five Operations & Resources domains (routing to **TFORS**).
- **`Risk`** is a **long-lived record**, not a termly form entry. It stays open across terms
  until actively closed with a reason. `status`, `closed_at`/`closed_by`/`close_reason`,
  and `close_qa_by`/`close_qa_at` form the audit trail the Committee needs.
  **Closed risks stay on the register, greyed out — never deleted or filtered away.**
- **`RiskRating`** holds one rating per `(risk, period)`. The full history is kept; that is
  what makes worsening / persisting / improving computable rather than judged.
- **`RiskSettings`** is a singleton (pk=1, same pattern as `Branding`) carrying the
  escalation threshold. The agreed rule is **Red only**; `escalate_persisting_amber` widens
  it. It is a setting, not code, because the client expects to revisit it.
- The term view opens on **"your open risks, review each one"** with an add form below —
  never a blank form.

## Operations & Resources tab (pilot)

- **`OperationsMetric`** + **`OperationsMetricBand`** are the catalogue. Metrics are
  **records, not hard-coded fields**, and bands are **phase-aware from the start**.
- Each metric names one `rule` from `review/operations.py`; the band supplies its numbers.
- **`OperationsMetricVisibility`** is the pilot switch, per `(school, year, metric)`,
  **default off** (no row at all means hidden).
- **`OperationsEntry`** carries the value/band choice, commentary, and a `source` field
  (`manual`/`import`) so an IMP/FBIT feed later is a **new writer, not a rewrite**.
- Supporting records: `StatutoryComplianceItem` (five dated items), `GrantPublication`,
  `ComplaintTheme` (admin-editable), `OperationsNote` ("Anything else to raise").

### Rules that must not be softened

- **Hidden means absent.** No tile, no grey placeholder, no contribution to a domain header
  count, and **no domain card at all** if every metric under it is hidden. An empty "IT"
  card reads as a failure, not as "not in the pilot".
- **Hidden is never green.** Hidden metrics are filtered out *before* any summary runs, so
  they are out of the roll-up denominator. A school piloting two domains must not look
  healthier than one running five.
- **Roll-ups show scope** ("3 of 12 metrics — pilot").
- **Blue means "not yet benchmarked" and is never Green.** It is a real state in the enum,
  not a null rendered grey. Primary ICFP has **no band on purpose** — the ISBL data is a
  paid product the Trust does not hold, so Primary staff costs stay Blue indefinitely. That
  is the expected state; a Blue tile must look deliberate and explain itself.
- **The bands are the control, and there are always four of them.** On a judgement-based
  metric (`rule = band_choice`) the three band statements *are* the radio buttons — the
  descriptor is the label, never a colour word in a dropdown, and never printed twice.
  Everywhere else the colour is **derived** and the same four bands render as a read-only
  strip with the one in force marked `.is-current`. Do not make a derived tile clickable:
  that would let a school enter 9% sickness and click Green over it.
- **"Not yet rated" is the fourth band on every tile** — a selectable button where the
  Principal chooses, a muted card where the colour is derived. It keeps Blue clearable
  rather than a value you can set once and never undo. The single exception is Primary
  ICFP staff costs, which has no band records at all; its blue note carries the
  explanation instead.
- **There is no ownership field.** `Principal-owned`/`Trust-owned` was dropped by the
  client; the mockup's `TRUST`/`SCHOOL` badges are gone. Do not reintroduce them.
- Both standing texts (the legend line and the small-print footer) appear **verbatim** —
  they live in `operations.py` as `LEGEND_STANDING_TEXT` and `SMALL_PRINT`.

## Security model (do not weaken)

- **Authentication** = Microsoft SSO. The login page offers only the Microsoft button.
  `ACCOUNT_ADAPTER` (`OsedAccountAdapter`) closes `/accounts/signup/` and applies the
  provisioning rule to password logins too; **allauth has no `ACCOUNT_ALLOW_SIGNUPS`
  setting** — that name was in `settings.py` for months and did nothing. Both adapters
  call the one `provisioning_problem()` rule. Imported users get unusable passwords
  (SSO-only). Break-glass is any superuser with a usable password, via either
  `/accounts/login/` (POST still accepted; rate-limited) or `/admin/login/` (not).
- **Authorization** = per-school scoping. Non-superusers are restricted to their
  `SchoolProfile` schools in **both** views (`_resolve_school_selection`,
  `_get_allowed_schools`) and admin (`_request_schools`). Any new view that reads or
  writes school data **must** go through these helpers — never trust a `school` id from
  the request without checking it against the user's allowed set.
- Superusers bypass school scoping by design.
- **`Risk QA`** is a Django group holding the single `review.qa_risk` permission. It grants
  the cross-school "awaiting QA" view — but **not** a scoping bypass: that view still
  filters through `_get_allowed_schools`, so a CFO account must be provisioned with every
  school it reviews, or its queue is silently partial.
- Nav gating: the **Risk** and **Operations & Resources** tabs are visible to every
  authenticated user (read-only users included — the spec wants the full register visible
  at School Dashboard level). Only **Risk QA** is gated, on `user_can_qa_risk`.
- No Committee or Trust Board roles exist, deliberately. Those audiences have **no OSED
  logins** and see exported screenshots. Do not build click-through or external-audience
  login paths — that work is cancelled, not deferred.

## Conventions

- Views are **function-based**, not class-based. Match that style.
- **Indentation is per file — match the file you are editing.** `views.py`, `admin.py` and
  `tests.py` use **tabs**; `models.py`, `forms.py`, `permissions.py`, `risk.py`,
  `operations.py`, `urls.py` and `context_processors.py` use **4 spaces**.
- Prefer editing existing helpers over adding parallel ones; reuse
  `_academic_year_context`, `_resolve_school_selection`, `_readonly_redirect`, and the
  `review/templates/review/includes/filter_*.html` selector partials.
- Academic year is stored as a start year (e.g. `2026`) but displayed as `2026-2027`;
  `MIN_ACADEMIC_YEAR_START = 2026`.
- **Terms**: `ReviewPeriod.round` still stores `1`/`2`/`3`, but is labelled **Autumn /
  Spring / Summer** everywhere. Use `TERM_LABELS` / `ReviewPeriod.term_label` for display —
  never print "Round N".
- **`{# ... #}` is single-line only.** Django does not close a hash comment on a later
  line — the whole block is emitted as page text, and it has leaked onto the Trust
  Dashboard, which goes into board packs as a screenshot. Use `{% comment %}` for anything
  longer. `TemplateCommentTests` fails the build on an unbalanced line.
- Templates carry meaningful **non-ASCII** (the dashboard trend legend `▲ ▼ —`, em-dashes
  throughout). Edit them as UTF-8; a PowerShell `Get-Content`/`Set-Content` round-trip
  reads them as cp1252 and adds a BOM, corrupting the lot invisibly.

### Three separate colour scales — do not cross them

| Tokens | Meaning | Chip style |
|---|---|---|
| `--rag-*` | the **1–5 evaluation scale** (`--rag-blue` is grade 1, Exceptional) | `.rag-pill`, rounded |
| `--risk-*` | risk register bands (four: red/amber/yellow/green) | `.risk-chip`, square, uppercase |
| `--ops-*` | Operations RAG (`--ops-blue` = *not yet benchmarked*) | `.ops-chip`, rounded pill |

The `--ops-*` tokens also drive the band controls: `.ops-bandpick-*` (the four radio
buttons) and `.ops-band*` (the read-only strip). Both take their colour from a per-option
`--band` / `--band-wash` pair, so a band is restyled in one place.

A risk amber must never read as a quality judgement, and Operations blue must never borrow
`--rag-blue`. Every RAG chip also carries its band as **text**, because the Trust Dashboard
goes into board packs as a greyscale screenshot.

### Two things named "Category" — do not confuse them

- **`Category`** — the 8 dashboard evaluation categories (`seed_categories`). Pre-existing.
- **`TrustCategory`** — the 14-value risk/operations list (`seed_trust_categories`). Its
  nine evaluation-area rows are a `OneToOneField` to **`InDepthArea`** with `name` as a
  property, so renaming an area flows through instead of forking the list. Never store
  those names as free strings.

> `Category` and `InDepthArea` names have pre-existing drift ("Personal Development and
> Well-being" vs "…Wellbeing"; "Early Years / P16" vs separate "Early Years" and
> "Post-16"). `TrustCategory` keys off `InDepthArea`. Leave the drift alone unless asked.

## Data / seeding management commands (idempotent)

Run at deploy time on **Azure** by `startup.sh` (the live path), in this order: `migrate`,
`ensure_schema`, `seed_categories`, `load_indepth_blueprint`, `load_indepth_criteria`,
**`seed_trust_categories`**, **`seed_operations_metrics`**, `import_indepth_workbooks`,
`seed_schools`, `seed_branding`, `collectstatic`, `copy_demo_media_to_static`.

One-off (**not** in `startup.sh`): `ensure_osed_staff_group` (the **OSED Staff** editor
group) and `ensure_risk_qa_group` (the **Risk QA** group).

In-depth criteria source data lives in `review/data/` — the per-area supporting-tool
workbooks (e.g. `Updated P16 2026.xlsx`) drop into `review/data/workbooks/` and are picked
up by `import_indepth_workbooks`.

> Ordering matters: `load_indepth_criteria` (from `criteria.json`) runs **before**
> `import_indepth_workbooks`, so where an area has a workbook, the workbook wins. An
> area with no workbook keeps its `criteria.json` text.

> `seed_trust_categories` must run **after** `load_indepth_criteria` (it matches the nine
> areas by name against `InDepthArea`, and warns rather than inventing them if they are
> missing). `seed_operations_metrics` must run **after** `seed_trust_categories`, since its
> metrics hang off the five domain rows.

> `seed_operations_metrics` never switches anything on. It also **deletes bands not in the
> seed** — that is deliberate, and is how Primary staff costs stays Blue.

> The importer takes the area name from **A1** of the first standard sheet (falling back
> to A2 of `Expected Standard`/`Strong Standard`). A workbook that arrives with a blank
> A1 on its first sheet will fail with "Could not determine area name" — fix the cell in
> the workbook rather than the importer.

> `ensure_schema` and migrations `0023`/`0024` are deliberate `IF NOT EXISTS` repair
> shims for a production Postgres DB on which migration `0020` was only partially
> applied. Keep them. (Note: `startup.sh` currently runs `ensure_schema` **after**
> `migrate`, not before — see "Known discrepancies" below.)

## Deployment

**Azure App Service is the only deployment target.** There is no second environment.

- See **`AZURE_DEPLOYMENT.md`** (the single source of truth) — startup command
  `bash startup.sh`, Postgres Flexible Server, and required App Settings.
- `startup.sh` is the live deploy path: it runs migrations, the seed/import commands and
  `collectstatic`, then launches gunicorn. Anything that must reach production has to be
  wired into that script.
- Production uses `CompressedManifestStaticFilesStorage`, so **a static file that was never
  collected hard-fails the page** rather than degrading. After adding any static asset,
  run `collectstatic` with `DEBUG=0` and confirm it appears in `staticfiles/staticfiles.json`.
- Media: local disk in dev; production uses `MEDIA_AS_STATIC=1` (demo assets via
  WhiteNoise) or Azure Blob (`USE_AZURE_MEDIA_STORAGE=1`).

## Open with the client (do not silently resolve)

1. **Risk Management Framework (Final, Sept 2025)** — requested, never supplied. The matrix
   is built from the proposal; if the framework disagrees it is a one-line change to
   `BAND_MATRIX` in `review/risk.py`. The mockup's own register rows contradict the
   mockup's matrix in four of six cases — **the matrix is the specification**.
2. **Which schools and which sections are in the Operations pilot** — a config decision,
   made in the admin visibility grid, not in code.
3. **"A marked step-change" in complaints is undefined** in the source document. The
   working threshold is `+3` in a term, held on the band record (`step_change`) so it can
   be corrected without a deploy.
4. **Staff turnover comparators (12% secondary / 11% primary) are placeholders.** The Trust
   does not hold the census figures. They render with their year so a stale figure is
   visible, but they are not real yet.
5. **Hard-benchmarked vs judgement-based** is a best guess for the metrics the document
   does not classify. It is a label, not logic.
6. **`School.is_mainstream` defaults to `True`.** Any non-mainstream school must be set in
   the admin, or the Inclusive Mainstream Fund will wrongly appear on its grant checklist.
7. **The Power BI embed** (planned, not built) — see `POWERBI_EMBED_PLAN.md` §2 for the
   eight questions the client must answer before it can be costed. The two that block
   everything: whether the report holds pupil-level or aggregate data, and whether the
   dataset exists at all.

## Proposed: Power BI embed (planned, NOT built)

Full plan in **`POWERBI_EMBED_PLAN.md`**. Read it before starting any work on this — the
detail is there, not here. The four things worth knowing without opening it:

- **Nothing is approved and no code exists.** The Django side is ~2–3 days; the feature is
  weeks, and most of it is Azure tenant and semantic-model work outside this repo.
- **`School` has no stable external key** — `name` is not even `unique=True`, and the pk
  is meaningless outside this database. A DfE URN has to be added before any filtering can
  be trusted, and a blank URN must **fail closed** (no token, no report), never fall back
  to an unfiltered view.
- **`_resolve_school_selection` fails closed but silently** (`views.py:194-197`): a forged
  `?school=` id is discarded and the user's own school substituted. Right for rendering a
  page, wrong for minting an access token — that path needs a 403. Wrap the helper, do not
  change it.
- **`is_superuser` must not become the trust-wide BI identity.** It would silently re-grade
  every existing superuser from "sees all self-evaluations" to "sees every pupil in the
  Trust". Use a separate permission shaped like `Risk QA`.

If the embedded report would duplicate the Trust Dashboard, do not build it — that summary
is generated from tile data specifically so it cannot drift, and it goes into board packs.

## Known discrepancies (pre-existing, unresolved)

- `startup.sh` runs `ensure_schema` **after** `migrate` (lines 27 and 30), while this file
  previously stated it must run before. Both have been left as they are — confirm the
  intended order before changing either.
- `startup.sh` starts gunicorn with **no `--workers` flag** (line 55), so production runs a
  single worker, while the file's own comment says to add `--workers=3` on Postgres — which
  production uses. Harmless today (no view makes a blocking outbound call), but any feature
  that does, such as the Power BI embed, would stall the whole site on that one worker.

## Design decisions worth knowing before changing them

- The **Operations baseline is derived** from the year's Autumn entry rather than stored
  separately, so it cannot drift from the data it summarises.
- The Trust Dashboard **executive summary is generated** from the tile data, not authored,
  for the same reason.
- `OperationsEntry.manual_red_reason` exists because some red triggers in the source bands
  ("a core-subject vacancy unfilled a full term") cannot be computed from one figure.
  Setting a reason forces Red.
- Computed RAGs return **Blue when their source data is incomplete** (fewer than five
  statutory dates, no grant records, no prior complaints term) rather than guessing.
- `Risk.review_point` is free text, not an FK to `ReviewPeriod`: the register works in
  half-terms ("Aut 2", "Spring 1"), which `ReviewPeriod` cannot express.

## Guardrails

- Never commit `.env` or `db.sqlite3` (both gitignored; keep it that way).
- Don't set `DEBUG=1` in any production config.
- Commit/push only when asked.
