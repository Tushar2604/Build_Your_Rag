import { api } from "./client";

export interface WidgetConfig {
  theme_color: string;
  display_name: string;
  welcome_message: string;
  launcher_position: "bottom-right" | "bottom-left";
}

export interface Chatbot {
  id: string;
  name: string;
  system_prompt: string;
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
  system_prompt?: string;
  top_k?: number;
  is_public?: boolean;
  allowed_document_ids?: string[];
}

export interface UpdateChatbotInput {
  name?: string;
  system_prompt?: string;
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
