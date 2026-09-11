# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**OSED** is a Django 6 self-evaluation tool for a multi-academy trust. Schools record
termly **dashboard ratings** and structured **in-depth reviews** across judgement areas;
trust leaders and trustees view aggregated results. Access is via **Microsoft SSO** (or an admin-issued password), with
authorization handled in-app and scoped per school.

Two further tabs were added in Aug 2026 from the Oxlip TFORS/risk proposal (v7):

- **Risk** — a per-school risk register scored on the Trust's Impact × Likelihood matrix,
  routed to TFORS or SIV by category, QA'd by the CFO, rolled up to the Trust Dashboard as
  a **Red-only** exception report. Live, not behind a flag.
- **Operations & Resources** — five domains of benchmarked termly RAG metrics, shipped as a
  **pilot**: every metric is individually switchable per school and per academic year, and
  defaults to **off**.

Single Django app: `review`. Project package: `osed`.

## How work happens in this repo

**Claude Code leads the work and is accountable for it** — read the code, make the change,
run the tests, report the real output. Claude may **call in its own subagents** to help:
the crew in `~/.claude/agents/` (quartermaster, carpenter, bosun, master-at-arms, gunner,
lookout, surgeon), the built-ins (Explore, Plan, general-purpose), and the user-level
commands such as `/captain` and `/wheels-up`. They assist; they do not take over — the
change, the verification and the report come back through Claude.

- **The older persona agents are retired.** The project's `.claude/agents/` (ada, juno,
  les, stella, tess, theo, vera, victor) and `.claude/commands/` were removed in Sept 2026.
  Do not recreate them and do not work from them.
- **The GitHub Copilot copies are gone too.** `.github/agents/*.agent.md` (arthur, les,
  quinn, stella, theo, victor) were deleted in the same pass. `.github/` now holds only
  `workflows/azure-deploy.yml`.
- **Never report a pass you have not seen.** If a subagent reports a result, it is Claude's
  job to have the real output — `python manage.py test review` — before calling anything
  done. Check the change against "Security model", "Rules that must not be softened" and
  "Conventions" below as part of the same pass.

## Running locally (Windows)

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Local dev uses **SQLite** (`db.sqlite3`) and `DEBUG=1` via a gitignored `.env`
  (copy from `.env.example`). Production uses **Postgres** via `DATABASE_URL`.
- Run tests: `python manage.py test review` (**232 tests** in `review/tests.py`; the suite
  takes ~85–130s because some tests load the in-depth criteria). Capture to a file and
  grep for `^Ran \|^OK\|^FAILED` — stdout/stderr interleave through a pipe and `tail`
  will show seed-command chatter instead of the verdict.
- The working copy lives inside **OneDrive**, which locks files under `.git` during sync.
  A commit may stop on "Deletion of directory '.git/objects/NN' failed. Should I try
  again?" — that is post-commit `gc`, the commit is already written; answer `y`.
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
- **`review/allauth_adapters.py`** — the login gate. `provisioning_problem(user)` is the
  **one** authorisation rule (active `User` + `SchoolProfile`; superusers exempt).
  `OsedAccountAdapter` (`ACCOUNT_ADAPTER`) applies it in `pre_login` — which every allauth
  login path goes through — and closes `/accounts/signup/`; `RestrictMicrosoftLoginAdapter`
  (`SOCIALACCOUNT_ADAPTER`) matches the Entra email to a user and applies the same rule.
  Guarded by `LoginDoorsTests` (21 tests; the rule was mutation-checked when it had 15:
  disable it and seven went red).
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

## Version history — the only way back

Six models carry `simple_history`: `Evaluation`, `InDepthReview`, `InDepthResponse`,
`OperationsEntry`, `OperationsNote` and `Risk`. `updated_at` is excluded, since `auto_now`
would make every row unique for nothing. Reached through the admin **History** tab, scoped
by `ScopedHistoryAdminMixin`; `HistoryRequestMiddleware` populates `history_user`, so you
can see *who* saved each version.

Three things about it that are not obvious and have already mattered:

- **History starts at migration `0034` (9 Sept 2026).** Anything overwritten before that
  deploy has no prior version and is **gone**. When assessing damage from any wrong-data
  incident, that date is the hard floor.
- **A row needs two versions to be recoverable.** simple-history records state *after* each
  save, so the clobbering save produces a row holding the clobbered text. A record saved
  only once since `0034` cannot be rolled back.
- **`prune_history` is not scheduled, and its own docstring says "NEVER add this to
  `startup.sh`"** — an unattended destructive command on every deploy is the shape of the
  original incident. It is absent from `startup.sh` and `azure-deploy.yml`; schedule it
  externally if at all, and keep the dry run as the default. Note also that
  `RETENTION_DAYS = 90` is measured from each row's own `history_date` — from when the good
  text was *written*, not when it was destroyed — so switching it on mid-incident deletes
  the pre-clobber versions you are trying to read.

## Security model (do not weaken)

- **Authentication** = Microsoft SSO **or** email + password. The login page offers the
  Microsoft button and, below it, an email/password form. The form was removed on
  8 Sept 2026 and **reinstated on 11 Sept at the client's request**: some staff cannot use
  the Microsoft button (a live ticket — a Cedars Park user whose Entra `mail`/UPN did not
  match her OSED email had been working on an admin-set password, and was locked out the
  day the form went). Do not remove it again without the client.
  `ACCOUNT_ADAPTER` (`OsedAccountAdapter`) closes `/accounts/signup/` and applies the
  provisioning rule to password logins too; **allauth has no `ACCOUNT_ALLOW_SIGNUPS`
  setting** — that name was in `settings.py` for months and did nothing. Both adapters
  call the one `provisioning_problem()` rule, so a password gets no one past **OSED's**
  rule. It **does** bypass Microsoft's own controls — MFA, conditional access, and Entra
  account disablement — which is why passwords are **issued by an admin only**, per person
  (user change page → **Reset password**). Imported users get unusable passwords.
  `osed/urls.py` returns 404 for allauth's `password/set/` (a user minting their own),
  `email/` (rewriting the address SSO matches on) and `password/reset/` (no mail backend;
  would be a single-factor route in the day one is added). `password/change/` stays open —
  it needs the current password. `LoginDoorsTests` guards all four.
  `/accounts/login/` is rate-limited by allauth, **but weakly** — see "Known discrepancies".
- **Microsoft refusals say which rule failed.** "You are not authorised to use this service"
  means no active user matches the email Entra sent — allauth takes Entra `mail`, falling
  back to `userPrincipalName`, which may differ from the address people email. "Your
  account is not configured with a school yet" means a user matched but has no profile
  (check for an older duplicate). The same two messages appear on a password refusal,
  except that an inactive user with the right password gets allauth's "account inactive"
  page. An error on a Microsoft page (`AADSTS…`) never reached OSED — that is the Entra
  app registration.
- **Authorization** = per-school scoping. Non-superusers are restricted to their
  `SchoolProfile` schools in **both** views (`_resolve_school_selection`,
  `_get_allowed_schools`) and admin (`_request_schools`). Any new view that reads or
  writes school data **must** go through these helpers — never trust a `school` id from
  the request without checking it against the user's allowed set.
- Superusers bypass school scoping by design.
- **Every redirect carries the school, for every user — never gate it on
  `is_superuser`.** Post-save redirects once emitted `school=` only for superusers, so a
  multi-school user was silently returned to their `SchoolProfile.school` after each save.
  On the in-depth review, whose filter bar also dropped `page`, the two composed into an
  unbreakable loop (live ticket, 10 Sept 2026 — see "Two schools is the case that breaks"
  below). Preserving the id grants nothing: `_resolve_school_selection` re-checks it
  against the user's own allowed set on the way back in, by **list membership**, not a
  database lookup. Build redirect params with `_school_param` / `_query_string`, and read
  a posted id with `_posted_school_id` (which coerces through `int()` before it reaches a
  `Location` header). `MultiSchoolPrincipalTests` goes red if any of that is undone.
- **`Risk QA`** is a Django group holding the single `review.qa_risk` permission. It grants
  the cross-school "awaiting QA" view — but **not** a scoping bypass: that view still
  filters through `_get_allowed_schools`, so a CFO account must be provisioned with every
  school it reviews, or its queue is silently partial.
- Nav gating: the **Risk** and **Operations & Resources** tabs are visible to every
  authenticated user *except governors* (read-only users included — the spec wants the full
  register visible at School Dashboard level). **Risk QA** is gated on `user_can_qa_risk`.
- **Governors are the one role defined by subtraction — see "Governor access" below.**
- No Committee or Trust Board roles exist. Those audiences have **no OSED logins** and see
  exported screenshots. Do not build click-through or external-audience login paths for
  them — that work is cancelled, not deferred. **Governors are the exception, agreed by the
  client on 9 Sept 2026**, and are the first external audience with logins; this line
  previously read "no Committee or Trust Board roles exist, deliberately" and forbade all
  such work, which the client has now overturned for governors only.

### Governor access

Added Sept 2026 after the client's green light. A governor reaches **three pages,
read-only** — School Dashboard, Trust Dashboard, Evaluation — plus Home. Everything else
in `review/urls.py` is refused with a **403** rendering `review/not_permitted.html`.

- **The role is `SchoolProfile.role`** (`FULL` default / `GOVERNOR`), **not a Django
  group**. Deliberate: a "Governor" *permission* would be a permission that **removes**
  access, and the admin presents permissions as grants — someone would eventually tick it
  onto a Principal believing it gave them something. Groups stay additive; the field
  answers a different question. Migration `0035` is additive with `default=FULL`, so it
  re-grades nobody. Superusers cannot be governors by construction (the role lives on a
  profile they are exempt from needing).
- **`user_can_edit` and `user_can_qa_risk` both return False for a governor**, checked
  *before* `EDIT_PERMS` / `qa_risk`. A misconfigured governor holding edit permissions
  still cannot save. Governor always wins.
- **The gate is `@governor_denied` on the view; the nav is decoration.** If the two
  disagree, the view is the truth. Note the decorator is a **deny-list, which fails open
  for the next view someone adds** — the guarantee is `GovernorUrlCoverageTests`, which
  walks `review/urls.py` and goes red on any route that is neither in `GOVERNOR_URL_NAMES`
  nor decorated. **That test is the feature.** Both halves are mutation-checked: neutering
  `user_is_governor` reddens 17 tests, making `governor_denied` a no-op reddens 15
  including the coverage test.
- **`home` is a deliberate fourth page**, excluded from `GOVERNOR_URL_NAMES` because it
  lives in `osed/urls.py`. Gating it would 403 a governor's own "Home" link.
- **The Trust Dashboard is school-scoped for governors like everyone else**, so a
  single-school governor sees a one-row grid. The **Risk exception report and the
  Operations roll-up are suppressed in `board_view` itself** (`show_trust_extras`), not
  only in the template — a technical 500 page renders the whole context. Client decision:
  governors do not see risk titles or owners.
- **`role` is deliberately not in `SchoolProfileAdmin.list_editable`.** The changelist
  writes back every row whose posted value differs from the database at POST time, so a
  submitter silently reverts rows they never touched — and `SchoolProfile` carries no
  `simple_history`, so the prior role is unrecoverable.
- The CSV importer takes an optional `role` column. An **unrecognised value skips the row**
  before any user is created; a **missing column reports a count** of accounts created with
  full access, because a mistyped header would otherwise silently make a spreadsheet of
  governors into editors.

## User provisioning — what actually links a person to a school

Learned from a live ticket (8 Sept 2026: a Principal "has access but is not assigned to
Copleston"). None of this is visible from the admin list page.

- A user's schools are `SchoolProfile.schools` (m2m) **plus** `SchoolProfile.school` (FK).
  `_get_allowed_schools` re-adds the FK if the m2m lacks it, so an **empty Schools box still
  works** — and, the other way round, **clearing the Schools box does not revoke access**.
- The admin's **Schools column cannot tell those two states apart**: `schools_access` inserts
  the FK name when it is missing, so "Copleston High School" renders identically for
  `m2m=[Copleston]` and `m2m=[]`. Open the change page to know.
- **Adding a User in the admin creates no `SchoolProfile`** — `SchoolProfileInline` is
  `extra=0`, so after "Save" the profile is behind an "Add another" link. Miss it and the
  person is refused at either login door (or, before the adapter fix, landed on the *"Not linked to a
  school"* 403 page — the wording they will repeat back to you). The list shows "—".
- The **CSV importer needs the exact `School.name`** ("Copleston High School", not
  "Copleston"); a non-matching row is skipped with an on-screen error, so read the results
  panel. It lowercases email; the admin add form does **not** normalise it.
- **`User.email` is not unique.** Both reads are `email__iexact` and `.first()` is
  pk-ordered on Django 6 (deterministic: oldest row wins), but nothing prevents or reports
  a duplicate. Refuse-on-duplicate is a pending follow-up, not built.
- **Offboarding: `is_active = False` is the only complete action.** Deleting the profile
  revokes SSO for non-superusers only; superusers skip the profile check entirely.
  **Disabling the person's Microsoft account does not end a password login** — anyone who
  was issued a password keeps it until OSED's `is_active` is cleared.
- Which Django user an Entra identity lands in is the `SocialAccount` row
  (`/admin/socialaccount/socialaccount/`) — check it before assuming the profile is wrong.

### Two schools is the case that breaks

Learned from a live ticket (10 Sept 2026: a Principal over Bacton and Mendlesham looping
between the in-depth ratings and commentary pages). **Most OSED bugs are invisible with one
school**, because every fallback lands you back where you started.

- Effective access is the m2m **union** the FK (`_get_allowed_schools`), so a profile with
  `m2m=[B]` and `FK=A` holds **two** schools. Counting `schools` alone under-reports who is
  exposed to a multi-school defect.
- Where a user lands when a school is not supplied is `SchoolProfile.school`, else
  `allowed_schools[0]` — **name-ordered**. Both fallbacks are silent.
- **Fixtures matter.** Every `SchoolProfile` in the suite was single-school for months,
  which is exactly why the loop shipped. When testing anything school-scoped, give the user
  two schools, make the FK school sort **first** alphabetically, and assert against the
  **other** one — otherwise a silent fallback passes by accident.
- Superusers cannot reproduce any of this: they keep `?school=` on paths where
  non-superusers once lost it. **Reproduce as a non-superuser with two schools, or you have
  not reproduced it.**

## Conventions

- Views are **function-based**, not class-based. Match that style.
- **Indentation is per file — match the file you are editing.** `views.py`, `admin.py` and
  `tests.py` use **tabs**; `models.py`, `forms.py`, `permissions.py`, `risk.py`,
  `operations.py`, `urls.py` and `context_processors.py` use **4 spaces**.
- Prefer editing existing helpers over adding parallel ones; reuse
  `_academic_year_context`, `_resolve_school_selection`, `_readonly_redirect`,
  `_school_param`, `_query_string`, `_posted_school_id`, and the
  `review/templates/review/includes/filter_*.html` selector partials.
- **A page that scopes to a school must name that school on screen**, via the
  `page-subtitle--school` block ("Working on <School>"). It used to render only in the
  single-school `{% else %}` branch, so the one user who most needed it — someone holding
  two schools — saw the name nowhere but inside a closed dropdown. Save confirmations name
  the school for the same reason. `MultiSchoolPrincipalTests` asserts it on all six scoped
  pages (dashboard, evaluation, in-depth ×2, reflection, overview); add new ones to that list.
- **A GET filter form must carry every piece of page state it does not want reset.** The
  commentary filter bar omitted its hidden `page` field, so using it dropped the user back
  to the ratings step — half of the loop above. Check the view's `request.GET.get(...)`
  calls against the form's fields when adding a filter.
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
group), `ensure_risk_qa_group` (the **Risk QA** group), and `prune_history` — which must
**never** go in `startup.sh`; see "Version history" above.

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
8. **Is the Entra app registration single-tenant?** `MICROSOFT_TENANT` defaults to
   `organizations` (`settings.py`), `AZURE_DEPLOYMENT.md` documents either, and the adapter
   authorises on the email claim alone. Multi-tenant + `organizations` is the nOAuth pattern;
   single-tenant makes it moot. Needs the live App Setting and the Entra portal checked.

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
- **`SchoolProfileAdmin.list_editable` still holds `school`**, and `save_model` forces
  `obj.school` to the alphabetically-first of the *editor's* schools on every row it saves —
  so a non-superuser editing one row on the changelist silently rewrites that row's landing
  school, and widens the target user's access (effective access is FK ∪ m2m). Bounded:
  needs `is_staff` plus `change_schoolprofile`, which the OSED Staff group does **not**
  grant. Pre-existing; `role` was kept out of `list_editable` rather than joining it.
  Flagged by the Purser, 10 Sept 2026.
- **`startup.sh` swallows a failed `migrate`** (`|| echo "Migrations failed (continuing)."`,
  line 27) and boots gunicorn anyway. That was survivable while every migration was
  feature-local. It no longer is: `nav_flags` calls `user_is_governor` on **every** render
  for every authenticated non-superuser, so an unapplied `0035` takes down every page in the
  site rather than one feature — and a 500 on an in-flight POST discards whatever was typed.
  After any deploy, confirm `showmigrations review | tail -1` shows `[X] 0035`.
- **`InDepthResponseAdmin` is the one school-linked admin with no `get_queryset` scoping**
  (`admin.py`, `InDepthResponseAdmin`) — every other one filters through `_request_schools`.
  An `is_staff` account holding `change_indepthresponse` (which OSED Staff grants) reads every
  school's evidence text there. Bounded by `is_staff`, which only superusers can set. Flagged
  8 Sept 2026; fix is five lines matching `InDepthReviewAdmin`; awaiting a decision.
- **The left-hand nav drops the working school.** Every tab in `base.html` is a bare path
  with no `school=`, so a multi-school user who moves from one tab to another is returned to
  their default school. Same silent switch as the 10 Sept ticket, different trigger; the
  "Working on <School>" banner is currently the only thing that surfaces it. Left as-is
  deliberately — making `_resolve_school_selection` session-sticky would hide the defect
  behind state and break the superuser workflow, so carrying `?school=` through the nav is a
  design decision awaiting a call. **Governors sharpen this considerably** (Lookout, Sept
  2026): a two-school governor logs in three times a year to *read*, crosses the Trust
  Dashboard which has no "Working on" banner at all, and lands on the wrong school with
  nothing on screen that felt like a change — the failure is not "gets stuck", it is
  "quotes the wrong school's judgements in a governors' meeting". `not_permitted.html` was
  given `school_param` so at least the recovery page does not itself switch school; the nav
  is still bare. **This is now the strongest argument for carrying `?school=` through the
  nav** and should be decided rather than left.
- **`word_limit.js` trims stored text on page load, and the next Save persists the trim.**
  `enforce(el, maxWords)` runs at init, before the user touches anything, and
  `trimToMaxWords` both drops the tail and collapses newlines into single spaces. Reachable
  for text entered via the admin or `import_indepth_workbooks`, with JS disabled, or if a
  limit is ever lowered — so save/reload/re-save is **not** byte-identical for an over-limit
  value. Flagged 10 Sept 2026; the fix is to drop the init-time `enforce` call and keep the
  counter, letting the server-side `_validate_max_words` reject it with the text intact.
- **The in-depth save has no stale-write guard.** Neither in-depth template emits
  `form_rendered_at`, so `_is_stale_write` short-circuits and the write at
  `views.py` is unconditional — two tabs on the same school/year/area silently overwrite each
  other, on the pages holding the longest free text. `evaluation.html` and `dashboard.html`
  both do it properly; copy them.
- **`unsaved_changes.js` binds to the first `form[method="post"]` only.** On
  `evaluation.html` that is the grade-override form whenever it renders, leaving the
  eight-category commentary form unguarded — navigate away and the typing is gone, with no
  warning and nothing saved to recover.
- **Redirect query strings are built two different ways** — f-string concatenation via
  `_query_string` in four views, list-of-tuples in `_readonly_redirect` / `risk_register` /
  `operations`. Unifying them into one `_redirect_with_params(url_name, **params)` is a
  worthwhile tidy, deliberately not done during the 10 Sept fix so the diff stayed readable.
- `/admin/login/` takes email+password with **no rate limit**; `/accounts/login/` is
  limited by allauth. `SOCIALACCOUNT_ONLY = True` would remove the `/accounts/` password
  path — **not an option now** that staff log in with passwords (see "Security model").
- **allauth's login rate limit is weaker than it looks** (Master-at-Arms, 11 Sept 2026).
  There is no `CACHES` setting, so the counters are per-process in-memory: they reset on
  every deploy and multiply with workers or instances. allauth ignores `X-Forwarded-For`
  unless told otherwise, so on App Service the per-IP bucket is **probably** Azure's front
  end — shared by the whole Trust (unverified). The per-email half (5 failures / 5 min)
  lets anyone lock a named person out of password login. Fix: log `REMOTE_ADDR` and
  `X-Forwarded-For` once in production, then set `ALLAUTH_TRUSTED_PROXY_COUNT` —
  **never blind**, a wrong count lets an attacker choose their IP. Move to
  `DatabaseCache` before adding workers.

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
- Subagents are fine and the crew is welcome; the retired personas (Les, Stella, Theo,
  Victor et al.) are not — see "How work happens in this repo" above.
