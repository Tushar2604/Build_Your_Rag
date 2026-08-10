import { api } from "./client";

export interface WidgetConfig {
  theme_color: string;
  display_name: string;
  welcome_message: string;
  launcher_position: "bottom-right" | "bottom-left";
}

export type Channel = "text" | "voice";

/** One named, toggleable block of the Conversational Flow. `id` is absent only
 * for a section the UI has just added — the server mints one on save. */
export interface FlowSection {
  id?: string;
  title: string;
  body: string;
  enabled: boolean;
}

/** Runtime settings on the Assistant Details tab. Saved as a unit. */
export interface AssistantConfig {
  direction: "outgoing" | "incoming";
  languages: string[];
  tts_voice: string;
  llm_model: string;
  stt_model: string;
  welcome_message: string;
  /** Model rephrases the opener per call instead of reading it verbatim. */
  welcome_dynamic: boolean;
  /** The caller can talk over the opener. */
  welcome_interruptible: boolean;
}

export interface AssistantOptions {
  languages: string[];
  tts_voices: string[];
  llm_models: string[];
  stt_models: string[];
  use_cases: { id: string; label: string }[];
}

export interface Chatbot {
  id: string;
  name: string;
  channel: Channel;
  /** The composed prompt the model actually receives (read-only when the bot
   * is authored as sections). */
  system_prompt: string;
  /** Empty when this bot was authored as a raw prompt instead. */
  flow_sections: FlowSection[];
  /** Cloned voice for spoken replies; null = the browser's default voice. */
  voice_profile_id: string | null;
  assistant: AssistantConfig;
  top_k: number;
  is_public: boolean;
  public_key: string;
  allowed_origins: string[];
  /** Empty = this assistant retrieves from every ready document in the tenant. */
  allowed_document_ids: string[];
  widget: WidgetConfig;
  public_url: string;
  embed_snippet: string;
  /** False when generation fell back to a draft — only set on a generate call. */
  ai_generated: boolean;
}

export interface CreateChatbotInput {
  name: string;
  channel?: Channel;
  system_prompt?: string;
  top_k?: number;
  is_public?: boolean;
  allowed_document_ids?: string[];
}

export interface UpdateChatbotInput {
  name?: string;
  channel?: Channel;
  /** Mutually exclusive with `flow_sections` — the API rejects both together. */
  system_prompt?: string;
  flow_sections?: FlowSection[];
  top_k?: number;
  is_public?: boolean;
  allowed_origins?: string[];
  widget?: WidgetConfig;
  /** Requires `voice_profile_id_set: true` — otherwise an omitted field
   * would be indistinguishable from an intentional clear. */
  voice_profile_id?: string | null;
  voice_profile_id_set?: boolean;
  /** Whole-object replace, not a merge. */
  assistant?: AssistantConfig;
  allowed_document_ids?: string[];
}

/* ── Knowledge base (per assistant) ── */
export interface KnowledgeDocument {
  id: string;
  filename: string;
  status: string;
  chunk_count: number;
  error: string | null;
  attached: boolean;
}

export interface AssistantKnowledge {
  documents: KnowledgeDocument[];
  attached_count: number;
  ready_count: number;
  /** True when nothing is attached, i.e. the assistant searches everything. */
  scope_is_all: boolean;
}

export function listChatbots(): Promise<Chatbot[]> {
  return api.get<Chatbot[]>("/chatbots");
}

export function getChatbot(id: string): Promise<Chatbot> {
  return api.get<Chatbot>(`/chatbots/${id}`);
}

export function createChatbot(input: CreateChatbotInput): Promise<Chatbot> {
  return api.post<Chatbot>("/chatbots", input);
}

export function updateChatbot(
  id: string,
  input: UpdateChatbotInput,
): Promise<Chatbot> {
  return api.patch<Chatbot>(`/chatbots/${id}`, input);
}

export function rotateChatbotKey(id: string): Promise<Chatbot> {
  return api.post<Chatbot>(`/chatbots/${id}/rotate-key`);
}

/** Replace the prompt with the stock section set — used both to recover a flow
 * and to give a raw-prompt bot something to edit in the flow builder. */
export function resetChatbotFlow(id: string): Promise<Chatbot> {
  return api.post<Chatbot>(`/chatbots/${id}/flow/reset`);
}

/** Dropdown contents for the Assistant Settings row + the create-box chips. */
export function getAssistantOptions(): Promise<AssistantOptions> {
  return api.get<AssistantOptions>("/chatbots/options");
}

/** Describe an assistant in prose; the server generates and saves it. */
export function generateAssistant(input: {
  description: string;
  use_case?: string | null;
  channel?: Channel;
}): Promise<Chatbot> {
  return api.post<Chatbot>("/chatbots/generate", input);
}

/** "Ask AI" — rebuild an existing assistant's flow. Replaces it wholesale. */
export function regenerateFlow(
  id: string,
  input: { description: string; use_case?: string | null },
): Promise<Chatbot> {
  return api.post<Chatbot>(`/chatbots/${id}/flow/generate`, input);
}

export function getAssistantKnowledge(id: string): Promise<AssistantKnowledge> {
  return api.get<AssistantKnowledge>(`/chatbots/${id}/knowledge`);
}

export function setAssistantKnowledge(
  id: string,
  documentIds: string[],
): Promise<AssistantKnowledge> {
  return api.put<AssistantKnowledge>(`/chatbots/${id}/knowledge`, {
    document_ids: documentIds,
  });
}
