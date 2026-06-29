const BASE = "/api/v1";

function getToken(): string | null {
  return localStorage.getItem("access_token");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore parse failure
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function streamSSE(
  path: string,
  body: unknown,
  handlers: {
    onCitations?: (citations: CitationPayload[]) => void;
    onToken?: (token: string) => void;
    onDone?: (tokensUsed: number) => void;
    onError?: (err: string) => void;
  },
): () => void {
  const controller = new AbortController();
  const token = getToken();

  (async () => {
    try {
      const res = await fetch(`${BASE}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        handlers.onError?.(`HTTP ${res.status}`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // Parse complete SSE events (separated by a blank line). We must NOT
        // trim token data: the model's whitespace (spaces between words, and
        // newlines as their own tokens) is significant. Per the SSE spec we
        // strip only a single leading space after "data:" and rejoin the
        // event's multiple data lines with "\n".
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);

          let eventType = "message";
          const dataLines: string[] = [];
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).replace(/^ /, "");
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).replace(/^ /, ""));
            }
          }
          const data = dataLines.join("\n");

          if (eventType === "citations") {
            handlers.onCitations?.(JSON.parse(data) as CitationPayload[]);
          } else if (eventType === "token") {
            handlers.onToken?.(data);
          } else if (eventType === "done") {
            const parsed = JSON.parse(data) as { tokens_used: number };
            handlers.onDone?.(parsed.tokens_used);
          } else if (eventType === "error") {
            try {
              handlers.onError?.((JSON.parse(data) as { detail?: string }).detail ?? "Generation failed.");
            } catch {
              handlers.onError?.("Generation failed.");
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.((err as Error).message);
      }
    }
  })();

  return () => controller.abort();
}

export interface CitationPayload {
  document_id: string;
  ordinal: number;
  score: number;
  snippet: string;
}
