import { api } from "./client";

export interface AnalyticsDay {
  day: string; // ISO date
  answers: number;
  avg_top_score: number | null;
  avg_citations: number;
  no_context_rate: number; // 0..1
  refusal_rate: number; // 0..1
  avg_tokens: number;
}

export interface AnalyticsProvider {
  provider: string | null;
  answers: number;
  avg_top_score: number | null;
  avg_tokens: number;
}

export interface ChatbotAnalytics {
  chatbot_id: string;
  days: number;
  daily: AnalyticsDay[];
  providers: AnalyticsProvider[];
}

export function getChatbotAnalytics(
  chatbotId: string,
  days = 30,
): Promise<ChatbotAnalytics> {
  return api.get<ChatbotAnalytics>(`/chatbots/${chatbotId}/analytics?days=${days}`);
}

export interface RequestLog {
  id: string;
  created_at: string;
  query: string;
  status: "ok" | "error";
  num_retrieved: number;
  max_score: number | null;
  no_context: boolean;
  refused: boolean;
  provider: string | null;
  model: string | null;
  tokens_used: number;
  latency_ms: number;
  error: string | null;
  answer: string | null;
}

export function getChatbotRequests(
  chatbotId: string,
  limit = 50,
): Promise<RequestLog[]> {
  return api.get<RequestLog[]>(`/chatbots/${chatbotId}/requests?limit=${limit}`);
}
