// Candidates — every WhatsApp contact across every connected number, in one
// tenant-wide, read-oriented list. The transcript and attachments for a given
// candidate are fetched through the existing `whatsappInbox` endpoints
// (`listMessages`, `mediaUrl`, ...): those are already scoped by tenant
// alone, not by which number the conversation happened to land on, so there
// was nothing to duplicate there — this module only adds the list.
import { api } from "./client";

export type ChannelKind = "cloud_api" | "personal";

export interface Candidate {
  id: string;
  phone_number: string;
  display_name: string;
  last_message_at: string | null;
  last_message_preview: string;
  unread_count: number;
  has_attachment: boolean;
  auto_reply: boolean;
  channel_kind: ChannelKind;
  channel_label: string;
  /** Only set for a "personal" (QR-linked) number — the only kind with a live
   * reply inbox today. Lets the profile view offer "keep replying" there. */
  session_id: string | null;
  message_count: number;
  document_count: number;
  /** How far down the follow-up ladder this contact is, and whether we are
   * currently waiting on them — see the backend's SendFollowUps. */
  followups_sent: number;
  awaiting_reply: boolean;
  /** Every conversation this person has, across every connected number. This
   * card represents the most recently active one. More than one entry means
   * they have talked to the workspace on two numbers — two real conversations
   * to switch between, not a duplicate. */
  threads: CandidateThread[];
}

export interface CandidateThread {
  conversation_id: string;
  /** The connected number that owns it. Null once that number is disconnected. */
  session_id: string | null;
  channel_kind: ChannelKind;
  channel_label: string;
  last_message_at: string | null;
  message_count: number;
  unread_count: number;
}

/** A number the Candidates list can be filtered by. Both kinds in one list —
 * picking "which WhatsApp number" is not a question about our implementation. */
export interface ConnectedNumber {
  id: string;
  kind: ChannelKind;
  phone_number: string;
  label: string;
  connected: boolean;
  contact_count: number;
}

export function listConnectedNumbers(): Promise<ConnectedNumber[]> {
  return api.get<ConnectedNumber[]>("/candidates/numbers");
}

export interface CandidatePage {
  candidates: Candidate[];
  total: number;
  page: number;
  page_size: number;
}

export interface CandidateFilters {
  search?: string;
  hasAttachment?: boolean;
  unreadOnly?: boolean;
  /** Narrow to one connected WhatsApp number — a linked session id or a Cloud
   * API channel id. Omit for every number. */
  numberId?: string;
  page?: number;
  pageSize?: number;
}

export function listCandidates(filters: CandidateFilters = {}): Promise<CandidatePage> {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.hasAttachment !== undefined) {
    params.set("has_attachment", String(filters.hasAttachment));
  }
  if (filters.unreadOnly) params.set("unread_only", "true");
  if (filters.numberId) params.set("number_id", filters.numberId);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 30));
  return api.get<CandidatePage>(`/candidates?${params}`);
}

/** One candidate, so their profile survives a refresh or a shared link. */
export function getCandidate(conversationId: string): Promise<Candidate> {
  return api.get<Candidate>(`/candidates/${conversationId}`);
}

// --- CRM export -------------------------------------------------------------
//
// The destination is a workspace-level setting (Integrations → "Your CRM
// (Webhook)"), not a per-candidate one, so the UI asks for it once per page
// and every card on that page shares the answer.

export interface CrmDestination {
  connected: boolean;
  /** Host only — the backend never returns the full URL, because the path of
   * a catch-hook URL is its credential. */
  endpoint_host: string;
  /** Where an admin goes to set it up. */
  settings_path: string;
}

export interface CrmExportResult {
  delivered: boolean;
  /** Confirmation on success; whatever the CRM said on failure. */
  message: string;
  endpoint_host: string;
}

export function getCrmDestination(): Promise<CrmDestination> {
  return api.get<CrmDestination>("/candidates/crm/destination");
}

/** Push one candidate's whole record to the workspace's CRM endpoint.
 * Resolves with the delivery outcome — a CRM that rejects the payload is news
 * to show the operator, not an exception to swallow. */
export function exportCandidateToCrm(conversationId: string): Promise<CrmExportResult> {
  return api.post<CrmExportResult>(`/candidates/${conversationId}/crm/export`, {});
}
