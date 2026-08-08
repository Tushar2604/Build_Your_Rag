# --- Frontend build: compile the SPA (admin UI + /c/<key> share page) ---
FROM node:20-slim AS frontend
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # outputs /web/dist

# --- Builder: install Python dependencies into a venv ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# --- WhatsApp bridge deps: Baileys sidecar for personal-account QR linking ---
FROM node:20-slim AS bridge
WORKDIR /bridge

# Baileys depends on `libsignal` via a git URL (git+https://github.com/
# whiskeysockets/libsignal-node), and node:20-slim ships no git -- npm fails
# with a bare "unknown git error". Build-stage only: the runtime image copies
# the resolved node_modules and never needs git.
#
# The git config rewrite is insurance: npm records git deps in the lockfile as
# git+ssh://git@github.com/..., which needs SSH keys the builder doesn't have.
# The committed lockfile is already rewritten to https, so this only matters if
# someone regenerates it -- at which point the build keeps working instead of
# failing the same way again.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global url."https://github.com/".insteadOf ssh://git@github.com/

COPY whatsapp-bridge/package.json whatsapp-bridge/package-lock.json ./
# `ci` over `install`: installs exactly the locked tree (including the pinned
# libsignal commit), so a deploy can't silently pick up a different Baileys.
RUN npm ci --omit=dev --no-audit --no-fund
COPY whatsapp-bridge/src ./src

# --- Runtime: slim image with the venv, app, and built SPA ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# Non-root user for safety.
RUN useradd --create-home --uid 1000 appuser

# Node runtime for the WhatsApp bridge, lifted from the stage that already
# built its dependencies — so the binary and the native modules are guaranteed
# to be the same Node version. Both images are Debian bookworm, so the shared
# libraries line up. ~50MB, versus a full toolchain from apt.
COPY --from=bridge /usr/local/bin/node /usr/local/bin/node
COPY --from=bridge /usr/local/lib/node_modules /usr/local/lib/node_modules

COPY --from=builder /opt/venv /opt/venv
COPY --from=bridge /bridge ./whatsapp-bridge
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
# The built SPA — FastAPI serves it from this path (frontend/dist), giving a
# single public origin for the API, the widget script, and the share page.
COPY --from=frontend /web/dist ./frontend/dist

# appuser needs write access to create the local-disk upload fallback
# (LOCAL_STORAGE_DIR, a relative path under /app) when R2_* is unset.
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000

# Run DB migrations, then start the API. PORT is honoured for hosts (Render/Fly)
# that inject it.
CMD ["sh", "scripts/start.sh"]
