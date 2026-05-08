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
