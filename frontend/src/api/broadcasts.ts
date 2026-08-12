import { api } from "./client";

export type BroadcastStatus = "queued" | "sending" | "paused" | "completed";

/** broadcast = announce only (replies recorded, not answered).
 *  broadcast_reply = the assistant picks up the conversation. */
export type BroadcastMode = "broadcast" | "broadcast_reply";

/** cloud_api = a Twilio/Cloud API business number.
 *  personal  = a QR-linked personal WhatsApp ("Phone WhatsApp"). */
export type SenderKind = "cloud_api" | "personal";

/** One WhatsApp number a campaign can send from. */
export interface CampaignSender {
  id: string;
  kind: SenderKind;
  label: string;
  phone_number: string;
  /** False when it exists but cannot send right now — see the reason. */
  available: boolean;
  unavailable_reason: string;
  chatbot_id: string | null;
  chatbot_name: string;
}

export type RecipientStatus =
  | "pending"
  | "sent"
  | "delivered"
  | "read"
  | "replied"
  | "failed";

export interface Broadcast {
  id: string;
  chatbot_id: string;
  chatbot_name: string;
  whatsapp_channel_id: string | null;
  whatsapp_session_id: string | null;
  sender_kind: SenderKind;
  mode: BroadcastMode;
  from_number: string;
  name: string;
  message_template: string;
  status: BroadcastStatus;
  total_count: number;
  /** Funnel counters are cumulative: a `read` contact also counts as sent. */
  sent_count: number;
  delivered_count: number;
  read_count: number;
  replied_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
}

export interface BroadcastRecipient {
  id: string;
  phone_number: string;
  display_name: string;
  status: RecipientStatus;
  error: string;
  session_id: string | null;
  attempts: number;
  updated_at: string;
}

export interface RecipientPage {
  recipients: BroadcastRecipient[];
  total: number;
  page: number;
  page_size: number;
}

export interface BroadcastMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface AddRecipientsResult {
  added: number;
  duplicates: number;
  /** Rows that couldn't be normalized to E.164 — surfaced, never dropped. */
  invalid: string[];
}

export interface PreviewedContact {
  phone_number: string;
  display_name: string;
}

export interface ContactPreview {
  contacts: PreviewedContact[];
  /** Lines that could not be read as a number, verbatim. */
  invalid: string[];
  duplicates: string[];
  total_valid: number;
  truncated: boolean;
}

/** Parse a contact blob without saving it, so a bad file is caught in the
 * editor rather than discovered as a short send. */
export function previewContacts(recipientsText: string): Promise<ContactPreview> {
  return api.post<ContactPreview>("/broadcasts/preview-contacts", {
    recipients_text: recipientsText,
  });
}

export interface CreateBroadcastInput {
  chatbot_id: string;
  name: string;
  message_template: string;
  recipients_text?: string;
  mode?: BroadcastMode;
  /** Omit both to fall back to the number already bound to the assistant. */
  sender_kind?: SenderKind;
  sender_id?: string;
}

/** Every WhatsApp number this workspace can send a campaign from. */
export function listCampaignSenders(): Promise<CampaignSender[]> {
  return api.get<CampaignSender[]>("/broadcasts/senders");
}

export function listBroadcasts(): Promise<Broadcast[]> {
  return api.get<Broadcast[]>("/broadcasts");
}

export function getBroadcast(id: string): Promise<Broadcast> {
  return api.get<Broadcast>(`/broadcasts/${id}`);
}

export function createBroadcast(input: CreateBroadcastInput): Promise<Broadcast> {
  return api.post<Broadcast>("/broadcasts", input);
}

export function deleteBroadcast(id: string): Promise<void> {
  return api.delete<void>(`/broadcasts/${id}`);
}

export function addRecipients(
  id: string,
  recipientsText: string,
): Promise<AddRecipientsResult> {
  return api.post<AddRecipientsResult>(`/broadcasts/${id}/recipients`, {
    recipients_text: recipientsText,
  });
}

export function listRecipients(
  id: string,
  opts: { status?: RecipientStatus | null; search?: string; page?: number; pageSize?: number } = {},
): Promise<RecipientPage> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.search?.trim()) params.set("search", opts.search.trim());
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 25));
  return api.get<RecipientPage>(`/broadcasts/${id}/recipients?${params}`);
}

export function startBroadcast(id: string): Promise<Broadcast> {
  return api.post<Broadcast>(`/broadcasts/${id}/start`);
}

export function pauseBroadcast(id: string): Promise<Broadcast> {
  return api.post<Broadcast>(`/broadcasts/${id}/pause`);
}

export function completeBroadcast(id: string): Promise<Broadcast> {
  return api.post<Broadcast>(`/broadcasts/${id}/complete`);
}

export function retryFailed(id: string): Promise<Broadcast> {
  return api.post<Broadcast>(`/broadcasts/${id}/retry-failed`);
}

export function listRecipientMessages(
  broadcastId: string,
  recipientId: string,
): Promise<BroadcastMessage[]> {
  return api.get<BroadcastMessage[]>(
    `/broadcasts/${broadcastId}/recipients/${recipientId}/messages`,
  );
}

/** Human takeover — sends as the assistant, bypassing the RAG pipeline. */
export function sendManualMessage(
  broadcastId: string,
  recipientId: string,
  message: string,
): Promise<BroadcastMessage> {
  return api.post<BroadcastMessage>(
    `/broadcasts/${broadcastId}/recipients/${recipientId}/messages`,
    { message },
  );
}
