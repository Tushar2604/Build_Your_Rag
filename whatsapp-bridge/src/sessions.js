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
import {
  buildMediaContent,
  describeMedia,
  extractText,
  fetchMedia,
  MAX_MEDIA_BYTES,
  previewFor,
} from "./media.js";
import { CHUNK_SIZES, chunk, toContactRows, toMessageRows } from "./history.js";

export { extractText };

const logger = pino({ level: process.env.BRIDGE_LOG_LEVEL || "warn" });

// Baileys emits a new QR every ~20s. We keep only the newest.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 60_000;
// A group JID ends in @g.us. Auto-replying into group chats is a fast way to
// get a number reported, so the bridge drops them before the API ever sees them.
const DIRECT_CHAT_SUFFIX = "@s.whatsapp.net";
// WhatsApp's phone-number-privacy rollout addresses some direct chats by an
// opaque "linked ID" instead of the phone number — Baileys treats @lid as a
// fully valid 1:1 chat address (see isLidUser / decodeMessageNode in
// @whiskeysockets/baileys), not a group/broadcast type. A contact whose chat
// happens to be LID-routed was previously indistinguishable from a group here
// and silently dropped: no log, no error, the message just never arrived.
const LID_CHAT_SUFFIX = "@lid";

/**
 * Baileys carries `messageTimestamp` as a number on some paths and a protobuf
 * `Long` on others. Both reduce to unix seconds; anything else becomes 0, which
 * the API reads as "age unknown".
 */
export function messageTimestamp(message) {
  const raw = message?.messageTimestamp;
  if (raw == null) return 0;
  const seconds = typeof raw === "object" && typeof raw.toNumber === "function"
    ? raw.toNumber()
    : Number(raw);
  return Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
}

/** Strip the WhatsApp JID down to an E.164 number. */
export function jidToPhone(jid) {
  if (!jid) return "";
  const bare = String(jid).split(":")[0].split("@")[0];
  return bare.startsWith("+") ? bare : `+${bare}`;
}

export class SessionManager {
  constructor({ pool, notify, uploadMedia, fetchMedia: fetchMediaFn, syncHistory }) {
    // Receives batches of imported contacts/messages. Injected for the same
    // reason as the others: this class should not know about HTTP.
    this.syncHistoryFn = syncHistory;
    this.pool = pool;
    // Injected rather than imported: the manager owns WhatsApp sockets and
    // knows nothing about where files live. Tests pass a stub.
    this.uploadMediaFn = uploadMedia;
    // The download talks to WhatsApp's CDN, so it is the one step that cannot
    // run without a live socket. Injecting it keeps the surrounding decisions
    // — size caps, what happens when a fetch fails — testable.
    this.fetchMediaFn = fetchMediaFn || fetchMedia;
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
      // Ask the phone for the widest history it will give. Without this a newly
      // linked device sees only messages that arrive from now on, so the inbox
      // opens empty against an account with years of conversations. Even with
      // it, WhatsApp caps what it sends — this widens the window, it does not
      // transfer everything.
      syncFullHistory: true,
    });

    this.sockets.set(sessionId, { sock, auth });

    // Baileys ignores the promise this returns, so a failed write would surface
    // as an unhandled rejection rather than anything actionable. Losing one
    // creds flush is survivable — Baileys emits another on the next key change —
    // so log it and keep the socket alive.
    sock.ev.on("creds.update", () => {
      auth.saveCreds().catch((err) =>
        logger.error({ sessionId, err: err.message }, "could not persist creds"),
      );
    });

    // The phone pushes history asynchronously after linking, in several chunks
    // over minutes. Each arrives here.
    sock.ev.on("messaging-history.set", async (payload) => {
      await this.importHistory(sessionId, payload);
    });

    sock.ev.on("connection.update", async (update) => {
      // Ignore events from a socket we have already replaced or deliberately
      // stopped. Baileys delivers `close` asynchronously after `end()`, so
      // without this a stop would schedule a reconnect and resurrect itself,
      // and a restart (start() begins with stop()) would leave the outgoing
      // socket's timer to re-enter start() a couple of seconds later — which
      // rotates the QR out from under whoever is scanning it.
      if (this.sockets.get(sessionId)?.sock !== sock) return;

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
      // "notify" is a message delivered on a live socket. "append" is anything
      // WhatsApp had queued and flushed on connect — Baileys picks between the
      // two purely on `node.attrs.offline` (lib/Socket/messages-recv.js), so
      // "append" covers the operator's own messages typed on the phone AND a
      // contact's reply that landed while this socket was down.
      //
      // Both are stored, and both may be answered. Treating "append" as
      // unanswerable is what made a campaign reply vanish whenever the bridge
      // happened to be reconnecting — on a host that sleeps, most of them. The
      // API decides from the message's own age instead; genuine history
      // backfill never reaches here at all (it arrives on
      // "messaging-history.set" and is posted to /bridge-history).
      if (event.type !== "notify" && event.type !== "append") return;
      const synced = event.type === "append";
      for (const message of event.messages) {
        await this.handleInbound(sessionId, message, { synced });
      }
    });

    return sock;
  }

  async handleInbound(sessionId, message, { synced = false } = {}) {
    const jid = message.key?.remoteJid || "";
    const isLidChat = jid.endsWith(LID_CHAT_SUFFIX);
    if (!jid.endsWith(DIRECT_CHAT_SUFFIX) && !isLidChat) return; // groups, status, broadcasts

    // A LID is an opaque per-contact identifier, not a phone number — parsing
    // it the way a normal @s.whatsapp.net JID is parsed would produce a
    // number that means nothing (and can never match a campaign recipient,
    // since everything else in this app keys a contact by E.164 phone).
    // Baileys carries the real number alongside as `key.senderPn` for exactly
    // this case. If it isn't present yet, there is no correct number to file
    // this under, so the message is dropped rather than filed under a fake one.
    const phoneJid = isLidChat ? message.key?.senderPn || "" : jid;
    if (!phoneJid) return;

    // Messages the operator sent from the phone itself echo back here. They are
    // reported (so the inbox agrees with what WhatsApp shows) but marked
    // outbound, which is what stops the assistant answering its own words.
    const outbound = Boolean(message.key?.fromMe);

    const text = extractText(message);
    const media = describeMedia(message);
    // Reactions, receipts and protocol messages carry neither — nothing to show.
    if (!text && !media) return;

    const payload = {
      from: jidToPhone(phoneJid),
      // The original jid, not phoneJid: replies must address the same chat
      // WhatsApp is actually routing this contact through (their LID, if
      // that's what arrived), not a phone-number address that may not work.
      jid,
      text,
      direction: outbound ? "out" : "in",
      message_id: message.key?.id || "",
      pushname: message.pushName || "",
      preview: previewFor(text, media),
      // Baileys stamps a message "append" purely from `node.attrs.offline` —
      // i.e. WhatsApp queued it while this socket was down and flushed it on
      // reconnect. That is a live, unanswered message, NOT a history backfill
      // (real backfill arrives via `messaging-history.set` and never reaches
      // this handler). So `synced` is reported as a hint only; the API decides
      // whether to answer from `timestamp`, because treating it as a veto
      // silently dropped every reply that landed during a reconnect.
      synced,
      // Unix seconds. Lets the API skip a genuinely stale message without
      // muting a fresh one that merely arrived late.
      timestamp: messageTimestamp(message),
    };

    if (media) {
      payload.media_kind = media.kind;
      payload.media_mime_type = media.mime_type;
      payload.media_filename = media.filename;
      payload.media_size_bytes = media.size_bytes;

      const result = await this.fetchMediaFn(message, media, {
        logger,
        maxBytes: MAX_MEDIA_BYTES(),
      });
      if (result.buffer) {
        // Uploaded before the event is reported, so the API can attach the
        // storage key to the message row in one write rather than patching it
        // afterwards and racing the assistant's reply.
        const key = await this.uploadMedia(sessionId, payload.message_id, media, result.buffer);
        if (key) payload.media_storage_key = key;
        else payload.media_error = "upload failed";
      } else {
        payload.media_error = result.skipped;
        logger.warn({ sessionId, reason: result.skipped }, "media not stored");
      }
    }

    await this.notify(sessionId, "message", payload);
  }

  /**
   * Push one chunk of synced history to the API.
   *
   * Never throws: history is a bonus on top of a working live feed, and a
   * failed import must not take down the socket that is delivering today's
   * messages.
   */
  async importHistory(sessionId, { contacts = [], messages = [], progress, isLatest } = {}) {
    if (!this.syncHistoryFn) return;
    try {
      const contactRows = toContactRows(contacts);
      const messageRows = toMessageRows(messages, describeMedia, extractText);
      if (!contactRows.length && !messageRows.length) return;

      logger.info(
        { sessionId, contacts: contactRows.length, messages: messageRows.length, progress },
        "importing whatsapp history",
      );

      for (const batch of chunk(contactRows, CHUNK_SIZES.CONTACT_CHUNK)) {
        await this.syncHistoryFn(sessionId, { contacts: batch });
      }
      for (const batch of chunk(messageRows, CHUNK_SIZES.MESSAGE_CHUNK)) {
        await this.syncHistoryFn(sessionId, { messages: batch });
      }
      if (isLatest) logger.info({ sessionId }, "whatsapp history sync complete");
    } catch (err) {
      logger.error({ sessionId, err: err.message }, "history import failed");
    }
  }

  /** Hand media bytes to the API, which owns the storage backend (R2 or disk).
   * Returns the storage key, or null when the upload could not be completed. */
  async uploadMedia(sessionId, messageId, media, buffer) {
    if (!this.uploadMediaFn) return null;
    try {
      return await this.uploadMediaFn(sessionId, messageId, media, buffer);
    } catch (err) {
      logger.error({ sessionId, err: err.message }, "media upload failed");
      return null;
    }
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

  /**
   * Resolve the address to actually send to, and confirm someone is there.
   *
   * WhatsApp accepts a send to any well-formed JID without complaint — a
   * number that was never registered, or one mistyped into a campaign's
   * contact list, returns exactly the same success as a real delivery. That
   * silence is the worst possible failure mode for a broadcast tool: the
   * campaign reports "sent", the operator waits for a reply, and the message
   * never existed. `onWhatsApp` is a USync lookup that answers whether the
   * number is registered, and hands back the canonical JID (including the
   * @lid form) to address it by.
   *
   * Fails open on a lookup *error* — a USync timeout must not block a real
   * send — but closed on a definitive "not registered", which is the case
   * worth catching.
   */
  async resolveJid(sessionId, toJid) {
    const entry = this.sockets.get(sessionId);
    if (!entry) throw new Error("This WhatsApp session isn't connected.");
    // A @lid address is already canonical and came from a live conversation,
    // so there is nothing to look up and nobody to doubt.
    if (!String(toJid).endsWith("@s.whatsapp.net")) return { jid: toJid };

    let results;
    try {
      results = await entry.sock.onWhatsApp(toJid);
    } catch (err) {
      logger.warn({ sessionId, err: err.message }, "number check failed, sending anyway");
      return { jid: toJid };
    }
    // `undefined` means the query itself produced nothing usable (offline,
    // rate limited) — treated as inconclusive rather than as a rejection.
    if (!results) return { jid: toJid };

    const match = results.find((r) => r.exists);
    if (!match) return { jid: toJid, registered: false };
    return { jid: match.jid || toJid, registered: true };
  }

  /** Throws a message an operator can act on when the number isn't reachable. */
  async #addressFor(sessionId, toJid) {
    const resolved = await this.resolveJid(sessionId, toJid);
    if (resolved.registered === false) {
      throw new Error(
        `${jidToPhone(toJid)} isn't a WhatsApp account. Check the country code — ` +
          `a local number pasted without one is the usual cause.`,
      );
    }
    return resolved.jid;
  }

  async sendText(sessionId, toJid, text) {
    const entry = this.sockets.get(sessionId);
    if (!entry) throw new Error("This WhatsApp session isn't connected.");
    await entry.sock.sendMessage(await this.#addressFor(sessionId, toJid), { text });
  }

  async sendMedia(sessionId, toJid, kind, buffer, { mimeType, fileName, caption } = {}) {
    const entry = this.sockets.get(sessionId);
    if (!entry) throw new Error("This WhatsApp session isn't connected.");
    await entry.sock.sendMessage(
      await this.#addressFor(sessionId, toJid),
      buildMediaContent(kind, buffer, { mimeType, fileName, caption }),
    );
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
