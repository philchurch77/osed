#!/usr/bin/env bash
set -e

# Apply any pending schema migrations on every release.
python manage.py migrate --noinput

# Idempotent seed steps (each command is safe to re-run).
python manage.py ensure_schema
python manage.py load_indepth_blueprint
python manage.py seed_schools
python manage.py seed_branding

# Create the admin user once, if DJANGO_SUPERUSER_* env vars are set.
python manage.py createsuperuser --noinput || true

# Launch the app. Azure's built-in Python container injects PORT (and nginx
# forwards to it); default to 8000 if it's ever unset. Using ${PORT} keeps this
# script portable across Azure and Render with no edits.
# --access-logfile/--error-logfile '-' send gunicorn logs to stdout/stderr so
# they surface in the App Service Log Stream.
exec gunicorn osed.wsgi:application \
    --bind=0.0.0.0:${PORT:-8000} \
    --workers=3 \
    --timeout=120 \
    --access-logfile '-' \
    --error-logfile '-'
