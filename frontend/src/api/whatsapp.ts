import { api } from "./client";

export interface WhatsAppChannel {
  id: string;
  chatbot_id: string;
  chatbot_name: string;
  phone_number: string;
  status: string;
  webhook_url: string;
  created_at: string;
}

export interface ConnectWhatsAppInput {
  chatbot_id: string;
  phone_number: string;
  twilio_account_sid: string;
  twilio_auth_token: string;
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
