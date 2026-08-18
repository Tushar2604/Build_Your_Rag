// Tests for the pure parts of the session manager: what gets turned into a
// reply-worthy event and what gets dropped.
//
// The filtering here is load-bearing. Auto-replying into a group chat, or to
// our own echoed messages, is both embarrassing and the fastest way to get a
// personal number reported — so each exclusion has its own test.

import test from "node:test";
import assert from "node:assert/strict";

import { SessionManager, extractText, jidToPhone } from "../src/sessions.js";

const SESSION = "11111111-1111-1111-1111-111111111111";
const DIRECT = "917502163963@s.whatsapp.net";
const GROUP = "120363000000000000@g.us";
const LID = "138078937182420@lid";

/** A manager that records notifications instead of making network calls. */
function harness({ uploadMedia, fetchMedia } = {}) {
  const events = [];
  const manager = new SessionManager({
    pool: { query: async () => ({ rows: [] }) },
    notify: async (sessionId, event, payload) => {
      events.push({ sessionId, event, payload });
    },
    // Defaults to "storage unavailable" so tests that do not care about media
    // still exercise the graceful path rather than a network call.
    uploadMedia,
    // The real one reaches WhatsApp's CDN. Default to a successful tiny
    // download so tests exercise the surrounding logic, and let the size-cap
    // test fall through to the real implementation's guard.
    fetchMedia: fetchMedia || (async (_msg, media, opts) =>
      media.size_bytes > (opts?.maxBytes ?? Infinity)
        ? { skipped: `too large (${Math.round(media.size_bytes / 1024 / 1024)}MB)` }
        : { buffer: Buffer.from("stub-bytes") }),
  });
  return { manager, events };
}

function inbound(overrides = {}) {
  return {
    key: { remoteJid: DIRECT, fromMe: false, id: "MSG1", ...(overrides.key || {}) },
    message: overrides.message ?? { conversation: "Hello there" },
    pushName: overrides.pushName ?? "Yacoob",
  };
}

// --- jidToPhone ---

test("jidToPhone strips the device suffix and adds a plus", () => {
  assert.equal(jidToPhone("917502163963:12@s.whatsapp.net"), "+917502163963");
  assert.equal(jidToPhone("971553752665@s.whatsapp.net"), "+971553752665");
});

test("jidToPhone keeps an existing plus and tolerates empty input", () => {
  assert.equal(jidToPhone("+14155238886@s.whatsapp.net"), "+14155238886");
  assert.equal(jidToPhone(""), "");
  assert.equal(jidToPhone(undefined), "");
});

// --- extractText ---

test("extractText reads every common message shape", () => {
  assert.equal(extractText({ message: { conversation: "plain" } }), "plain");
  assert.equal(extractText({ message: { extendedTextMessage: { text: "reply" } } }), "reply");
  assert.equal(extractText({ message: { imageMessage: { caption: "photo" } } }), "photo");
  assert.equal(
    extractText({ message: { buttonsResponseMessage: { selectedDisplayText: "Yes" } } }),
    "Yes",
  );
  assert.equal(extractText({ message: { listResponseMessage: { title: "Option A" } } }), "Option A");
});

test("extractText trims and returns empty for unsupported payloads", () => {
  assert.equal(extractText({ message: { conversation: "  spaced  " } }), "spaced");
  assert.equal(extractText({ message: { audioMessage: {} } }), "");
  assert.equal(extractText({ message: {} }), "");
  assert.equal(extractText({}), "");
});

// --- Inbound filtering ---

test("a direct text message is forwarded to the API", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound());

  assert.equal(events.length, 1);
  const [{ event, payload }] = events;
  assert.equal(event, "message");
  assert.equal(payload.text, "Hello there");
  assert.equal(payload.from, "+917502163963");
  assert.equal(payload.jid, DIRECT);
  assert.equal(payload.pushname, "Yacoob");
});

test("our own messages are reported as outbound, not dropped", async () => {
  // The inbox has to agree with what WhatsApp shows on the phone, so a reply
  // typed there must appear in the thread. `direction` is what keeps the
  // assistant from answering its own words — see the API side.
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ key: { fromMe: true } }));
  assert.equal(events.length, 1);
  assert.equal(events[0].payload.direction, "out");
});

test("messages from the contact are reported as inbound", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound());
  assert.equal(events[0].payload.direction, "in");
});

test("group messages are dropped", async () => {
  // Auto-replying into a group is how a number gets reported.
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ key: { remoteJid: GROUP } }));
  assert.equal(events.length, 0);
});

test("a @lid-addressed contact is forwarded, keyed by their real phone number", async () => {
  // WhatsApp's phone-number-privacy rollout routes some direct chats through
  // an opaque @lid address instead of the number. It's still a real 1:1 chat
  // — previously indistinguishable here from a group and silently dropped —
  // and Baileys carries the actual number separately as `key.senderPn`.
  const { manager, events } = harness();
  await manager.handleInbound(
    SESSION,
    inbound({ key: { remoteJid: LID, senderPn: DIRECT } }),
  );
  assert.equal(events.length, 1);
  const { payload } = events[0];
  assert.equal(payload.from, "+917502163963", "filed under the real number, not the LID");
  assert.equal(payload.jid, LID, "still addressed to the LID for the reply to reach the same chat");
});

test("a @lid message with no resolved phone number is dropped, not filed under a fake one", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ key: { remoteJid: LID } }));
  assert.equal(events.length, 0);
});

test("status broadcasts are dropped", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(
    SESSION,
    inbound({ key: { remoteJid: "status@broadcast" } }),
  );
  assert.equal(events.length, 0);
});

test("media with no caption is captured, not dropped", async () => {
  // Previously this returned early, so a customer sending a photo was invisible
  // end to end. The inbox needs it, and needs a label to show in the list.
  const { manager, events } = harness();
  await manager.handleInbound(
    SESSION,
    inbound({ message: { audioMessage: { mimetype: "audio/ogg", fileLength: 2048 } } }),
  );
  assert.equal(events.length, 1);
  const { payload } = events[0];
  assert.equal(payload.media_kind, "audio");
  assert.equal(payload.media_mime_type, "audio/ogg");
  assert.equal(payload.text, "");
  assert.equal(payload.preview, "Voice message");
});

test("an image caption becomes the message text and the preview", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(
    SESSION,
    inbound({ message: { imageMessage: { caption: "my invoice", mimetype: "image/jpeg" } } }),
  );
  const { payload } = events[0];
  assert.equal(payload.media_kind, "image");
  assert.equal(payload.text, "my invoice");
  assert.equal(payload.preview, "my invoice");
});

test("oversized media is recorded without its bytes", async () => {
  // Losing the file is bad; losing the fact that a customer sent something is
  // worse. The message still arrives, flagged with why the file is missing.
  const { manager, events } = harness();
  await manager.handleInbound(
    SESSION,
    inbound({
      message: { videoMessage: { mimetype: "video/mp4", fileLength: 500 * 1024 * 1024 } },
    }),
  );
  assert.equal(events.length, 1);
  assert.equal(events[0].payload.media_kind, "video");
  assert.match(events[0].payload.media_error, /too large/);
  assert.equal(events[0].payload.media_storage_key, undefined);
});

test("a stored attachment carries its storage key", async () => {
  const { manager, events } = harness({
    uploadMedia: async () => "whatsapp/session/MSG1",
  });
  await manager.handleInbound(
    SESSION,
    inbound({ message: { documentMessage: { mimetype: "application/pdf", fileName: "x.pdf" } } }),
  );
  assert.equal(events[0].payload.media_storage_key, "whatsapp/session/MSG1");
  assert.equal(events[0].payload.media_filename, "x.pdf");
});

test("reactions and receipts are still dropped", async () => {
  // No text and no media means there is nothing to show in a thread.
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ message: { reactionMessage: {} } }));
  assert.equal(events.length, 0);
});

test("a whitespace-only message is dropped", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ message: { conversation: "   " } }));
  assert.equal(events.length, 0);
});

// --- Reconnect backoff ---

test("reconnect delay grows and is capped", async () => {
  // A tight reconnect loop against WhatsApp reads as abuse.
  const { manager } = harness();
  const delays = [];
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms) => {
    delays.push(ms);
    return realSetTimeout(() => {}, 0);
  };
  try {
    for (let i = 0; i < 8; i += 1) manager.scheduleReconnect(SESSION);
  } finally {
    globalThis.setTimeout = realSetTimeout;
  }

  assert.equal(delays[0], 2000);
  assert.equal(delays[1], 4000);
  assert.equal(delays[2], 8000);
  for (let i = 1; i < delays.length; i += 1) {
    assert.ok(delays[i] >= delays[i - 1], "delay must never shrink");
  }
  assert.ok(Math.max(...delays) <= 60000, "delay must be capped at 60s");
  manager.clearTimer(SESSION);
});

test("stopping an unknown session is a no-op", async () => {
  const { manager } = harness();
  await manager.stop("does-not-exist", { keepAuth: true });
  assert.equal(manager.has("does-not-exist"), false);
});

test("sending on a session with no socket fails loudly", async () => {
  const { manager } = harness();
  await assert.rejects(
    () => manager.sendText(SESSION, DIRECT, "hi"),
    /isn't connected/,
  );
});
