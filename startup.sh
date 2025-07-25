#!/bin/bash
set -e

# Set Python path to include the app directory
export PYTHONPATH=/app:$PYTHONPATH

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
    --chdir /app \
    platform_core.wsgi:application