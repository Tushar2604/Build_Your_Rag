// Session manager: one Baileys socket per linked WhatsApp account.
//
// Responsibilities are narrow on purpose — this process owns the WhatsApp
// connection and nothing else. It has no idea what a chatbot is; it reports
// events to the API and sends whatever text the API asks it to send. Keeping
// the RAG pipeline out of here means a WhatsApp reconnect storm can't take down
// the API, and vice versa.

import {
  makeWASocket,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";
import QRCode from "qrcode";
import pino from "pino";

import { useDbAuthState } from "./authStore.js";

const logger = pino({ level: process.env.BRIDGE_LOG_LEVEL || "warn" });

// Baileys emits a new QR every ~20s. We keep only the newest.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 60_000;
// A group JID ends in @g.us. Auto-replying into group chats is a fast way to
// get a number reported, so the bridge drops them before the API ever sees them.
const DIRECT_CHAT_SUFFIX = "@s.whatsapp.net";

/** Strip the WhatsApp JID down to an E.164 number. */
export function jidToPhone(jid) {
  if (!jid) return "";
  const bare = String(jid).split(":")[0].split("@")[0];
  return bare.startsWith("+") ? bare : `+${bare}`;
}

/** Pull display text out of the many shapes a WhatsApp message can take. */
export function extractText(message) {
  const m = message?.message;
  if (!m) return "";
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    m.buttonsResponseMessage?.selectedDisplayText ||
    m.listResponseMessage?.title ||
    m.templateButtonReplyMessage?.selectedDisplayText ||
    ""
  ).trim();
}

export class SessionManager {
  constructor({ pool, notify }) {
    this.pool = pool;
    // notify(sessionId, event, payload) -> POSTs to the API's bridge webhook.
    this.notify = notify;
    this.sockets = new Map();
    this.reconnectAttempts = new Map();
    this.timers = new Map();
  }

  has(sessionId) {
    return this.sockets.has(sessionId);
  }

  /** Start (or restart) a socket. Safe to call on an already-running session. */
  async start(sessionId) {
    await this.stop(sessionId, { keepAuth: true });

    const auth = await useDbAuthState(this.pool, sessionId);
    const { version } = await fetchLatestBaileysVersion();

    const sock = makeWASocket({
      version,
      auth: auth.state,
      logger,
      // We are a headless relay: announcing "online" would mark the user's real
      // messages as read on their phone, which they did not ask for.
      markOnlineOnConnect: false,
      // Shows up in the user's Linked Devices list, so it should name us.
      browser: ["Assistant Platform", "Chrome", "1.0.0"],
    });

    this.sockets.set(sessionId, { sock, auth });

    sock.ev.on("creds.update", auth.saveCreds);

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        try {
          const dataUrl = await QRCode.toDataURL(qr, { margin: 1, width: 384 });
          await this.notify(sessionId, "qr", { qr_data_url: dataUrl });
        } catch (err) {
          await this.notify(sessionId, "failed", { error: `QR render failed: ${err.message}` });
        }
      }

      if (connection === "open") {
        this.reconnectAttempts.delete(sessionId);
        await this.notify(sessionId, "linked", {
          phone_number: jidToPhone(sock.user?.id),
          display_name: sock.user?.name || "",
        });
      }

      if (connection === "close") {
        const code = lastDisconnect?.error?.output?.statusCode;
        const reason = lastDisconnect?.error?.message || "connection closed";
        // loggedOut means WhatsApp revoked the link (user removed the device,
        // or the number was banned). Retrying is pointless and looks like abuse.
        if (code === DisconnectReason.loggedOut) {
          await auth.clear();
          this.sockets.delete(sessionId);
          await this.notify(sessionId, "logged_out", { error: reason });
          return;
        }
        await this.notify(sessionId, "disconnected", { error: reason });
        this.scheduleReconnect(sessionId);
      }
    });

    sock.ev.on("messages.upsert", async (event) => {
      if (event.type !== "notify") return;
      for (const message of event.messages) {
        await this.handleInbound(sessionId, message);
      }
    });

    return sock;
  }

  async handleInbound(sessionId, message) {
    // fromMe: our own outgoing messages echo back; replying to them would make
    // the assistant talk to itself.
    if (message.key?.fromMe) return;

    const jid = message.key?.remoteJid || "";
    if (!jid.endsWith(DIRECT_CHAT_SUFFIX)) return; // groups, status, broadcasts

    const text = extractText(message);
    if (!text) return; // media with no caption, reactions, receipts

    await this.notify(sessionId, "message", {
      from: jidToPhone(jid),
      jid,
      text,
      message_id: message.key?.id || "",
      pushname: message.pushName || "",
    });
  }

  /** Exponential backoff — a tight reconnect loop against WhatsApp reads as
   * abuse and is a good way to get the number flagged. */
  scheduleReconnect(sessionId) {
    const attempt = (this.reconnectAttempts.get(sessionId) || 0) + 1;
    this.reconnectAttempts.set(sessionId, attempt);
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_MAX_MS);

    this.clearTimer(sessionId);
    this.timers.set(
      sessionId,
      setTimeout(() => {
        this.start(sessionId).catch(async (err) => {
          await this.notify(sessionId, "disconnected", { error: err.message });
          this.scheduleReconnect(sessionId);
        });
      }, delay),
    );
  }

  clearTimer(sessionId) {
    const timer = this.timers.get(sessionId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(sessionId);
    }
  }

  async sendText(sessionId, toJid, text) {
    const entry = this.sockets.get(sessionId);
    if (!entry) throw new Error("This WhatsApp session isn't connected.");
    await entry.sock.sendMessage(toJid, { text });
  }

  /** Stop the socket. `keepAuth` distinguishes a restart from an unlink. */
  async stop(sessionId, { keepAuth = true } = {}) {
    this.clearTimer(sessionId);
    this.reconnectAttempts.delete(sessionId);
    const entry = this.sockets.get(sessionId);
    this.sockets.delete(sessionId);
    if (!entry) return;

    try {
      if (keepAuth) {
        // end() closes the socket without telling WhatsApp to drop the device,
        // so the credentials stay valid and the next start needs no QR.
        entry.sock.end(undefined);
      } else {
        await entry.sock.logout();
        await entry.auth.clear();
      }
    } catch {
      // A socket that's already dead is exactly the state we wanted.
    }
  }

  async shutdown() {
    await Promise.all([...this.sockets.keys()].map((id) => this.stop(id, { keepAuth: true })));
  }
}
