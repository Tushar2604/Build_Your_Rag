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

export interface Chatbot {
  id: string;
  name: string;
  channel: Channel;
  /** The composed prompt the model actually receives (read-only when the bot
   * is authored as sections). */
  system_prompt: string;
  /** Empty when this bot was authored as a raw prompt instead. */
  flow_sections: FlowSection[];
  top_k: number;
  is_public: boolean;
  public_key: string;
  allowed_origins: string[];
  widget: WidgetConfig;
  public_url: string;
  embed_snippet: string;
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
