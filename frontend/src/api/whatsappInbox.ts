// WhatsApp inbox — conversations and messages for a QR-linked personal number.
//
// Separate from `whatsappWeb.ts`, which is about linking a number rather than
// reading what arrives on it.
import { api } from "./client";

/** "in" from the contact, "out" from the assistant or a human operator. */
export type MessageDirection = "in" | "out";

/**
 * Who wrote a message.
 *
 * `assistant` is a generated answer, `operator` a reply typed in this inbox,
 * and `device` one typed on the linked phone itself. Worth distinguishing: the
 * point of attaching an agent to a number is being able to see that it is in
 * fact answering, and all three otherwise look identical in the thread.
 */
export type MessageAuthor = "contact" | "assistant" | "operator" | "device";

/** Empty for a plain text message. */
export type MediaKind = "" | "image" | "video" | "audio" | "document" | "sticker";

export type ThreadStatus = "open" | "closed";

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
  // --- Shared-inbox working state ---
  /** Null when nobody has picked the thread up — a state the rail filters on. */
  assignee_id: string | null;
  /** Resolved server-side; an id is not something a list can render. */
  assignee_email: string;
  tags: string[];
  pinned: boolean;
  status: ThreadStatus;
  // --- Contact card. Everything WhatsApp does not tell us. ---
  company: string;
  job_title: string;
  email: string;
  city: string;
  country: string;
  linkedin_url: string;
  source: string;
}

/** Fields a client may write back. Everything optional — each gesture in the
 * inbox sends only what it changed, so two people working the same thread
 * cannot clobber each other's unrelated edits. */
export interface ConversationPatch {
  auto_reply?: boolean;
  mark_read?: boolean;
  assignee_id?: string;
  /** Send with no `assignee_id` to actually clear the owner — "absent" and
   * "null" would otherwise be indistinguishable over JSON. */
  unassign?: boolean;
  tags?: string[];
  pinned?: boolean;
  status?: ThreadStatus;
  company?: string;
  job_title?: string;
  email?: string;
  city?: string;
  country?: string;
  linkedin_url?: string;
  source?: string;
  display_name?: string;
}

/** An internal note. Never sent to the contact — see the backend for why it is
 * not a message. */
export interface ConversationNote {
  id: string;
  body: string;
  author_email: string;
  created_at: string;
}

export interface InboxStats {
  connected_numbers: number;
  conversations: number;
  active_conversations: number;
  unread: number;
  messages_sent: number;
  messages_received: number;
  delivery_rate: number;
  read_rate: number;
  reply_rate: number;
  active_campaigns: number;
  period_label: string;
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
  author: MessageAuthor;
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
  /** Resolved from the caller's token server-side, so "mine" always means the
   * person looking. */
  assignedToMe?: boolean;
  unassigned?: boolean;
  status?: ThreadStatus;
  pinned?: boolean;
  tag?: string;
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
  if (filters.assignedToMe) params.set("assigned_to_me", "true");
  if (filters.unassigned) params.set("unassigned", "true");
  if (filters.status) params.set("status", filters.status);
  if (filters.pinned !== undefined) params.set("pinned", String(filters.pinned));
  if (filters.tag) params.set("tag", filters.tag);
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

/** Send a file as the operator, with an optional caption. Personal/QR-linked
 * numbers only — see the backend endpoint for why Twilio numbers can't yet. */
export function sendAttachment(
  conversationId: string,
  file: File,
  caption: string,
): Promise<InboxMessage> {
  const form = new FormData();
  form.append("file", file);
  form.append("caption", caption);
  return api.postForm<InboxMessage>(
    `/whatsapp-web/conversations/${conversationId}/attachments`,
    form,
  );
}

/** The one write for everything about a thread that isn't a message. */
export function updateConversation(
  conversationId: string,
  patch: ConversationPatch,
): Promise<InboxConversation> {
  return api.patch<InboxConversation>(`/whatsapp-web/conversations/${conversationId}`, patch);
}

/** Hand the conversation to a human (false) or back to the assistant (true). */
export function setAutoReply(
  conversationId: string,
  autoReply: boolean,
): Promise<InboxConversation> {
  return updateConversation(conversationId, { auto_reply: autoReply });
}

export function markRead(conversationId: string): Promise<InboxConversation> {
  return updateConversation(conversationId, { mark_read: true });
}

export function assignConversation(
  conversationId: string,
  userId: string | null,
): Promise<InboxConversation> {
  return updateConversation(
    conversationId,
    userId ? { assignee_id: userId } : { unassign: true },
  );
}

// --- Internal notes ---------------------------------------------------------

export function listNotes(conversationId: string): Promise<ConversationNote[]> {
  return api.get<ConversationNote[]>(`/whatsapp-web/conversations/${conversationId}/notes`);
}

export function addNote(conversationId: string, body: string): Promise<ConversationNote> {
  return api.post<ConversationNote>(`/whatsapp-web/conversations/${conversationId}/notes`, {
    body,
  });
}

export function deleteNote(conversationId: string, noteId: string): Promise<void> {
  return api.delete<void>(
    `/whatsapp-web/conversations/${conversationId}/notes/${noteId}`,
  );
}

/** Workspace-wide counters for the inbox header — not scoped to one number, so
 * switching numbers doesn't make the header jump. */
export function getInboxStats(): Promise<InboxStats> {
  return api.get<InboxStats>("/whatsapp-web/stats");
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
