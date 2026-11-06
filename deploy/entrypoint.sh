#!/bin/sh
set -eu
umask 077

if [ "${1:-}" = serve ]; then
    shift
    python manage.py migrate --noinput
    exec gunicorn config.wsgi:application \
        --bind "${ALCOVE_BIND:-127.0.0.1:8000}" --workers 1 --threads 4 --forwarded-allow-ips="" "$@"
fi

exec "$@"
