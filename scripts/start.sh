#!/bin/sh
# Container entrypoint: apply migrations, start the WhatsApp bridge (if
# configured), then launch the API in the foreground.
set -e

echo "Running database migrations..."
alembic upgrade head

# The Baileys sidecar owns the personal-WhatsApp sockets. It is optional: with
# no BRIDGE_TOKEN the API reports the feature as unconfigured and everything
# else works unchanged, so a deploy without it is a supported configuration.
BRIDGE_DIR="/app/whatsapp-bridge"
if [ -n "${BRIDGE_TOKEN}" ] && [ -d "${BRIDGE_DIR}" ]; then
  echo "Starting WhatsApp bridge on :${BRIDGE_PORT:-8081}"
  # Backgrounded so the API stays PID 1's foreground child and the platform's
  # health check (which probes the API) governs the container's liveness.
  BRIDGE_API_BASE="${BRIDGE_API_BASE:-http://127.0.0.1:${PORT:-8000}}" \
    node "${BRIDGE_DIR}/src/index.js" &
  BRIDGE_PID=$!

  # Without this, killing the container would orphan the bridge and leave the
  # WhatsApp sockets open until the process was reaped.
  trap 'kill "${BRIDGE_PID}" 2>/dev/null || true' TERM INT
else
  echo "WhatsApp bridge disabled (BRIDGE_TOKEN unset)."
fi

PORT="${PORT:-8000}"
echo "Starting API on :${PORT}"
exec uvicorn src.interfaces.api.app:app --host 0.0.0.0 --port "${PORT}"
