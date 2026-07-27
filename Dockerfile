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

# --- Runtime: slim image with the venv, app, and built SPA ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# Non-root user for safety.
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv
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
