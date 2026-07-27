import { api, streamSSE, CitationPayload } from "./client";

export interface CreateSessionResponse {
  session_id: string;
}

export interface Citation {
  document_id: string;
  ordinal: number;
  score: number;
  snippet: string;
}

export interface AnswerResponse {
  message_id: string;
  answer: string;
  citations: Citation[];
  tokens_used: number;
  provider: string;
}

export function createSession(chatbotId: string): Promise<CreateSessionResponse> {
  return api.post<CreateSessionResponse>(`/chatbots/${chatbotId}/sessions`);
}

export function askMessage(
  sessionId: string,
  message: string,
): Promise<AnswerResponse> {
  return api.post<AnswerResponse>(`/sessions/${sessionId}/messages`, { message });
}

export function askStream(
  sessionId: string,
  message: string,
  handlers: {
    onCitations?: (c: CitationPayload[]) => void;
    onToken?: (t: string) => void;
    onDone?: (tokensUsed: number) => void;
    onError?: (e: string) => void;
  },
): () => void {
  return streamSSE(`/sessions/${sessionId}/stream`, { message }, handlers);
}

/** AI-generated opening turn for a brand-new session — same SSE contract as
 * askStream, but with no user message (the model greets first). */
export function greetStream(
  sessionId: string,
  handlers: {
    onCitations?: (c: CitationPayload[]) => void;
    onToken?: (t: string) => void;
    onDone?: (tokensUsed: number) => void;
    onError?: (e: string) => void;
  },
): () => void {
  return streamSSE(`/sessions/${sessionId}/greeting`, {}, handlers);
}
