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

/** A manager that records notifications instead of making network calls. */
function harness() {
  const events = [];
  const manager = new SessionManager({
    pool: { query: async () => ({ rows: [] }) },
    notify: async (sessionId, event, payload) => {
      events.push({ sessionId, event, payload });
    },
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

test("our own echoed messages are ignored", async () => {
  // Without this the assistant would reply to itself, forever.
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ key: { fromMe: true } }));
  assert.equal(events.length, 0);
});

test("group messages are dropped", async () => {
  // Auto-replying into a group is how a number gets reported.
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ key: { remoteJid: GROUP } }));
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

test("media with no caption is dropped rather than answered blindly", async () => {
  const { manager, events } = harness();
  await manager.handleInbound(SESSION, inbound({ message: { audioMessage: {} } }));
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
