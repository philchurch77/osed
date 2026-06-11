# OSED

Local development (Windows)

1. Create/activate a virtualenv
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run migrations:
   - `python manage.py migrate`
4. Start the dev server:
   - `python manage.py runserver`

Deploy to Render

- This repo includes a `render.yaml` blueprint.
- Render will:
  - install requirements
  - run `collectstatic`
  - run `migrate`
  - start the app with `gunicorn osed.wsgi:application`

Environment variables

- `SECRET_KEY` (Render generates this from `render.yaml`)
- `DEBUG` (Render sets `0`)
- `DATABASE_URL` (Render sets from the managed Postgres database)
- Optional (Microsoft login):
  - `MICROSOFT_CLIENT_ID`
  - `MICROSOFT_CLIENT_SECRET`
  - `MICROSOFT_TENANT`

Notes

- In local dev, SQLite is used by default.
- In Render, the app uses Postgres via `DATABASE_URL`.
- Migrations `0023`/`0024` and the `ensure_schema` management command are intentional
  repair shims for the Render Postgres database (migration `0020` was partially applied
  there). They use defensive `IF NOT EXISTS` SQL and must be kept; `render.yaml` runs
  `ensure_schema` before `migrate` during each build.

User accounts / roles

- **Superuser**: full access, including `/admin/`.
- **Staff (editors)**: sign in via Microsoft SSO, must have a `SchoolProfile`, and must be granted edit permissions (recommended: add them to the **OSED Staff** group).
- **Viewer (trustees)**: sign in via Microsoft SSO and must have a `SchoolProfile` linking them to the school(s) they may view; they can view data but cannot save changes.

To create/update the **OSED Staff** group (once):

- `python manage.py ensure_osed_staff_group`

Media uploads (logos, branding)

This app uses Django `ImageField` for:
- `School.logo` (uploads to `school_logos/`)
- `Branding.trust_emblem` (uploads to `branding/`)

Where uploaded files go depends on your storage backend:

Local development

- Uploading in `/admin/` saves files into the local folder `media/`.
- You can see them on disk under:
   - `media/school_logos/...`
   - `media/branding/...`
- When running `python manage.py runserver`, Django serves them at URLs like `/media/...`.

Render / production

On Render’s free plan, the filesystem is ephemeral. If you save uploads into `media/` on the web service, they may disappear on redeploy/restart and won’t be shared across instances.

Demo logos/branding (committed assets)

This repo includes demo logo + branding images committed under `media/branding/` and `media/school_logos/`, and the Render blueprint seeds the database to reference them.

To make those demo images reliably visible on Render without setting up cloud storage, `render.yaml` enables `MEDIA_AS_STATIC=1` and runs `python manage.py copy_demo_media_to_static` during the build. That copies the demo media assets into `staticfiles/media/...`, and Django will generate ImageField URLs like `/static/media/...` which WhiteNoise can serve.

Recommended: Azure Blob Storage for media

This repo already includes `django-storages[azure]`. To make admin uploads persist in production, enable Azure media storage:

1. Create an Azure Storage Account + a Blob Container (e.g. `media`).
2. In Render, set these environment variables on your web service:
    - `USE_AZURE_MEDIA_STORAGE=1`
    - `AZURE_ACCOUNT_NAME=...`
    - `AZURE_ACCOUNT_KEY=...`
    - `AZURE_CONTAINER=media`  (or your container name)
    - Optional: `AZURE_CUSTOM_DOMAIN=...` (if you front the container with a custom domain/CDN)
3. Redeploy.

After that, files uploaded in the Django Admin are stored in Azure, and the `.url` for each image points at the blob URL.
