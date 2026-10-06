#!/usr/bin/env bash
# Render runs this to build the site (render.yaml: buildCommand). It stops at the first error.
set -o errexit

pip install -r requirements.txt

# Nothing below serves a request, so the settings only need SOME allowed host to start (the running site gets its own from Render),
# and debug must be off so the static files get their fingerprinted names.
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS=localhost

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py ensure_superuser
