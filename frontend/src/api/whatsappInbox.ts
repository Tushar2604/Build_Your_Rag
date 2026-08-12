// WhatsApp inbox — conversations and messages for a QR-linked personal number.
//
// Separate from `whatsappWeb.ts`, which is about linking a number rather than
// reading what arrives on it.
import { api } from "./client";

/** "in" from the contact, "out" from the assistant or a human operator. */
export type MessageDirection = "in" | "out";

/** Empty for a plain text message. */
export type MediaKind = "" | "image" | "video" | "audio" | "document" | "sticker";

export interface InboxConversation {
  id: string;
  phone_number: string;
  display_name: string;
  last_message_at: string | null;
  last_message_preview: string;
  unread_count: number;
  has_attachment: boolean;
  /** False means a human has taken over and the assistant is staying quiet. */
  auto_reply: boolean;
}

export interface InboxConversationPage {
  conversations: InboxConversation[];
  total: number;
  page: number;
  page_size: number;
}

export interface InboxMessage {
  id: string;
  direction: MessageDirection;
  content: string;
  created_at: string;
  media_kind: MediaKind;
  media_mime_type: string;
  media_filename: string;
  media_size_bytes: number;
  /** False when WhatsApp delivered an attachment we could not store — the UI
   * says so rather than offering a download that would 404. */
  media_available: boolean;
}

export interface ConversationFilters {
  search?: string;
  hasAttachment?: boolean;
  unreadOnly?: boolean;
  /** false selects conversations a human has taken over. */
  autoReply?: boolean;
  page?: number;
  pageSize?: number;
}

export function listConversations(
  sessionId: string,
  filters: ConversationFilters = {},
): Promise<InboxConversationPage> {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.hasAttachment !== undefined) {
    params.set("has_attachment", String(filters.hasAttachment));
  }
  if (filters.unreadOnly) params.set("unread_only", "true");
  if (filters.autoReply !== undefined) params.set("auto_reply", String(filters.autoReply));
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 30));
  return api.get<InboxConversationPage>(
    `/whatsapp-web/sessions/${sessionId}/conversations?${params}`,
  );
}

export function listMessages(conversationId: string, limit = 100): Promise<InboxMessage[]> {
  return api.get<InboxMessage[]>(
    `/whatsapp-web/conversations/${conversationId}/messages?limit=${limit}`,
  );
}

/** Reply as the operator. The assistant keeps answering unless auto-reply is
 * turned off separately — see `setAutoReply`. */
export function sendMessage(conversationId: string, message: string): Promise<InboxMessage> {
  return api.post<InboxMessage>(`/whatsapp-web/conversations/${conversationId}/messages`, {
    message,
  });
}

/** Hand the conversation to a human (false) or back to the assistant (true). */
export function setAutoReply(
  conversationId: string,
  autoReply: boolean,
): Promise<InboxConversation> {
  return api.patch<InboxConversation>(`/whatsapp-web/conversations/${conversationId}`, {
    auto_reply: autoReply,
  });
}

export function markRead(conversationId: string): Promise<InboxConversation> {
  return api.patch<InboxConversation>(`/whatsapp-web/conversations/${conversationId}`, {
    mark_read: true,
  });
}

/**
 * URL for an attachment's bytes.
 *
 * Served through the API rather than as a storage link, so it carries the
 * caller's auth — which is also why it cannot be used directly in an `<img
 * src>`: the request would go out without the Authorization header. Fetch it
 * and turn it into an object URL instead (see `useAttachment`).
 */
export function mediaUrl(conversationId: string, messageId: string): string {
  return `/api/v1/whatsapp-web/conversations/${conversationId}/media/${messageId}`;
}

/**
 * Fetch an attachment as an object URL usable in `<img>` / `<a download>`.
 *
 * Callers must revoke the returned URL when the element goes away, or every
 * image scrolled past stays in memory for the life of the tab.
 */
export async function fetchMediaObjectUrl(
  conversationId: string,
  messageId: string,
): Promise<string> {
  const token = localStorage.getItem("access_token");
  const res = await fetch(mediaUrl(conversationId, messageId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Attachment unavailable");
  return URL.createObjectURL(await res.blob());
}
