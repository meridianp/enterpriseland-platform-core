#!/bin/bash
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput || true

echo "Starting Gunicorn on port ${PORT:-8080}..."
exec gunicorn --bind 0.0.0.0:${PORT:-8080} \
    --workers 4 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    platform_core.wsgi:application