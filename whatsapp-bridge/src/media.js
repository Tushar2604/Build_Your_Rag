// Classifying and fetching WhatsApp media.
//
// Split out from sessions.js because it is the piece with real decisions in it
// — which message shapes count as media, what a caption-less image should look
// like to the inbox, and when a file is too big to be worth fetching — and
// those decisions are worth testing without a WhatsApp socket.

import { downloadMediaMessage, getContentType } from "@whiskeysockets/baileys";

// WhatsApp message keys mapped to the `kind` the inbox filters on. Anything not
// listed is treated as text (or ignored, if it carries no words at all).
const MEDIA_KINDS = {
  imageMessage: "image",
  videoMessage: "video",
  audioMessage: "audio",
  documentMessage: "document",
  stickerMessage: "sticker",
  // Sent as a document with a thumbnail by some clients; same handling.
  documentWithCaptionMessage: "document",
};

// Fetching a 200MB video into a 512MB container to show it in a thread list is
// a poor trade. Oversized media is recorded as a placeholder so the inbox still
// shows that something arrived, it just is not downloadable.
const DEFAULT_MAX_MEDIA_MB = 16;

/** Human label for a media message that carried no caption, so the thread list
 * shows "Photo" rather than a blank row. */
const KIND_LABELS = {
  image: "Photo",
  video: "Video",
  audio: "Voice message",
  document: "Document",
  sticker: "Sticker",
};

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
    m.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    m.buttonsResponseMessage?.selectedDisplayText ||
    m.listResponseMessage?.title ||
    m.templateButtonReplyMessage?.selectedDisplayText ||
    ""
  ).trim();
}

/**
 * Describe a message's attachment, or null when it is plain text.
 *
 * Returns metadata only — the bytes are fetched separately by `fetchMedia`, so
 * a caller can record that an attachment exists even if downloading it fails.
 */
export function describeMedia(message) {
  const inner = message?.message;
  if (!inner) return null;
  const type = getContentType(inner);
  const kind = MEDIA_KINDS[type];
  if (!kind) return null;

  // documentWithCaptionMessage wraps the real document one level down.
  const node =
    type === "documentWithCaptionMessage"
      ? inner.documentWithCaptionMessage?.message?.documentMessage
      : inner[type];
  if (!node) return null;

  return {
    kind,
    mime_type: node.mimetype || "",
    filename: node.fileName || node.title || "",
    size_bytes: Number(node.fileLength || 0) || 0,
    label: KIND_LABELS[kind] || "Attachment",
  };
}

/** What the thread list shows for this message: its caption, or a kind label. */
export function previewFor(text, media) {
  if (text) return text;
  if (media) return media.label;
  return "";
}

/**
 * Download an attachment's bytes.
 *
 * Returns `{ buffer }` on success, or `{ skipped }` with a reason — never
 * throws. A message whose media cannot be fetched is still worth recording:
 * losing the file is bad, losing the fact that a customer sent something is
 * worse.
 */
export async function fetchMedia(message, media, { logger, maxBytes } = {}) {
  const limit = maxBytes ?? DEFAULT_MAX_MEDIA_MB * 1024 * 1024;
  if (media.size_bytes && media.size_bytes > limit) {
    return { skipped: `too large (${Math.round(media.size_bytes / 1024 / 1024)}MB)` };
  }
  try {
    const buffer = await downloadMediaMessage(message, "buffer", {}, { logger });
    if (!buffer?.length) return { skipped: "empty download" };
    if (buffer.length > limit) {
      return { skipped: `too large (${Math.round(buffer.length / 1024 / 1024)}MB)` };
    }
    return { buffer };
  } catch (err) {
    return { skipped: err.message || "download failed" };
  }
}

export const MAX_MEDIA_BYTES = () =>
  Number(process.env.BRIDGE_MAX_MEDIA_MB || DEFAULT_MAX_MEDIA_MB) * 1024 * 1024;

/**
 * Build the Baileys `sendMessage` content for an outbound attachment.
 *
 * Baileys discriminates the message type by which key is present (`image`,
 * `video`, `document`, ...), not by a separate type field, so this is just
 * picking the right shape for the kind the API already classified the file
 * as. Anything not recognised as image/video/audio falls back to `document`
 * — WhatsApp renders that as a generic downloadable file, which is always a
 * safe default.
 */
export function buildMediaContent(kind, buffer, { mimeType, fileName, caption } = {}) {
  const base = caption ? { caption } : {};
  if (kind === "image") return { image: buffer, mimetype: mimeType, ...base };
  if (kind === "video") return { video: buffer, mimetype: mimeType, ...base };
  if (kind === "audio") return { audio: buffer, mimetype: mimeType, ptt: false };
  return {
    document: buffer,
    mimetype: mimeType || "application/octet-stream",
    fileName: fileName || "file",
    ...base,
  };
}
