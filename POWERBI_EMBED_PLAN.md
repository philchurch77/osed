# Power BI embed — feature plan (not built)

**Status: SUPERSEDED IN PART — 17 September 2026.**
Drafted 6 September 2026 as planning only.

A **user-owns-data** embed shipped on 17 September 2026 as an interim: `/review/context/`,
`review/powerbi.py`, `School.powerbi_school_name`. That is the mode §3 below **rejected**,
and §3 is not retracted — it is the reason the shipped page carries `FILTER_NOTICE`
verbatim, telling the user that Power BI and not OSED controls what they can see.

What changed is the input, not the analysis. The client supplied only an `autoAuth=true`
embed URL, with no capacity, service principal or workspace grant behind it, and on
17 September chose "build it, labelled honestly" over waiting.

**Correction, same day.** The semantic model behind this report does contain a pupil-level
table — `(1) Oxlip Students`, one row per child, carrying `forename`, `Ethnicity`, `SEN`,
`EHCP or SEN Support`, `FSM` and `in_lea_care`. A school-level `Schools` table was added to
aggregate and filter against, and `POWERBI_FILTER_TARGET` points at that. **That settles how
OSED filters; it does not settle what a viewer can reach.** §7 is therefore live rather than
set aside, and §4.6's manual walkthrough is a precondition of switching the feature on, not
a nicety: RLS filters rows and not pages, so a visual bound to the student table, a
drillthrough, or "Show as table" reaches pupil rows whatever OSED sends. If any pupil row
proves reachable from a report page, **this build is not adequate** and the DPO screens it
before `POWERBI_ENABLED=1`.

Read the rest of this document as the plan for the **app-owns-data upgrade**, which is
still the only version where `SchoolProfile` is the single source of truth. Three of its
protections are absent from what shipped and the client has been told so: **§4.1** (a stable
DfE URN — a mutable display-string match is used instead), **§4.4** (a distinct trust-wide
permission — no trust-wide view was built at all), and **§4.5** (a full read-access log — OSED
records that the page was opened, but never what was read, since it does not broker the
request). **§8's second paragraph
describes app-owns-data and must not be sent to the client about this build.**

The request: embed a Power BI summary page in OSED, filtered to the signed-in user's
school, with a trust-wide view for superusers.

---

## 1. The short answer

**The Django work is 2–3 days. The feature is weeks, and roughly four-fifths of it is
not code.**

| Phase | What | Effort |
|---|---|---|
| 0 — Tenant & licensing | Fabric/Power BI capacity, Entra app registration, workspace grant | Not code. 1–3 weeks elapsed, mostly waiting |
| 1 — Semantic model | A dataset with a school key and an RLS role. **Carries the real risk** | 3–5 days of BI work, **none of it in this repo** |
| 2 — Django | `powerbi.py`, view, template, settings, nav, model field | 2–3 days |
| 3 — Tests & deploy config | Scoping tests, `AZURE_DEPLOYMENT.md` | 1 day |

The Django side is small because `_resolve_school_selection` and `_get_allowed_schools`
already answer the only question Power BI needs answered. Phase 1 is where this goes
wrong: if nobody has decided what the report is *of*, the embed is a frame around an
empty room — and Phase 0 will have committed the Trust to a recurring capacity bill
before anyone finds out.

---

## 2. Blocking questions — answer before costing

These are the Trust's decisions, not coding decisions. Do not silently resolve them.

1. **Does the report contain pupil-level rows, or aggregate/cohort figures?**
   Everything else scales from this answer. See §7.
2. **Does the Power BI report/dataset actually exist yet?** Nothing in this repo implies
   a warehouse or semantic model. If there is none, Phase 1 is the whole project.
3. **Who controls the warehouse?** The Trust itself (internal disclosure — update the
   Article 30 record and the privacy notice) or an LA/third party (a data sharing
   agreement or Art 26 joint-controller arrangement is needed before a row crosses).
4. **Which named individuals get the trust-wide view?** Today that would be every Django
   superuser. It should almost certainly be a shorter, deliberately provisioned list.
5. **Is export/print enabled in the embed, and what retention applies** to the resulting
   files on school laptops?
6. **What is the Power BI tenant's data region?** A non-UK/EU capacity is an
   international transfer decision, not a technical detail.
7. **Is this the cancelled trustee work in disguise?** CLAUDE.md records that Committee
   and Trust Board roles are cancelled, not deferred, and those audiences have no OSED
   logins. If the motive is "so trustees can look for themselves", that needs the client,
   not an implementer.
8. **Does the report duplicate the Trust Dashboard?** If so, do not build it. The
   executive summary is *generated* from tile data precisely so it cannot drift from what
   it summarises, and it goes into board packs as a screenshot. A second Power BI view of
   the same numbers reintroduces exactly the drift that was designed out. The feature
   earns its place only if it does something OSED cannot — finance, MIS, multi-year trend.

---

## 3. Approach: app-owns-data, and why not the others

| Option | Verdict |
|---|---|
| **Publish to web** | **Ruled out.** Publishes to the anonymous internet with a guessable URL, is search-indexed, and honours no RLS at all. School judgement grades and an open risk register are not public documents even without pupil PII. Say so to the client in writing. |
| **Secure embed, user-owns-data** | **Rejected.** Cheapest on the invoice, most expensive in the audit. Authorization moves into Power BI workspace permissions and the dataset's own `USERPRINCIPALNAME()` mapping — a second access-control system this repo cannot see, cannot test, and which will drift from `SchoolProfile` the first time someone is added in one place and not the other. Against the "every view goes through the scoping helpers" rule in CLAUDE.md. |
| **App-owns-data ("embed for your customers")** | **Recommended.** A service principal mints a short-lived embed token carrying an effective identity that *OSED chooses*. Viewers need no Power BI licence. Costs a dedicated Entra app registration and a Fabric/Power BI capacity (F SKU, or a pausable A SKU). In exchange `SchoolProfile` stays the single source of truth. |

The matching RLS role is `PATHCONTAINS(USERNAME(), [URN])` on the school dimension with
`|` as the separator. That one expression covers single-school and multi-school users
identically, which is why it is worth insisting on over an `IN VALUES` variant
(`SchoolProfile.schools` is a ManyToMany — a user can hold several).

---

## 4. Six things that must be designed in from the first commit

Retrofitting any of these is a schema change, a security incident, or both.

### 4.1 A stable `School` key — and fail closed when it is missing

`review/models.py:37-50`. `School` has `name` (a plain `CharField`, **not** `unique=True`),
`phase`, `is_mainstream`, `logo` and an auto pk. Neither candidate works as a warehouse
join:

- `name` is mutable, non-unique and already drifts elsewhere in this codebase. An admin
  renaming a school silently changes what the RLS filter matches — either the user sees
  nothing, or they see the wrong school.
- The auto pk is meaningless to the warehouse and unstable across a re-seed.

Add a DfE URN, unique, admin-editable, and **refuse to mint a token when it is blank**.
That single fail-closed branch is what makes the whole feature safe. A `School` with no
URN must render "not yet configured for reporting" — never an unfiltered report.

`seed_schools.py` already holds the seven canonical school names, is idempotent, and is
already run by `startup.sh`, so the URN backfill needs no new deploy step.

### 4.2 Validate, then mint — never the reverse

The embed token is a bearer credential in the page source. It is unrevocable for its
lifetime (up to 60 minutes), extractable from the DOM, and replayable directly against
the Power BI API. Whatever identity is baked in at mint time is what the holder gets.
There is no server-side undo.

Required ordering:

1. `@login_required`
2. Resolve the school through `_resolve_school_selection` (`review/views.py:161`).
   **Never read `request.GET["school"]` in the embed view.**
3. No school resolves → 403, no token
4. Map `School` → URN. Missing → 403, no token, log it
5. Only now call Power BI, with the identity listing **every** dataset the report binds to
6. Return the token from an authenticated, same-origin JSON endpoint

The client must not influence scope: report id, workspace id, dataset ids and role name
are server-side config. The token endpoint accepts no `report`, `dataset` or `role`
parameter.

**A trap in the existing helper — FIXED, September 2026; do not act on this paragraph.**
`_resolve_school_selection` no longer substitutes a school: commit `2dd979f` changed it to
return the school chooser with `refused=True`, so a forged `?school=` is refused visibly
rather than silently swapped. It fails closed **and says so**, and the wrap-the-helper
instruction below is no longer needed. The original text, kept so the reasoning survives:
`_resolve_school_selection` fails closed but *silently* — it filtered a forged `?school=`
id against `allowed_schools` and fell back to the user's own school. Correct for rendering a dashboard; wrong for minting
a token, where a malformed or unauthorised id must produce a 403 rather than quietly
minting for whatever school sorted first. Wrap the helper for the embed view; do not
change it.

### 4.3 `no-store` on the token endpoint

Django sets no `Cache-Control` on a plain `JsonResponse`. A token carrying School A's
identity, cached by the browser bfcache or any intermediary, hands School A's data to
School B's principal for the rest of its lifetime. Set `Cache-Control: no-store, private`,
use `@never_cache`, and add a test asserting the header — this is exactly the kind of
thing a well-meaning performance change removes.

### 4.4 A distinct trust-wide permission

`is_superuser` currently means "sees all schools' self-evaluation text". Pointed at a
trust-wide pupil dataset, every existing superuser account is silently re-graded to "can
see every pupil in the Trust" — an authorization escalation caused by a data change, with
no code review moment and no notification to whoever granted those accounts. The warehouse
is also likely *broader* than OSED's scope (MIS, possibly HR, possibly other trusts'
benchmarking), so "superuser sees everything" would mean everything the dataset holds.

Add `review.view_trust_bi` as its own permission and group, shaped exactly like the
existing `Risk QA` group. Decouple it from `is_superuser`, which also carries Django
admin, the CSV user import and the visibility grid.

The trust-wide view must **still** be minted with an identity carrying a trust-scope RLS
role. Never omit the identity to get "see everything" — an identity-free token is bounded
only by the service principal's own permissions, which is the entire warehouse.

### 4.5 A view-access log

OSED records who *wrote* (`Evaluation.updated_by`) but nothing records who *read*, and
`LOGGING` is console-only at WARNING. In the app-owns-data model Power BI's own activity
log records the **service principal**, not the end user — so OSED would be the only
possible source of "who looked at this child's record, and when", and it would not have it.

A small `BiAccessLog(user, school, report_key, created_at)` written at token-mint time.
One insert per embed load. Retrofitting an audit trail after an incident produces a log
that starts the day someone asked for it.

### 4.6 RLS DAX with no blank-identity escape hatch

The common developer-convenience pattern
`IF(ISBLANK(USERNAME()), TRUE(), [URN] = USERNAME())` turns an empty identity into full
access. An empty or missing school must yield **zero** rows. Ask to see the DAX; do not
accept "RLS is on" as an answer.

Related: RLS filters rows, not pages. A page bound to a non-RLS aggregate table, a text
box with a worked example, or a drillthrough onto a different table all bypass it.
**Manual acceptance test before go-live:** sign in as a School A user and walk every page,
every visual, the filter pane, every drillthrough and every "show as table". Repeat as a
two-school user. Repeat as a school with no URN.

---

## 5. File-by-file change list

Indentation is per file — `views.py`, `admin.py` and `tests.py` use **tabs**; everything
else here uses **4 spaces**.

1. **`review/models.py`** — add `urn` to `School` after `name`, with a `Meta`
   `UniqueConstraint` conditional on `~Q(urn="")`. The condition matters: on Postgres a
   plain `unique=True` with `default=""` collides on the second unconfigured school.
   `School` has no `Meta` today, so this adds one.
   Do **not** add a `PowerBiReport` catalogue model — one report is two env vars.
2. **`review/migrations/00XX_school_urn.py`** — `AddField` + `AddConstraint`. Schema only;
   the URNs are not in the repo.
3. **`review/management/commands/seed_schools.py`** — extend the tuples to
   `(name, phase, urn)`, setting `urn` only where blank and warning rather than
   overwriting an admin edit. No `startup.sh` change needed.
4. **`review/admin.py`** (tabs) — `urn` into `SchoolAdmin.list_display` and
   `search_fields`. `School` is already in `ADMIN_SECTIONS`, so `AdminIndexGroupingTests`
   stays green.
5. **`review/powerbi.py`** (new, 4 spaces) — beside `risk.py` and `operations.py`, so all
   Power BI knowledge is in one place:
   - `class PowerBiNotConfigured(Exception)`
   - `_aad_token()` — MSAL client-credentials on scope
     `https://analysis.windows.net/powerbi/api/.default`
   - `mint_embed_token(*, urns, trust_wide)` → dataclass of `token`, `embed_url`,
     `report_id`, `expires_at`
   - raises `PowerBiNotConfigured` when config is missing **or any school in scope has a
     blank URN**
   - `@sensitive_variables()` on the mint function so locals are scrubbed from tracebacks
6. **`review/views.py`** (tabs) — `analytics` (GET only, `@login_required`, no edit path so
   no `_readonly_redirect`) and `analytics_token` (`JsonResponse`, `@never_cache`, repeats
   the *entire* scope derivation and takes no identity input from the client). Catch
   `PowerBiNotConfigured` and render an explanatory panel — never a broken iframe.
7. **`review/urls.py`** — `analytics/` and `analytics/token/`.
8. **`review/templates/review/analytics.html`** — extends `base.html`, reuses
   `includes/filter_school_field.html`, `filter_year_field.html`, `filter_actions.html`.
   `{% comment %}` for anything multi-line; save as UTF-8.
9. **Static** — vendor `powerbi.min.js` into `review/static/review/vendor/` rather than a
   CDN (supply chain, and it keeps `script-src 'self'`), plus an embed JS that refreshes
   the token on a ~50-minute timer. Then run `collectstatic` with `DEBUG=0` and confirm
   both land in `staticfiles/staticfiles.json` — under
   `CompressedManifestStaticFilesStorage` a missing entry hard-fails the page.
10. **`osed/settings.py`** — `POWERBI_ENABLED` (default `False`), `POWERBI_TENANT_ID`
    (defaulting to `MICROSOFT_TENANT`), `POWERBI_CLIENT_ID`, `POWERBI_CLIENT_SECRET`,
    `POWERBI_WORKSPACE_ID`, `POWERBI_REPORT_ID`, `POWERBI_DATASET_ID`, `POWERBI_RLS_ROLE`,
    `POWERBI_TRUST_ROLE`, `POWERBI_TOKEN_MINUTES`. Guard in the existing shape: raise
    `ImproperlyConfigured` when `POWERBI_ENABLED and not DEBUG` and anything is missing.
    Use a **separate** app registration from `MICROSOFT_CLIENT_ID` — the SSO app is a
    delegated public-facing flow; the embed app is a service principal with Power BI API
    permissions, added to the workspace as a Member. Do not merge them.
11. **`review/context_processors.py`** — add `show_analytics_tab` to the existing
    `nav_flags` dict. Do not add a parallel processor.
12. **`review/templates/review/base.html`** — nav link gated on `show_analytics_tab`,
    matching the `show_operations_tab` pattern.
13. **`requirements.txt`** — add `msal` (pinned) and declare `requests` explicitly rather
    than relying on allauth pulling it in transitively.
14. **`review/tests.py`** (tabs) — the tests that matter: a two-school user gets exactly
    those two URNs; a superuser/BI-permission holder gets the trust role; a forged
    `?school=` outside the allowed set is ignored; a blank URN yields
    `PowerBiNotConfigured` and no token; `analytics_token` re-derives scope and ignores any
    client-supplied school; the `no-store` header is present. Mock the outbound HTTP — the
    suite must not call Azure.
15. **`AZURE_DEPLOYMENT.md`** — the new App Settings and the app-registration step.

---

## 6. Secrets, headers and browser posture

**The existing pattern is sound and should be copied verbatim.**
`MICROSOFT_CLIENT_SECRET` is read from env, placed only into `SOCIALACCOUNT_PROVIDERS`,
never rendered, never templated. `.env` is gitignored, `.env.example` carries a commented
placeholder with no value. There is no secret in the repo.

- **Prefer no secret at all.** Azure App Service is the only deployment target, so a
  managed identity or federated credential is available and removes rotation entirely.
  Worth checking before defaulting to a client secret (which caps at 24 months and expires
  silently).
- **Four leak paths to check:** never interpolate the token into a cacheable
  server-rendered template; never put it in a URL (`django.request` logs full paths at
  ERROR, and the Azure log stream has a wider read audience than the app); never log the
  MSAL response body (`acquire_token_for_client` returns a dict *containing*
  `access_token` — log the error code and correlation id only); and note there is
  currently **no logging call anywhere in `review/`**, so this risk is entirely in the new
  code.
- **CSP is absent and this is the moment to add it.** Django 6 ships CSP support natively,
  no new dependency. Minimum: `frame-src https://app.powerbi.com` scoped to the exact host,
  `frame-ancestors 'none'`, `default-src 'self'`.
- **Do not touch `X_FRAME_OPTIONS`.** It is unset, so Django's default `DENY` applies —
  that governs OSED *being framed*, and is unaffected by OSED framing Power BI. Expect
  someone to propose relaxing it after misreading an embed guide. It is unrelated.
- **Do not set `SameSite=None`.** An embedded third-party iframe does not carry OSED
  cookies; if this is proposed to "make the embed work", it is a misdiagnosis.
- **`postMessage`** is the only channel between page and iframe (different origins, so
  neither can read the other's DOM). Any custom handler must check `event.origin`, and the
  token must never be posted with a `"*"` target.
- **Referrer** is already `same-origin` by Django default, so no school id leaks to
  `app.powerbi.com` in a `Referer`. Pin it with a test.
- **Session lifetime.** `SESSION_COOKIE_AGE` is unset, so the default two-week rolling
  session applies. Today that grants a stale session read access to commentary; after this
  feature the same stale session on an unlocked staffroom machine is a live window onto
  pupil data. This is the realistic breach path in a school. Tighten to roughly a working
  day with `SESSION_EXPIRE_AT_BROWSER_CLOSE = True` — with SSO the re-login cost is a click,
  and it is a good line in the DPIA.

**Failure modes must be visibly closed.** If Power BI is unreachable, the token call fails,
or the school has no URN: a plain "This report is unavailable" and a server-side log. Never
a cached token, a previously rendered report, a default school, or an identity-free embed.

---

## 7. Data protection

If the report surfaces **pupil-level** data this is very likely a **mandatory** DPIA, not a
discretionary one — it engages several ICO screening triggers at once: special category
data, data concerning children, vulnerable subjects, systematic use, and a new technology
combining previously separate datasets.

That OSED stores none of it is not a defence. Under Art 4(2) OSED would be performing the
disclosure, and OSED's code alone decides who sees which school.

**Recommendation: do not build the pupil-level version until the DPO has screened it and
either signed a DPIA or recorded in writing why one is not required.** The aggregate-only
version is a materially different and much lighter proposition and should be priced as an
alternative first.

If pupil-level rows are genuinely needed, apply small-number suppression (cohorts under 5)
so that "2 pupils, Year 3, persistent absence, SEND" cannot re-identify a child from an
aggregate.

Also settle: export/print policy (RLS is respected, so no cross-school leak — but it
produces pupil-level files on school laptops, outside OSED, outside the warehouse and
outside any retention rule); how long the access log is kept and who may read it; and
whether the existing pupil privacy notice covers analytics use via a third-party
self-evaluation platform.

---

## 8. Wording for the client conversation

Accurate to the code **as it stands today** — the second paragraph describes design
commitments and must not be said until §4.1, §4.2 and §4.5 are built and tested. A DPO
will remember the sentence.

> "OSED holds no pupil records itself. Sign-in is Microsoft SSO restricted to accounts the
> Trust has provisioned in advance — self-registration is disabled, and an unrecognised
> account is refused at the door. Every page resolves which school you may see from your
> account, server-side, before any data is read; a school identifier supplied in a URL is
> checked against your permitted schools and ignored if it is not one of them."
>
> "For the Power BI summary, the filter is applied by the reporting service using an
> identity our server generates from your account after that check — it is not something
> the browser can alter, and there is no request a user can craft that widens it. We record
> who opened which school's report and when, so the Trust can answer a subject access
> request or investigate a concern."

---

## 9. Verified as sound (do not re-litigate)

Checked against the code during planning:

- `RestrictMicrosoftLoginAdapter` fails closed on every branch — no email, no matching
  active user, or no `SchoolProfile` all deny. `ACCOUNT_ALLOW_SIGNUPS = False` and
  `SOCIALACCOUNT_AUTO_SIGNUP = False`.
- The unauthorised-`?school=` path already fails closed — the forged id is never honoured,
  and since commit `2dd979f` the user is shown the school chooser rather than quietly given
  their own school. The line reference in this bullet is stale; see §4.2. Pin this with a
  test asserting the *minted identity*.
- Settings hygiene: `DEBUG` defaults False, production raises without `SECRET_KEY` or
  `DATABASE_URL`, no wildcard in `ALLOWED_HOSTS`, HSTS and secure cookies under
  `if not DEBUG`.
- No secrets in the repo.
- Every view in `review/urls.py` is `@login_required`, and `risk_qa` re-checks permission
  in the view rather than relying on nav gating. Follow that pattern.
- No existing outbound API call anywhere in `review/`. The Power BI call would be the
  **first** service-to-service call in this codebase — treat it as new territory, not as
  another instance of an existing pattern.

---

## 10. Who is needed

- **Gunner** — the scoping tests in step 14, before this ships.
- **Master-at-Arms** — the RLS role and token handling, once written.
- **Bosun** — `analytics.html` and the `staticfiles.json` check.
- **Nobody in this crew has Power BI or Fabric expertise.** Phase 1 needs someone from the
  Trust's side or a partner, confirmed *before* Phase 0 spends any money.
