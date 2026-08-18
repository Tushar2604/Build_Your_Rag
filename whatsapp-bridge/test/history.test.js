// Tests for the history importer's filtering and shaping.
//
// The decisions worth pinning down: what counts as a direct chat, which
// contacts are worth storing, and that a message's real timestamp survives —
// an import that stamps everything with "now" destroys thread ordering, which
// is the thing an inbox is for.

import test from "node:test";
import assert from "node:assert/strict";

import { chunk, directPhone, toContactRows, toMessageRows } from "../src/history.js";
import { describeMedia, extractText } from "../src/media.js";

test("directPhone accepts direct chats and rejects everything else", () => {
  assert.equal(directPhone("917502163963@s.whatsapp.net"), "+917502163963");
  assert.equal(directPhone("917502163963:12@s.whatsapp.net"), "+917502163963");
  assert.equal(directPhone("120363000000000000@g.us"), "", "group");
  assert.equal(directPhone("status@broadcast"), "", "status");
  assert.equal(directPhone(""), "");
  assert.equal(directPhone(undefined), "");
});

test("directPhone resolves a @lid chat from its phone-number alt", () => {
  assert.equal(
    directPhone("138078937182420@lid", "917502163963@s.whatsapp.net"),
    "+917502163963",
    "a LID chat with a known phone alt resolves to that number",
  );
  assert.equal(
    directPhone("138078937182420@lid"),
    "",
    "a LID chat with no phone alt yet is skipped, not parsed as a fake number",
  );
  assert.equal(
    directPhone("138078937182420@lid", ""),
    "",
    "an empty phone alt is treated the same as a missing one",
  );
});

test("contacts keep the saved name in preference to a pushname", () => {
  const rows = toContactRows([
    { id: "917502163963@s.whatsapp.net", notify: "self-chosen" },
    { id: "917502163963@s.whatsapp.net", name: "Speedy Printers" },
  ]);
  assert.deepEqual(rows, [{ phone: "+917502163963", name: "Speedy Printers" }]);
});

test("a LID-addressed contact resolves via its jid alt", () => {
  const rows = toContactRows([
    { id: "138078937182420@lid", jid: "917502163963@s.whatsapp.net", name: "Speedy Printers" },
  ]);
  assert.deepEqual(rows, [{ phone: "+917502163963", name: "Speedy Printers" }]);
});

test("unnamed contacts are skipped", () => {
  // A bare number the user never labelled adds a row to search through without
  // making anything findable.
  const rows = toContactRows([
    { id: "919999999999@s.whatsapp.net" },
    { id: "120363000000000000@g.us", name: "Some Group" },
  ]);
  assert.deepEqual(rows, []);
});

test("message rows preserve the original timestamp", () => {
  const rows = toMessageRows(
    [
      {
        key: { remoteJid: "917502163963@s.whatsapp.net", fromMe: false, id: "H1" },
        message: { conversation: "Do you print banners?" },
        messageTimestamp: 1700000000,
      },
    ],
    describeMedia,
    extractText,
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].timestamp, new Date(1700000000 * 1000).toISOString());
  assert.equal(rows[0].direction, "in");
  assert.equal(rows[0].preview, "Do you print banners?");
});

test("outbound history keeps its direction", () => {
  const rows = toMessageRows(
    [
      {
        key: { remoteJid: "917502163963@s.whatsapp.net", fromMe: true, id: "H2" },
        message: { conversation: "Yes, A0 and A1." },
        messageTimestamp: { low: 1700000100 },
      },
    ],
    describeMedia,
    extractText,
  );
  assert.equal(rows[0].direction, "out");
});

test("a LID-addressed message resolves via its senderPn alt", () => {
  const rows = toMessageRows(
    [
      {
        key: {
          remoteJid: "138078937182420@lid",
          senderPn: "917502163963@s.whatsapp.net",
          fromMe: false,
          id: "H4",
        },
        message: { conversation: "Still interested, thanks!" },
        messageTimestamp: 1700000300,
      },
    ],
    describeMedia,
    extractText,
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].phone, "+917502163963");
  assert.equal(rows[0].preview, "Still interested, thanks!");
});

test("group and empty messages are excluded from history", () => {
  const rows = toMessageRows(
    [
      {
        key: { remoteJid: "120363000000000000@g.us", id: "G1" },
        message: { conversation: "group chatter" },
      },
      { key: { remoteJid: "917502163963@s.whatsapp.net", id: "R1" }, message: {} },
    ],
    describeMedia,
    extractText,
  );
  assert.deepEqual(rows, []);
});

test("historical media is described but carries no storage key", () => {
  // WhatsApp expires media server-side, so old files are metadata only.
  const rows = toMessageRows(
    [
      {
        key: { remoteJid: "917502163963@s.whatsapp.net", id: "H3" },
        message: { imageMessage: { mimetype: "image/jpeg", fileLength: 900 } },
        messageTimestamp: 1700000200,
      },
    ],
    describeMedia,
    extractText,
  );
  assert.equal(rows[0].media_kind, "image");
  assert.equal(rows[0].preview, "Photo");
  assert.equal(rows[0].media_storage_key, undefined);
});

test("chunk splits evenly and keeps every item", () => {
  const items = Array.from({ length: 7 }, (_, i) => i);
  const batches = chunk(items, 3);
  assert.equal(batches.length, 3);
  assert.deepEqual(batches.flat(), items);
  assert.deepEqual(chunk([], 3), []);
});
