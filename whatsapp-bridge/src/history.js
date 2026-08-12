// Importing the history WhatsApp hands a newly linked device.
//
// Worth being clear about the ceiling: this is not "every message you have ever
// sent". When a device links, the phone pushes a bounded slice of history —
// `syncFullHistory` widens it from days to months, but anything older stays on
// the phone and no amount of asking retrieves it. What comes across reliably is
// the contact directory, which is the part that answers "what number do I use
// for the printer".

// Chunked so a large sync does not build one enormous request body. The API
// upserts each batch independently, so a failed chunk costs that chunk only.
const CONTACT_CHUNK = 400;
const MESSAGE_CHUNK = 200;

const DIRECT_CHAT_SUFFIX = "@s.whatsapp.net";

/** Strip a JID to its E.164 number, or "" when it is not a direct chat. */
export function directPhone(jid) {
  if (!jid || !String(jid).endsWith(DIRECT_CHAT_SUFFIX)) return "";
  const bare = String(jid).split(":")[0].split("@")[0];
  if (!/^\d{6,16}$/.test(bare)) return "";
  return `+${bare}`;
}

/**
 * Reduce a synced contact list to the entries worth storing.
 *
 * Contacts with no name are dropped: a bare number the user never labelled adds
 * a row to search through without making anything findable.
 */
export function toContactRows(contacts = []) {
  const seen = new Map();
  for (const contact of contacts) {
    const phone = directPhone(contact?.id);
    if (!phone) continue;
    const name = (contact.name || contact.notify || contact.verifiedName || "").trim();
    if (!name) continue;
    // A pushname is what the contact calls themselves; a saved name is what the
    // user calls them, and is the one they will search by.
    if (!seen.has(phone) || contact.name) seen.set(phone, name);
  }
  return [...seen.entries()].map(([phone, name]) => ({ phone, name }));
}

/**
 * Reduce synced messages to direct-chat rows the inbox can show.
 *
 * `describe` is the same classifier the live path uses, so a historical photo is
 * labelled exactly like a new one. History media is deliberately not downloaded:
 * WhatsApp expires it server-side, so most fetches would fail slowly and the
 * rest would pull megabytes for messages nobody asked to see.
 */
export function toMessageRows(messages = [], describe, extract) {
  const rows = [];
  for (const message of messages) {
    const phone = directPhone(message?.key?.remoteJid);
    if (!phone) continue; // groups, status, broadcasts

    const media = describe(message);
    const text = extract(message);
    if (!text && !media) continue; // receipts, reactions, protocol noise

    const seconds = Number(
      message.messageTimestamp?.low ?? message.messageTimestamp ?? 0,
    );
    rows.push({
      phone,
      text,
      // Real timestamps, not import time — otherwise every thread claims its
      // whole history arrived in the same second and ordering is meaningless.
      timestamp: seconds ? new Date(seconds * 1000).toISOString() : null,
      direction: message.key?.fromMe ? "out" : "in",
      message_id: message.key?.id || "",
      pushname: message.pushName || "",
      media_kind: media?.kind || "",
      media_mime_type: media?.mime_type || "",
      media_filename: media?.filename || "",
      media_size_bytes: media?.size_bytes || 0,
      preview: text || media?.label || "",
    });
  }
  return rows;
}

export function chunk(items, size) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export const CHUNK_SIZES = { CONTACT_CHUNK, MESSAGE_CHUNK };
