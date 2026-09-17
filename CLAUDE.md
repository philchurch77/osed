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
- Run tests: `python manage.py test review` (**277 tests** in `review/tests.py`; the suite
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
  in-depth review, reflection, **risk_register, risk_qa, operations, context_dashboard**).
  The in-depth grade is derived from a RAG "ladder" by `conclude_indepth_grade`.
- **`review/powerbi.py`** — everything the app knows about the Power BI embed, in **one
  place**: `resolve_embed(school)`, `is_configured()`, and the two verbatim standing texts.
  It has no branch that yields an unfiltered report. See "Context Dashboard" below.
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
  `LoginDoorsTests.setUp` calls `cache.clear()`: allauth's rate-limit counters live in the
  in-memory cache across tests and are keyed on user pk, which SQLite reuses after each
  rollback — without it, change-password POSTs in one test count against the next (429).
  Guarded by `LoginDoorsTests` (29 tests; the rule was mutation-checked when it had 15:
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

### Before you believe a reported loss, count the cargo (17 Sept 2026)

A client reported in-depth work missing at Bacton and Mendlesham, "definitely there Monday",
deadline the next day. **Nothing had been deleted — and the client was right.** Two
write-ups (12,686 and 5,777 characters) had been written on 10 Sept against Strong Standard
statements; on 16 Sept a rating change moved each review's concluded grade down to Expected,
and the commentary page — which filtered statements to the grade's rung — stopped rendering
them. "There Monday, gone Wednesday" was exactly accurate. The third area named, Inclusion,
had never held text on any date history covers.

The first census reported `hidden=0` and the wrong-school explanation was sent to the client.
It was wrong: the census defined "hidden" as text-without-a-rating and never asked about
text-on-a-rung-the-page-does-not-render. The Surgeon had named that mechanism as its leading
hypothesis and was overridden on the strength of a count that could not see it. Fixed the
same day: `views.py` now renders any statement that already holds a write-up, whatever rung
it sits on and whether or not it is still rated, and a block shown only for that reason
carries `kept_for_text` so the template can say why it is there (a "Strong Standard" heading
under an "Expected Standard" grade otherwise reads as "OSED still thinks I'm at Strong" —
the client's own words). Guarded by five tests in `InDepthJudgementAreaFlowTests`; removing
the `written` union reddens three of them.

The lesson is the order of operations, because the instinct is to reach for a restore:

1. **Establish gone-versus-hidden before anything else.** They present identically on screen
   and need opposite responses. `history_type` settles it: `+` created, `~` changed,
   `-` deleted. **No `-` rows means nothing was deleted, full stop.**
   **"Hidden" has more than one shape**, and a census must ask the page's own filter, not a
   proxy for it: text with no rating, text on a rung the page does not render, text on a
   deactivated `Category`. If a view decides what to show, reproduce that decision in the
   query or render the page — a count that checks one shape will report `hidden=0` while
   thousands of characters sit unrendered.
2. **Check whether the text ever existed**, not just whether it exists now — the longest
   `evidence_text` across *all* history rows for that review. "Never written" and "written
   and destroyed" look the same in a live table and completely different in history.
3. **A school-and-area-specific pattern is not what deletion looks like.** A catalogue purge
   cascades across every school equally. Selective loss points at scoping, a render filter,
   or perception — and "the client is confused" is the explanation to reach for **last**.
4. **Know what the app cannot do.** There are exactly two `.delete()` calls in `views.py`,
   both on `InDepthResponse`, and **no code path anywhere deletes an `Evaluation`** — so
   "all our ratings have gone" can never be a user's doing.
5. **Say what the history floor is.** It proves nothing before migration `0034`, 9 Sept 2026
   — and the original incident was destroying written work right up to that date. "It was
   there Monday" can be a misremembered date rather than a wrong claim, and that is the one
   case that cannot be disproved. Do not let a clean history report harden into "they
   imagined it".

The read-only census used is in the incident scratchpad rather than the repo; it is twenty
lines of ORM and is quicker to rewrite than to find.

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
  would be a single-factor route in the day one is added), and `3rdparty/` (listing or
  disconnecting the linked Microsoft identity — **exact path only**: `3rdparty/login/cancelled/`
  and `login/error/` are where Microsoft returns a failed sign-in). `password/change/` stays
  open — it needs the current password, and since 14 Sept 2026 it is **linked from the nav**
  ("Change password", shown only when `user.has_usable_password`) and styled by
  `templates/account/password_change.html`. The client had reported that password users could
  not replace an admin's temporary password: the page existed but nothing linked to it. A
  successful change signs out every other session. `templates/allauth/layouts/base.html` puts
  the remaining stock allauth pages inside `review/base.html`, because allauth's own layout
  linked to the closed routes. `LoginDoorsTests` guards all of it. **A "Forgot password"
  button was requested at the same time and is not built** — it needs a mail backend and
  reopens `password/reset/`; awaiting a client decision (see "Open with the client").
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
- **Issuing a password: one temporary password per person, never a shared one.** The person
  replaces it via the nav's "Change password" (needs the current one; signs out other
  sessions). A shared temporary password lets anyone who knows it change a colleague's
  first, and **nothing records a password change** — no `password_changed` receiver, and
  `LOGGING` is WARNING+. `MinimumLengthValidator` is at its default of **8**;
  Master-at-Arms suggested 12 for a route that bypasses MFA (new passwords only). Both are
  open suggestions (14 Sept 2026), not built.
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
- Where a user lands when a school is not supplied **used to be** `SchoolProfile.school`,
  else `allowed_schools[0]` — name-ordered, and both fallbacks silent. **Since 16 Sept 2026
  there is no fallback for a multi-school user**: they are asked. A single-school user still
  lands on their one school, which is not a guess. See "Ask, don't guess" below.
- **Fixtures matter.** Every `SchoolProfile` in the suite was single-school for months,
  which is exactly why the loop shipped. When testing anything school-scoped, give the user
  two schools, make the FK school sort **first** alphabetically, and assert against the
  **other** one — otherwise a silent fallback passes by accident.
- Superusers cannot reproduce any of this: they keep `?school=` on paths where
  non-superusers once lost it. **Reproduce as a non-superuser with two schools, or you have
  not reproduced it.**

### Ask, don't guess (16 Sept 2026)

`_resolve_school_selection` used to end `school_profile.school or allowed_schools[0]`, so a
page opened without a school silently picked one. That is gone.

- **A user holding more than one school who has not named one gets a chooser and no data.**
  It is returned through the third slot of `_resolve_school_selection`, which every scoped
  view already returns unexamined — so no view runs a query, builds a formset or saves while
  no school is chosen. **Superusers get it too**: the school they would otherwise land on is
  the first of every school in the Trust.
- **Single-school users are untouched.** Being shown a list of one is friction with nothing
  behind it. The Trust Dashboard is untouched too — it is trust-wide on purpose.
- **On POST it is a 409 refusal, not a redirect.** A save whose `school_id` is missing,
  malformed or naming a school outside the user's own set is refused rather than falling
  through to their default school — `reflection` in particular writes every area
  unconditionally, so that fallback could put one school's words onto another's. It renders
  rather than redirects so the posted body is not discarded, and offers no forward button:
  that would reload the form from the database and bury the unsaved text two steps back.
- **`_select_from_allowed` is the shared rule**, split out because `overview` builds its own
  phase-filtered candidate list. Resolution is by **list membership**, never a database
  lookup on the raw id. Two copies of "which school are we on" is how one ends up a term
  behind the other.
- The nav carries `school=` via `nav_school_param`, read from the query string rather than
  the database so it costs no query. **Home stays bare deliberately** — it is not scoped.

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
7. **The Power BI Context Dashboard shipped in the weak mode, by the client's choice.**
   Three things are still open and must not be silently resolved: (a) **resolved
   17 Sept 2026** — filter on the new school-level `Schools` table, not `(1) Oxlip Students`
   (whose name cannot be URL-filtered anyway); the exact **column** in `Schools` still needs
   confirming, and it is one App Setting, no deploy; (b) **who holds Power
   BI access and under which licence** — staff without it see a Microsoft sign-in page
   inside OSED's chrome; (c) whether to fund the app-owns-data upgrade in
   `POWERBI_EMBED_PLAN.md` §3, which is the only version where `SchoolProfile` is the
   single source of truth. Export/print policy and the absent read-access log go with it.
8. **Is the Entra app registration single-tenant?** `MICROSOFT_TENANT` defaults to
   `organizations` (`settings.py`), `AZURE_DEPLOYMENT.md` documents either, and the adapter
   authorises on the email claim alone. Multi-tenant + `organizations` is the nOAuth pattern;
   single-tenant makes it moot. Needs the live App Setting and the Entra portal checked.
9. **Self-service "Forgot password" (requested 14 Sept 2026, not built).** OSED has no
   `EMAIL_BACKEND` or Azure mail service, and a reset-by-email link lets anyone who can read
   a mailbox mint a password that bypasses MFA, conditional access and Entra disablement.
   Needs a mail service and the client's acceptance of that trade-off. Change-password
   (needs the current one) was built instead.

## Context Dashboard — the Power BI embed that shipped (Sept 2026)

`/review/context/` frames the Trust's **Oxlip Context Dashboard** Power BI report, opened
at the school `_resolve_school_selection` resolved. Off by default: the nav tab and the
page both come from `powerbi.is_configured()`, which needs `POWERBI_ENABLED`, a
`POWERBI_REPORT_URL` on `app.powerbi.com`, and a space-free `POWERBI_FILTER_TARGET`.

**The one thing to understand before touching it: the filter is not an access control.**
The client supplied a *user-owns-data* secure embed (`autoAuth=true`), so the viewer signs
in to Power BI with their own Microsoft account and OSED cannot mint an identity for them.
OSED chooses which school the report **opens at** — via a URL query-string filter the
viewer can change inside the frame or in the address bar. Access is decided by Power BI
workspace permissions and whatever RLS is on the dataset: a second access-control system
this repo cannot see, cannot test and cannot keep in step with `SchoolProfile`.
`POWERBI_EMBED_PLAN.md` §3 **rejected this mode**, and that rejection stands on its merits.
It shipped anyway because the client chose it, in writing, on 17 Sept 2026, on the
condition that the page says what it is — which is what `powerbi.FILTER_NOTICE` is for.
It is rendered verbatim and asserted by a test. **Do not soften it, and never describe
this page as restricting a user to their own school.**

- **Everything Power BI knows lives in `review/powerbi.py`.** `resolve_embed(school)`
  returns `(url, unavailable_reason)` with exactly one set, and has **no branch that
  returns an unfiltered URL** — not configured, wrong host, malformed filter target or a
  blank school mapping all yield an explanatory panel and no iframe. An all-schools view
  handed to whoever opened the page would be invisible from this end.
- **`School.powerbi_school_name` is the mapping**, because the report's slicer matches the
  OSED name in **none** of the seven cases ("Copleston", not "Copleston High School").
  `seed_schools` sets it **only when blank** and `--force` does not override it, so an
  admin's correction survives the next deploy. It is a display-string match, **not** a
  stable key — when app-owns-data arrives it still needs the DfE URN of §4.1.
- **No trust-wide view was built.** When one is, it takes its own permission shaped like
  `Risk QA` — never `is_superuser`, which would silently re-grade every existing superuser
  (§4.4). `multi_school_filter_expression` is there for that day and is unreachable today.
- **Governors are denied** (`@governor_denied`, hidden from the nav). `GOVERNOR_URL_NAMES`
  is deliberately untouched — the decorator is what keeps `GovernorUrlCoverageTests` green.
- **OSED records that the page was opened** — user pk, school, timestamp, at INFO on the
  `review` logger (the root is WARNING, so `settings.LOGGING` raises it deliberately).
  What it cannot record is what was **read** in Power BI: it never brokers that request,
  and Power BI logs the viewer's own Microsoft identity in a different system with a
  different read audience. §4.5's audit trail is therefore thinner here than under
  app-owns-data — a real regression, and the client knows.
- **Filter on the `Schools` table, never the student table.** The semantic model behind
  this report contains `(1) Oxlip Students` — one row per child, carrying `forename`,
  `Ethnicity`, `SEN`, `EHCP or SEN Support`, `FSM` and `in_lea_care`, i.e. **special
  category data about children**. A school-level `Schools` table was added on 17 Sept 2026
  to aggregate and filter against, and `POWERBI_FILTER_TARGET` points at that
  (`Schools/<school-name column>`). The student table's own name could not be URL-filtered
  anyway — a leading `(`, a digit and two spaces — and `FILTER_TARGET_RE` refuses it.
- **§4.6's walkthrough is therefore not optional, and has not been done.** OSED's filter is
  not a boundary, and RLS filters rows rather than pages: a visual bound to the student
  table, a drillthrough, or "Show as table" on any chart reaches pupil rows regardless of
  what OSED sends. Before `POWERBI_ENABLED=1`, someone with report access must walk every
  page, every visual, the filter pane, every drillthrough and every "show as table" as a
  single-school user and then as a two-school user, and record the result. If any pupil row
  is reachable, this build is **not** adequate — `POWERBI_EMBED_PLAN.md` §7 applies in full
  and it needs the DPO before it is switched on.
  **Sharpened on 17 Sept 2026, and no longer hypothetical.** The panel now renders (see the
  COOP entry below), and what the Context page shows is *aggregates* — percentages and
  counts, not pupil rows, which is better than feared. But on one primary of a few hundred
  on roll, several cohorts came out under five and **two came out at exactly one** — a care
  status and an exclusion — on the same page as Ethnicity, FSM, SEN/EHCP and persistent
  absence. An aggregate of one is an individual record wearing a percentage sign, and in a
  primary where staff know every child it is re-identifiable by anyone who can do the
  arithmetic. §7's small-number suppression (cohorts under 5) is therefore a live
  requirement now, not a later refinement. (The school and the figures are deliberately not
  recorded — see §7; a repo is the wrong place to keep them.) **"Show as table"
  and the drillthroughs have still not been tried by anyone** — that is the half of §4.6
  that reaches underneath the aggregates, and it remains undone.
- **There is still no CSP**, so the `EMBED_URL_PREFIX` startswith-check in `powerbi.py` is
  the only thing stopping a mistyped App Setting framing an arbitrary site. `frame-src`
  belongs in its own passage; until then, do not remove that check.
- **The panel needs a relaxed `Cross-Origin-Opener-Policy`, set on the view response and
  nowhere else.** Power BI's in-frame "Sign in" opens a blank popup and then navigates it
  to `login.microsoftonline.com`. Django's default `SECURE_CROSS_ORIGIN_OPENER_POLICY =
  "same-origin"` — which `SecurityMiddleware` stamps on every response, in dev and
  production alike, and which **this project never chose** — severs that popup from its
  opener, so the navigation is a silent no-op. `context_dashboard` sets
  `same-origin-allow-popups` on its own response when (and only when) a frame was built.
  It works because `SecurityMiddleware` uses `response.setdefault(...)`, so a header the
  view already set survives the middleware.
  **Do not promote this to `SECURE_CROSS_ORIGIN_OPENER_POLICY` in `settings.py`** — that
  relaxes the login page, the admin and every school's data to fix a popup that exists on
  one page. `ContextDashboardOpenerPolicyTests` guards both halves: removing the header
  reddens 1 test, promoting it to a global setting reddens **7**.
  Three things about the diagnosis, because it cost a day: the failure is **silent** —
  popup opens and strands on `about:blank`, console logs nothing, **zero** requests reach
  Microsoft — so there is no error to search for. It **cannot be reproduced locally**, as
  COOP is ignored on insecure origins. And the obvious console check
  (`w = open(); w.location = "…"`) **does not reproduce it and is misleading**: a URL-less
  `open()` inherits OSED's own origin, and COOP `same-origin` does not sever a same-origin
  popup. Power BI's case differs because its popup is opened from inside the cross-origin
  iframe. That test said "not COOP"; COOP it was.
- **The frame is shaped to the report, and one CSS line in it is load-bearing.**
  `.bi-frame-wrap` is `aspect-ratio: 16 / 9.5` — the canvas is authored 16:9, and the extra
  height is for Power BI's own page-tab strip, which it draws *inside* the frame at a fixed
  height whatever the width. At exactly 16/9 the strip eats into the canvas and Power BI
  answers with a scrollbar. It is a fitted number, not a derived one: scrollbar means go
  taller, empty band means go shorter.
  Separately, `.bi-frame`'s `position: relative` looks redundant beside `display: block;
  width: 100%` and **is not**. `.bi-frame-loading` above it is a full-size
  `position: absolute; inset: 0` element with no background; both are `z-index: auto` and
  paint in tree order, so that one property is the only thing putting the iframe last and
  letting it take the clicks. Remove it as a tidy and every click inside the report quietly
  stops working, for everyone, with nothing on screen to show for it.

If the embedded report would duplicate the Trust Dashboard, do not build on it — that
summary is generated from tile data specifically so it cannot drift, and it goes into board
packs.

## Known discrepancies (pre-existing, unresolved)

- **`base.html` ships a developer note, and an unfinished one, in an HTML comment on every
  page.** `review/templates/review/base.html:6-8` carries a Google Search Console note in
  `<!-- -->`, so it is invisible on screen but readable in view-source site-wide — and the
  `<meta name="google-site-verification">` below it still holds the literal
  `REPLACE_WITH_META_TAG_TOKEN_FROM_SEARCH_CONSOLE`, so verification by the meta-tag method
  was never completed. Use `{% comment %}` for the note (it never reaches the page) and
  either finish or remove the meta tag. Found by the Lookout, 17 Sept 2026; pre-existing and
  unrelated to the Context Dashboard, so left alone.
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
- ~~**The left-hand nav drops the working school.**~~ **Resolved 16 Sept 2026** — see
  "Ask, don't guess" below. The nav now carries `school=` (`272bb86`) and the silent
  fallback is gone (`2dd979f`). Kept here only as a pointer: the governor case that
  sharpened it — "quotes the wrong school's judgements in a governors' meeting" — is the
  reason the fix is worth defending if anyone proposes reinstating a default.
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
- **The `{% if messages %}` block is copied into 12 templates** (every page template plus
  `account/login.html` and `account/password_change.html`) rather than rendered once in
  `review/base.html`. Not broken; the tidy is to render it above `{% block content %}` in
  the base and delete the copies — check no page renders messages somewhere other than the
  top first. Flagged by the Carpenter, 14 Sept 2026.
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
