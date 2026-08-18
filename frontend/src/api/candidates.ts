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
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 30));
  return api.get<CandidatePage>(`/candidates?${params}`);
}
