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
  // Managed Postgres closes idle connections server-side — Neon's free tier
  // suspends the whole compute after a few minutes. The pool cannot tell a
  // dropped socket from a live one until it runs a query, which is where
  // "Connection terminated unexpectedly" comes from. Expiring our own idle
  // connections first means we reconnect on demand instead of handing out a
  // socket the server has already closed.
  idleTimeoutMillis: 10_000,
  // Generous on purpose. A suspended Neon compute can take 10-20s to accept its
  // first connection, and a timeout shorter than that cold start turns a slow
  // wake-up into "Connection terminated due to connection timeout" — a failure
  // that looks like a dead database but is really an impatient client.
  connectionTimeoutMillis: Number(process.env.BRIDGE_DB_CONNECT_TIMEOUT_MS || 30_000),
  keepAlive: true,
  ssl: /sslmode=require/.test(process.env.DATABASE_URL || "")
    ? { rejectUnauthorized: false }
    : undefined,
});

// An idle client that dies emits 'error' on the pool. With no listener that is
// an uncaught exception, which used to take the whole bridge down every time
// the database went away for a moment.
pool.on("error", (err) => {
  log.warn({ err: err.message }, "idle database client error");
});

/**
 * Take the cold start once, at boot, instead of on someone's first scan.
 *
 * Pairing is the latency-sensitive path: the QR is only valid for ~20s, so a
 * 15s database wake-up inside that window is the difference between a code that
 * scans and one that has already expired. Waking the database here moves that
 * cost to a moment when nobody is waiting.
 */
async function warmDatabase() {
  try {
    await pool.query("SELECT 1");
    log.info("database reachable");
  } catch (err) {
    // Not fatal: the bridge still serves, and the retry path will wake the
    // database on demand. Worth logging loudly because it predicts slow pairing.
    log.warn({ err: err.message }, "database not reachable at boot");
  }
}

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
    const body = await res.json().catch(() => null);
    // The API already tells us when a session row is gone; until now nothing
    // acted on it, so an unlinked session kept its socket and its reconnect
    // timer forever — retrying a link that can never be restored, and filling
    // the logs with failures for a session the user deleted minutes ago.
    if (body?.status === "unknown_session") {
      log.info({ sessionId }, "session no longer exists — stopping socket");
      manager.stop(sessionId, { keepAuth: false }).catch(() => {});
    }
    return body;
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
  await warmDatabase();
  await resumeLinkedSessions();
});

async function shutdown(signal) {
  log.info({ signal }, "shutting down");
  server.close();
  await manager.shutdown();
  await pool.end().catch(() => {});
  process.exit(0);
}

// Node's default for an unhandled rejection is to kill the process. That is the
// wrong trade here: nearly every async path in this service touches Postgres or
// a WhatsApp socket, and a managed database that briefly refuses a connection
// (Neon suspends when idle) would otherwise take the bridge down for good. The
// API keeps serving either way, so the failure is invisible — it shows up only
// as "the bridge isn't responding" the next time someone tries to pair.
process.on("unhandledRejection", (reason) => {
  log.error({ err: reason instanceof Error ? reason.message : String(reason) }, "unhandled rejection");
});
process.on("uncaughtException", (err) => {
  log.error({ err: err.message }, "uncaught exception");
});

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
