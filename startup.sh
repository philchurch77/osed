#!/usr/bin/env bash
set -euo pipefail

# Oryx starts this script with CWD already set to the extracted app path (e.g. /tmp/xxxx).
APP_ROOT="$(pwd)"

# 1) Activate the virtualenv created by Oryx (relative path)
VENV_PATH="$APP_ROOT/antenv"
if [ -d "$VENV_PATH" ]; then
  echo "Activating virtualenv: $VENV_PATH"
  # shellcheck disable=SC1091
  source "$VENV_PATH/bin/activate"
else
  echo "Warning: virtualenv not found at $VENV_PATH (Oryx may have set PYTHONPATH already). Continuing..."
fi

# 2) Python path + settings
export PYTHONPATH="$APP_ROOT:${PYTHONPATH:-}"
: "${DJANGO_SETTINGS_MODULE:=osed.settings}"
WSGI_PATH="${WSGI_PATH:-osed.wsgi:application}"

# 3) Migrations, schema + seed data, static.
#    Each step is idempotent and tolerant of failure so a transient error
#    (e.g. DB not yet reachable) doesn't block the app from booting.
if [ -f "$APP_ROOT/manage.py" ]; then
  echo "Running migrations..."
  python manage.py migrate --noinput || echo "Migrations failed (continuing)."

  echo "Ensuring schema + seed data..."
  python manage.py ensure_schema           || echo "ensure_schema failed (continuing)."
  python manage.py seed_categories         || echo "seed_categories failed (continuing)."
  python manage.py load_indepth_blueprint  || echo "load_indepth_blueprint failed (continuing)."
  python manage.py load_indepth_criteria   || echo "load_indepth_criteria failed (continuing)."
  python manage.py seed_schools            || echo "seed_schools failed (continuing)."
  python manage.py seed_branding           || echo "seed_branding failed (continuing)."

  # collectstatic is also run by Oryx during build (SCM_DO_BUILD_DURING_DEPLOYMENT=1);
  # repeated here defensively in case the build step is ever skipped.
  echo "Collecting static..."
  python manage.py collectstatic --noinput || echo "Collectstatic failed (continuing)."

  # Copy committed demo media (school logos + branding) into STATIC_ROOT/media so
  # WhiteNoise can serve them when MEDIA_AS_STATIC=1. Must run AFTER collectstatic.
  echo "Copying demo media into static..."
  python manage.py copy_demo_media_to_static || echo "copy_demo_media_to_static failed (continuing)."
fi

# 4) Start gunicorn from the current app path.
#    Default --workers is 1, which is safe for SQLite. If you run on Postgres,
#    add e.g. --workers=3 below.
echo "Starting gunicorn..."
exec gunicorn \
  --chdir "$APP_ROOT" \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 600 \
  --env "DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE" \
  "$WSGI_PATH"
