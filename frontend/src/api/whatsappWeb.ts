import { api } from "./client";

export type WhatsAppWebStatus =
  | "pending"
  | "awaiting_scan"
  | "linked"
  | "disconnected"
  | "logged_out"
  | "failed";

export interface WhatsAppWebSession {
  id: string;
  chatbot_id: string | null;
  chatbot_name: string;
  status: WhatsAppWebStatus;
  phone_number: string;
  display_name: string;
  /** Empty unless a scan is pending AND the code is still valid. */
  qr_data_url: string;
  qr_seconds_remaining: number;
  last_error: string;
  /** Server-rendered status line, so copy isn't reinvented per surface. */
  health: string;
  linked_at: string | null;
  created_at: string;
}

export interface WhatsAppWebOptions {
  enabled: boolean;
  bridge_healthy: boolean;
  message: string;
}

export function getWhatsAppWebOptions(): Promise<WhatsAppWebOptions> {
  return api.get<WhatsAppWebOptions>("/whatsapp-web/options");
}

export function listWebSessions(): Promise<WhatsAppWebSession[]> {
  return api.get<WhatsAppWebSession[]>("/whatsapp-web/sessions");
}

/** Creates the session and starts pairing. The QR arrives via polling. */
export function createWebSession(): Promise<WhatsAppWebSession> {
  return api.post<WhatsAppWebSession>("/whatsapp-web/sessions");
}

export function getWebSession(id: string): Promise<WhatsAppWebSession> {
  return api.get<WhatsAppWebSession>(`/whatsapp-web/sessions/${id}`);
}

export function refreshWebSessionQr(id: string): Promise<WhatsAppWebSession> {
  return api.post<WhatsAppWebSession>(`/whatsapp-web/sessions/${id}/refresh`);
}

export function attachAssistant(
  id: string,
  chatbotId: string | null,
): Promise<WhatsAppWebSession> {
  return api.patch<WhatsAppWebSession>(`/whatsapp-web/sessions/${id}/assistant`, {
    chatbot_id: chatbotId,
  });
}

export function unlinkWebSession(id: string): Promise<void> {
  return api.delete<void>(`/whatsapp-web/sessions/${id}`);
}

export interface MergeDuplicatesResult {
  merged_sessions: number;
  moved_conversations: number;
}

/**
 * Fold numbers that were connected more than once back into a single entry.
 *
 * New duplicates are absorbed the moment a scan links (server-side), so this is
 * only for workspaces that already have them. Idempotent — with nothing to
 * merge it reports zeroes, which is what lets the page call it on load.
 */
export function mergeDuplicateNumbers(): Promise<MergeDuplicatesResult> {
  return api.post<MergeDuplicatesResult>("/whatsapp-web/sessions/merge-duplicates");
}
