// WhatsApp bridge — HTTP control plane over the Baileys session manager.
//
// Binds to localhost by default: this service has no per-tenant authorization
// of its own, so anything that can reach it can drive any linked account. The
// API is the only intended caller, they share a container, and a shared secret
// is checked on every request as a second lock.

import express from "express";
import pg from "pg";
import pino from "pino";

import { SessionManager } from "./sessions.js";

const log = pino({ level: process.env.BRIDGE_LOG_LEVEL || "info" });

const PORT = Number(process.env.BRIDGE_PORT || 8081);
const HOST = process.env.BRIDGE_HOST || "127.0.0.1";
const TOKEN = process.env.BRIDGE_TOKEN || "";
const API_BASE = (process.env.BRIDGE_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");
const EVENT_PATH = "/api/v1/whatsapp-web/bridge-events";

if (!TOKEN) {
  log.error("BRIDGE_TOKEN is unset — refusing to start an unauthenticated bridge.");
  process.exit(1);
}

/** Convert a Postgres URL that may carry SQLAlchemy's driver suffix. */
function normalizeDbUrl(url) {
  return (url || "").replace("postgresql+asyncpg://", "postgresql://");
}

const pool = new pg.Pool({
  connectionString: normalizeDbUrl(process.env.DATABASE_URL),
  // The bridge is bursty and mostly idle; a big pool would just hold Neon
  // connections open next to the API's own pool.
  max: Number(process.env.BRIDGE_DB_POOL || 4),
  ssl: /sslmode=require/.test(process.env.DATABASE_URL || "")
    ? { rejectUnauthorized: false }
    : undefined,
});

/** Report an event to the API. Never throws — a momentarily unreachable API
 * must not kill the WhatsApp socket that produced the event. */
async function notify(sessionId, event, payload) {
  try {
    const res = await fetch(`${API_BASE}${EVENT_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": TOKEN,
      },
      body: JSON.stringify({ session_id: sessionId, event, ...payload }),
    });
    if (!res.ok) {
      log.warn({ sessionId, event, status: res.status }, "api rejected bridge event");
      return null;
    }
    return await res.json().catch(() => null);
  } catch (err) {
    log.warn({ sessionId, event, err: err.message }, "could not reach api");
    return null;
  }
}

const manager = new SessionManager({ pool, notify });

const app = express();
app.use(express.json({ limit: "1mb" }));

app.use((req, res, next) => {
  if (req.path === "/healthz") return next();
  if (req.get("X-Bridge-Token") !== TOKEN) {
    return res.status(403).json({ detail: "Invalid bridge token" });
  }
  next();
});

app.get("/healthz", (_req, res) => {
  res.json({ status: "ok", sessions: manager.sockets.size });
});

/** Start a session — begins the pairing flow, or restores an existing link. */
app.post("/sessions/:id/start", async (req, res) => {
  try {
    await manager.start(req.params.id);
    res.json({ status: "starting" });
  } catch (err) {
    log.error({ err: err.message }, "session start failed");
    res.status(500).json({ detail: err.message });
  }
});

/** Stop the socket but keep credentials, so it can resume without a re-scan. */
app.post("/sessions/:id/stop", async (req, res) => {
  await manager.stop(req.params.id, { keepAuth: true });
  res.json({ status: "stopped" });
});

/** Unlink for real: tells WhatsApp to drop the device and wipes the keys. */
app.post("/sessions/:id/logout", async (req, res) => {
  await manager.stop(req.params.id, { keepAuth: false });
  res.json({ status: "logged_out" });
});

app.post("/sessions/:id/send", async (req, res) => {
  const { jid, text } = req.body || {};
  if (!jid || !text) {
    return res.status(400).json({ detail: "jid and text are required" });
  }
  try {
    await manager.sendText(req.params.id, jid, text);
    res.json({ status: "sent" });
  } catch (err) {
    res.status(502).json({ detail: err.message });
  }
});

app.get("/sessions", (_req, res) => {
  res.json({ sessions: [...manager.sockets.keys()] });
});

/**
 * Restore links after a restart.
 *
 * The API knows which sessions were linked; the bridge holds no state of its
 * own across restarts. Without this, a redeploy or a free-tier sleep would
 * leave every linked account silently dead until someone re-scanned.
 */
async function resumeLinkedSessions() {
  try {
    const { rows } = await pool.query(
      `SELECT id FROM whatsapp_web_sessions
       WHERE status IN ('linked', 'disconnected') AND linked_at IS NOT NULL`,
    );
    for (const row of rows) {
      manager.start(row.id).catch((err) =>
        log.warn({ sessionId: row.id, err: err.message }, "resume failed"),
      );
    }
    if (rows.length) log.info({ count: rows.length }, "resuming linked sessions");
  } catch (err) {
    log.error({ err: err.message }, "could not resume sessions");
  }
}

const server = app.listen(PORT, HOST, async () => {
  log.info({ host: HOST, port: PORT }, "whatsapp bridge listening");
  await resumeLinkedSessions();
});

async function shutdown(signal) {
  log.info({ signal }, "shutting down");
  server.close();
  await manager.shutdown();
  await pool.end().catch(() => {});
  process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
