// Public, unauthenticated client for the hosted share-by-link chat page.
// Mirrors the embeddable widget's contract but lives in the SPA.

import type { Channel, WidgetConfig } from "./chatbots";

const BASE = "/api/v1/public";

export interface PublicConfig {
  chatbot_id: string;
  name: string;
  channel: Channel;
  widget: WidgetConfig;
}

export interface PublicCitation {
  ordinal: number;
  score: number;
  snippet: string;
}

export async function getPublicConfig(publicKey: string): Promise<PublicConfig> {
  const res = await fetch(`${BASE}/chatbots/${encodeURIComponent(publicKey)}/config`);
  if (!res.ok) throw new Error(res.status === 404 ? "Chatbot not found" : `HTTP ${res.status}`);
  return res.json();
}

export async function createPublicSession(publicKey: string): Promise<string> {
  const res = await fetch(
    `${BASE}/chatbots/${encodeURIComponent(publicKey)}/sessions`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error("Could not start a session");
  const data = await res.json();
  return data.session_id as string;
}

type StreamHandlers = {
  onCitations?: (c: PublicCitation[]) => void;
  onToken?: (t: string) => void;
  onDone?: () => void;
  onError?: (e: string) => void;
};

function streamUrl(publicKey: string, sessionId: string, path: string): string {
  return `${BASE}/chatbots/${encodeURIComponent(publicKey)}/sessions/${sessionId}/${path}`;
}

function _stream(url: string, body: unknown, handlers: StreamHandlers): () => void {
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
        handlers.onError?.(`HTTP ${res.status}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // Parse whole SSE events; never trim token data (spaces and newlines
        // from the model are significant). Strip only one leading space after
        // "data:" and rejoin multi-line data with "\n", per the SSE spec.
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
          if (evt === "citations") handlers.onCitations?.(JSON.parse(data));
          else if (evt === "token") handlers.onToken?.(data);
          else if (evt === "error") handlers.onError?.("Generation failed.");
        }
      }
      handlers.onDone?.();
    } catch (err) {
      if ((err as Error).name !== "AbortError") handlers.onError?.((err as Error).message);
    }
  })();
  return () => controller.abort();
}

export function streamPublic(
  publicKey: string,
  sessionId: string,
  message: string,
  handlers: StreamHandlers,
): () => void {
  return _stream(streamUrl(publicKey, sessionId, "stream"), { message }, handlers);
}

/** AI-generated opening turn for a brand-new session — same contract as
 * streamPublic, but with no user message (the model greets first). */
export function streamPublicGreeting(
  publicKey: string,
  sessionId: string,
  handlers: StreamHandlers,
): () => void {
  return _stream(streamUrl(publicKey, sessionId, "greeting"), {}, handlers);
}
