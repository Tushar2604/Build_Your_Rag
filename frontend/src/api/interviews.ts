import { api } from "./client";

export type InterviewStatus = "scheduled" | "in_progress" | "completed" | "cancelled";
export type InterviewVerdict = "strong_hire" | "hire" | "maybe" | "no_hire" | null;

export interface TranscriptTurn {
  role: "assistant" | "user";
  content: string;
}

export interface QuestionScore {
  question: string;
  answer: string;
  score: number;
  justification: string;
}

export interface Interview {
  id: string;
  candidate_name: string;
  candidate_email: string;
  role_title: string;
  scheduled_at: string;
  status: InterviewStatus;
  questions: string[];
  transcript: TranscriptTurn[];
  calendar_link: string | null;
  overall_score: number | null;
  overall_verdict: InterviewVerdict;
  scores: QuestionScore[];
  has_report: boolean;
  join_url: string;
  calendar_created: boolean;
  email_sent: boolean;
}

export interface ScheduleInterviewInput {
  candidate_name?: string;
  candidate_email: string;
  role_title?: string;
  job_document_id: string;
  resume_document_id: string;
  scheduled_at: string;
}

export function listInterviews(): Promise<Interview[]> {
  return api.get<Interview[]>("/interviews");
}

export function getInterview(id: string): Promise<Interview> {
  return api.get<Interview>(`/interviews/${id}`);
}

export function scheduleInterview(input: ScheduleInterviewInput): Promise<Interview> {
  return api.post<Interview>("/interviews", input);
}

export function interviewReportUrl(id: string): string {
  return `/api/v1/interviews/${id}/report`;
}

// --- Candidate-facing (token-scoped, no auth) ---

export interface InterviewBootstrap {
  candidate_name: string;
  role_title: string;
  tenant_name: string;
  scheduled_at: string;
  status: InterviewStatus;
  can_join: boolean;
}

const BASE = "/api/v1";

export async function getInterviewByToken(accessToken: string): Promise<InterviewBootstrap> {
  const res = await fetch(`${BASE}/interviews/token/${encodeURIComponent(accessToken)}`);
  if (!res.ok) throw new Error(res.status === 404 ? "Interview not found" : `HTTP ${res.status}`);
  return res.json();
}

interface InterviewStreamHandlers {
  onToken?: (t: string) => void;
  onDone?: (completed: boolean) => void;
  onError?: (e: string) => void;
}

function _streamInterview(url: string, body: unknown, handlers: InterviewStreamHandlers): () => void {
  const controller = new AbortController();
  (async () => {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const detail = await res.json().catch(() => ({}));
        handlers.onError?.(detail.detail || `HTTP ${res.status}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          let evt = "message";
          const dataLines: string[] = [];
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("event:")) evt = line.slice(6).replace(/^ /, "");
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
          }
          const data = dataLines.join("\n");
          if (evt === "token") handlers.onToken?.(data);
          else if (evt === "done") handlers.onDone?.(JSON.parse(data).completed === true);
          else if (evt === "error") {
            try {
              handlers.onError?.(JSON.parse(data).detail ?? "Generation failed.");
            } catch {
              handlers.onError?.("Generation failed.");
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") handlers.onError?.((err as Error).message);
    }
  })();
  return () => controller.abort();
}

export function greetInterview(accessToken: string, handlers: InterviewStreamHandlers): () => void {
  return _streamInterview(`${BASE}/interviews/token/${accessToken}/greeting`, {}, handlers);
}

export function respondInterview(
  accessToken: string,
  message: string,
  handlers: InterviewStreamHandlers,
): () => void {
  return _streamInterview(`${BASE}/interviews/token/${accessToken}/respond`, { message }, handlers);
}
