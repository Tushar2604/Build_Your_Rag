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
  #
  # Supervised, because that same arrangement hides a dead bridge: the container
  # stays healthy on the API alone, so a bridge that exits stays gone until
  # someone redeploys, and the only symptom is pairing failing with "the bridge
  # isn't responding". Restarting costs nothing — sessions are restored from
  # Postgres by resumeLinkedSessions() — while staying down costs the feature.
  (
    while true; do
      BRIDGE_API_BASE="${BRIDGE_API_BASE:-http://127.0.0.1:${PORT:-8000}}" \
        node "${BRIDGE_DIR}/src/index.js" || true
      echo "WhatsApp bridge exited; restarting in 5s"
      sleep 5
    done
  ) &
  BRIDGE_PID=$!

  # Without this, killing the container would orphan the bridge and leave the
  # WhatsApp sockets open until the process was reaped.
  trap 'kill "${BRIDGE_PID}" 2>/dev/null || true' TERM INT
elif [ -n "${BRIDGE_TOKEN}" ]; then
  # Distinguished from the unset-token case on purpose: this one means the image
  # was built without the sidecar, which is a build problem, not a config one.
  echo "WhatsApp bridge disabled (${BRIDGE_DIR} missing from the image)."
else
  echo "WhatsApp bridge disabled (BRIDGE_TOKEN unset)."
fi

PORT="${PORT:-8000}"

# Worker processes. One by default, because that is what a small/free instance
# has CPU for and because more workers multiply the database connection count:
# the ceiling is WEB_CONCURRENCY * (DB_POOL_SIZE + DB_MAX_OVERFLOW), which must
# stay under the database's own connection limit. Raise both together.
#
# Running more than one worker is safe: the follow-up sweep takes a Postgres
# advisory lock so exactly one process sweeps per tick (see `_sweep_lease`),
# and every other background job either claims rows with FOR UPDATE SKIP
# LOCKED or is idempotent. In-process state that is merely best-effort — the
# anonymous rate limiter, the LLM circuit breakers — becomes per-worker, which
# is a deliberate trade: they degrade gracefully rather than needing Redis.
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
echo "Starting API on :${PORT} with ${WEB_CONCURRENCY} worker(s)"
exec uvicorn src.interfaces.api.app:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --timeout-keep-alive 65
