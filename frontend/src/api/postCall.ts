import { api } from "./client";

export type CallStatus =
  | "completed"
  | "voicemail"
  | "no_answer"
  | "busy"
  | "failed";

export type DeliveryMethod = "webhook" | "email";

export const CALL_STATUSES: { value: CallStatus; label: string }[] = [
  { value: "completed", label: "Completed" },
  { value: "voicemail", label: "Voicemail Detected" },
  { value: "no_answer", label: "No Answer" },
  { value: "busy", label: "Busy" },
  { value: "failed", label: "Failed" },
];

export interface PostCallConfig {
  id: string;
  chatbot_id: string;
  delivery_method: DeliveryMethod;
  webhook_url: string;
  email_to: string;
  trigger_statuses: CallStatus[];
  include_summary: boolean;
  include_transcript: boolean;
  include_sentiment: boolean;
  include_extracted: boolean;
  enabled: boolean;
  created_at: string;
}

/** Create/update payload — the server validates the destination against the
 * chosen delivery method, so both fields are always sent. */
export interface PostCallConfigInput {
  delivery_method: DeliveryMethod;
  webhook_url: string;
  email_to: string;
  trigger_statuses: CallStatus[];
  include_summary: boolean;
  include_transcript: boolean;
  include_sentiment: boolean;
  include_extracted: boolean;
  enabled: boolean;
}

export interface PostCallDelivery {
  id: string;
  config_id: string;
  session_id: string;
  call_status: CallStatus;
  delivery_method: DeliveryMethod;
  destination: string;
  status: string;
  error: string;
  created_at: string;
}

export interface EndSessionResult {
  session_id: string;
  call_status: CallStatus;
  dispatched: number;
  skipped: number;
}

export function listPostCallConfigs(chatbotId: string): Promise<PostCallConfig[]> {
  return api.get<PostCallConfig[]>(`/chatbots/${chatbotId}/post-call`);
}

export function createPostCallConfig(
  chatbotId: string,
  input: PostCallConfigInput,
): Promise<PostCallConfig> {
  return api.post<PostCallConfig>(`/chatbots/${chatbotId}/post-call`, input);
}

export function updatePostCallConfig(
  chatbotId: string,
  configId: string,
  input: PostCallConfigInput,
): Promise<PostCallConfig> {
  return api.patch<PostCallConfig>(
    `/chatbots/${chatbotId}/post-call/${configId}`,
    input,
  );
}

export function deletePostCallConfig(
  chatbotId: string,
  configId: string,
): Promise<void> {
  return api.delete<void>(`/chatbots/${chatbotId}/post-call/${configId}`);
}

export function listPostCallDeliveries(
  chatbotId: string,
): Promise<PostCallDelivery[]> {
  return api.get<PostCallDelivery[]>(`/chatbots/${chatbotId}/post-call-deliveries`);
}

/** Close a conversation, firing any configs whose triggers match. */
export function endSession(
  chatbotId: string,
  sessionId: string,
  callStatus: CallStatus = "completed",
): Promise<EndSessionResult> {
  return api.post<EndSessionResult>(
    `/chatbots/${chatbotId}/sessions/${sessionId}/end`,
    { call_status: callStatus },
  );
}

/** Fire one rule against a real past conversation, ignoring its trigger filter. */
export function testPostCallConfig(
  chatbotId: string,
  configId: string,
  sessionId: string,
): Promise<EndSessionResult> {
  return api.post<EndSessionResult>(
    `/chatbots/${chatbotId}/post-call/${configId}/test?session_id=${sessionId}`,
  );
}
