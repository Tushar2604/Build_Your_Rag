#!/bin/sh
# Container entrypoint: apply migrations, then launch the API.
set -e

echo "Running database migrations..."
alembic upgrade head

PORT="${PORT:-8000}"
echo "Starting API on :${PORT}"
exec uvicorn src.interfaces.api.app:app --host 0.0.0.0 --port "${PORT}"
