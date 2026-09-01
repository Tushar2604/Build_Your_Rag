import { api } from "./client";

/** Which vendor carries this number.
 *
 * `twilio` — Twilio's WhatsApp API, identified by the number itself.
 * `cloud`  — Meta's WhatsApp Cloud API, identified by an opaque phone number ID.
 *
 * Everything after connecting is identical: the same inbox, the same assistant,
 * the same campaigns. Only connecting differs.
 */
export type WhatsAppProvider = "twilio" | "cloud";

export interface WhatsAppChannel {
  id: string;
  chatbot_id: string;
  chatbot_name: string;
  phone_number: string;
  provider: WhatsAppProvider;
  status: string;
  /** The callback URL to paste into the provider's console — already the right
   * one for this channel's provider. */
  webhook_url: string;
  /** Cloud only. The access token is never returned: it can be replaced, not read. */
  phone_number_id: string;
  /** Non-empty when the deployment itself is missing something (app secret,
   * verify token) and inbound messages will be refused until it is fixed. */
  setup_warning: string;
  created_at: string;
}

export interface ConnectWhatsAppInput {
  chatbot_id: string;
  phone_number: string;
  provider: WhatsAppProvider;
  /** Twilio only. */
  twilio_account_sid?: string;
  twilio_auth_token?: string;
  /** Cloud only. */
  phone_number_id?: string;
  waba_id?: string;
  access_token?: string;
}

export function listWhatsAppChannels(): Promise<WhatsAppChannel[]> {
  return api.get<WhatsAppChannel[]>("/whatsapp/channels");
}

export function connectWhatsAppChannel(input: ConnectWhatsAppInput): Promise<WhatsAppChannel> {
  return api.post<WhatsAppChannel>("/whatsapp/channels", input);
}

export function disconnectWhatsAppChannel(id: string): Promise<void> {
  return api.delete<void>(`/whatsapp/channels/${id}`);
}
