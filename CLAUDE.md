# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**OSED** is a Django 6 self-evaluation tool for a multi-academy trust. Schools record
termly **dashboard ratings** and structured **in-depth reviews** across judgement areas;
trust leaders and trustees view aggregated results. Access is via **Microsoft SSO**, with
authorization handled in-app and scoped per school.

Single Django app: `review`. Project package: `osed`.

## Running locally (Windows)

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Local dev uses **SQLite** (`db.sqlite3`) and `DEBUG=1` via a gitignored `.env`
  (copy from `.env.example`). Production uses **Postgres** via `DATABASE_URL`.
- Run tests: `python manage.py test review` (~34 tests in `review/tests.py`).
- Pre-deploy security check: `python manage.py check --deploy` with `DEBUG=0`.

## Architecture & key files

- **`osed/settings.py`** — all config is env-driven. `DEBUG` defaults to **False**;
  production raises `ImproperlyConfigured` if `SECRET_KEY` or `DATABASE_URL` is missing.
  `ALLOWED_HOSTS` is derived from the `ALLOWED_HOSTS` env var plus Azure's
  `WEBSITE_HOSTNAME`, and `CSRF_TRUSTED_ORIGINS` is derived from `ALLOWED_HOSTS` — so a
  custom domain is added in one place. Production HTTPS hardening (HSTS, secure cookies,
  SSL redirect) is gated behind `if not DEBUG`.
- **`review/views.py`** — function-based views (dashboard, overview, board, evaluation,
  in-depth review, reflection). The in-depth grade is derived from a RAG "ladder" by
  `conclude_indepth_grade`.
- **`review/models.py`** — `School`, `Category`, `SchoolProfile`, `ReviewPeriod`,
  `Evaluation`, and the in-depth models (`InDepthArea` → `InDepthStandard` →
  `InDepthJudgementArea`; `InDepthReview` → `InDepthResponse`). No pupil-level PII —
  only staff emails and school-level evaluation text.
- **`review/permissions.py`** — `user_can_edit(user)`: superusers and users holding the
  `EDIT_PERMS` may edit; everyone else is read-only (viewers/trustees).
- **`review/allauth_adapters.py`** — `RestrictMicrosoftLoginAdapter`: SSO only admits
  pre-provisioned users (existing active `User` + `SchoolProfile`).
- **`review/admin.py`** — multi-tenant admin; includes a CSV user-import view
  (`import-users/`, superuser only).

## Security model (do not weaken)

- **Authentication** = Microsoft SSO. Self-registration is disabled
  (`ACCOUNT_ALLOW_SIGNUPS = False`). Imported users get unusable passwords (SSO-only).
- **Authorization** = per-school scoping. Non-superusers are restricted to their
  `SchoolProfile` schools in **both** views (`_resolve_school_selection`,
  `_get_allowed_schools`) and admin (`_request_schools`). Any new view that reads or
  writes school data **must** go through these helpers — never trust a `school` id from
  the request without checking it against the user's allowed set.
- Superusers bypass school scoping by design.

## Conventions

- Views are **function-based**, not class-based. Match that style.
- Files use **tab** indentation (see `views.py`/`admin.py`) — preserve it.
- Prefer editing existing helpers over adding parallel ones; reuse
  `_academic_year_context`, `_resolve_school_selection`, etc.
- Academic year is stored as a start year (e.g. `2026`) but displayed as `2026-2027`;
  `MIN_ACADEMIC_YEAR_START = 2026`.

## Data / seeding management commands (idempotent)

Run at deploy time on **Azure** by `startup.sh` (the live path): `migrate`,
`ensure_schema`, `seed_categories`, `load_indepth_blueprint`, `load_indepth_criteria`,
`import_indepth_workbooks`, `seed_schools`, `seed_branding`, `collectstatic`,
`copy_demo_media_to_static`. One-off: `ensure_osed_staff_group` (creates the **OSED
Staff** editor group). In-depth criteria source data lives in `review/data/` — the
per-area supporting-tool workbooks (e.g. `Updated P16 2026.xlsx`) drop into
`review/data/workbooks/` and are picked up by `import_indepth_workbooks`.

> Ordering matters: `load_indepth_criteria` (from `criteria.json`) runs **before**
> `import_indepth_workbooks`, so where an area has a workbook, the workbook wins. An
> area with no workbook keeps its `criteria.json` text.

> The importer takes the area name from **A1** of the first standard sheet (falling back
> to A2 of `Expected Standard`/`Strong Standard`). A workbook that arrives with a blank
> A1 on its first sheet will fail with "Could not determine area name" — fix the cell in
> the workbook rather than the importer.

> `ensure_schema` and migrations `0023`/`0024` are deliberate `IF NOT EXISTS` repair
> shims for a production Postgres DB on which migration `0020` was only partially
> applied. Keep them; `ensure_schema` must run before `migrate`.

## Deployment

**Azure App Service is the only deployment target.** There is no second environment.

- See **`AZURE_DEPLOYMENT.md`** (the single source of truth) — startup command
  `bash startup.sh`, Postgres Flexible Server, and required App Settings.
- `startup.sh` is the live deploy path: it runs migrations, the seed/import commands and
  `collectstatic`, then launches gunicorn. Anything that must reach production has to be
  wired into that script.
- Media: local disk in dev; production uses `MEDIA_AS_STATIC=1` (demo assets via
  WhiteNoise) or Azure Blob (`USE_AZURE_MEDIA_STORAGE=1`).

## Guardrails

- Never commit `.env` or `db.sqlite3` (both gitignored; keep it that way).
- Don't set `DEBUG=1` in any production config.
- Commit/push only when asked.
