#!/bin/bash
set -e

echo "Running database migrations..."
uv run python -m alembic upgrade head

echo "Starting application..."
exec uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 10105 --workers 8 --proxy-headers --forwarded-allow-ips='*'
