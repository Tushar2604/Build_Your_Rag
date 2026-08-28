import { useEffect, useRef, useState, FormEvent } from "react";
import DictateButton from "../components/DictateButton";
import { useParams } from "react-router-dom";
import {
  getPublicConfig,
  createPublicSession,
  streamPublic,
  streamPublicGreeting,
  PublicConfig,
  PublicCitation,
} from "../api/public";
import VoiceCallPanel from "../components/VoiceCallPanel";
import { useIdleNudge } from "../hooks/useIdleNudge";

interface ChatMessage {
  role: "user" | "bot";
  content: string;
  citations?: PublicCitation[];
}

const NUDGE_LINES = [
  "Just checking in — are you still there?",
  "No rush! I'm here whenever you're ready to continue.",
  "Still with me? Let me know if you have any questions.",
];

export default function WidgetChatPage() {
  const { publicKey = "" } = useParams();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicConfig(publicKey).then(setConfig).catch((e) => setError(e.message));
  }, [publicKey]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas px-4">
        <div className="text-center">
          <p className="text-lg font-semibold text-gray-900">Chatbot unavailable</p>
          <p className="text-sm text-gray-500 mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas text-sm text-gray-400">
        Loading…
      </div>
    );
  }

  const theme = config.widget.theme_color;
  const name = config.widget.display_name || config.name;

  if (config.channel === "voice") {
    return (
      <div className="min-h-screen flex flex-col bg-gray-100">
        <header className="px-5 py-4 text-white shadow-sm" style={{ backgroundColor: theme }}>
          <h1 className="text-base font-semibold">{name}</h1>
        </header>
        <div className="flex-1">
          <VoiceCallPanel
            botName={name}
            theme={theme}
            adapter={{
              createSession: () => createPublicSession(publicKey),
              greet: (sid, h) =>
                streamPublicGreeting(publicKey, sid, { onToken: h.onToken, onDone: () => h.onDone?.(), onError: h.onError }),
              ask: (sid, text, h) =>
                streamPublic(publicKey, sid, text, { onToken: h.onToken, onDone: () => h.onDone?.(), onError: h.onError }),
            }}
          />
        </div>
      </div>
    );
  }

  return <TextWidgetChat publicKey={publicKey} config={config} />;
}

function TextWidgetChat({ publicKey, config }: { publicKey: string; config: PublicConfig }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages([{ role: "bot", content: "" }]);
    setBusy(true);
    createPublicSession(publicKey)
      .then((sid) => {
        sessionRef.current = sid;
        streamPublicGreeting(publicKey, sid, {
          onToken: (tok) =>
            setMessages((m) => {
              const copy = [...m];
              copy[0] = { ...copy[0], content: copy[0].content + tok };
              return copy;
            }),
          onDone: () => setBusy(false),
          onError: () => {
            setMessages([{ role: "bot", content: config.widget.welcome_message }]);
            setBusy(false);
          },
        });
      })
      .catch(() => {
        setMessages([{ role: "bot", content: config.widget.welcome_message }]);
        setBusy(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [publicKey]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  useIdleNudge(!busy && messages.length > 0, () => {
    setMessages((m) => [
      ...m,
      { role: "bot", content: NUDGE_LINES[Math.floor(Math.random() * NUDGE_LINES.length)] },
    ]);
  });

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }, { role: "bot", content: "" }]);

    try {
      if (!sessionRef.current) sessionRef.current = await createPublicSession(publicKey);
      let pendingCitations: PublicCitation[] = [];
      streamPublic(publicKey, sessionRef.current, text, {
        onCitations: (c) => {
          pendingCitations = c;
        },
        onToken: (tok) =>
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              content: copy[copy.length - 1].content + tok,
            };
            return copy;
          }),
        onError: (msg) => {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { role: "bot", content: msg || "Something went wrong." };
            return copy;
          });
          setBusy(false);
        },
        onDone: () => {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { ...copy[copy.length - 1], citations: pendingCitations };
            return copy;
          });
          setBusy(false);
        },
      });
    } catch (err) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "bot", content: (err as Error).message };
        return copy;
      });
      setBusy(false);
    }
  }

  const theme = config.widget.theme_color;

  return (
    <div className="min-h-screen flex flex-col bg-gray-100">
      <header className="px-5 py-4 text-white shadow-sm" style={{ backgroundColor: theme }}>
        <h1 className="text-base font-semibold">{config.widget.display_name || config.name}</h1>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-2xl flex flex-col gap-3">
          {messages.map((m, i) => (
            <div
              key={i}
              className={m.role === "user" ? "self-end max-w-[80%]" : "self-start max-w-[80%]"}
            >
              <div
                className={
                  m.role === "user"
                    ? "rounded-2xl rounded-br-sm px-4 py-2.5 text-white text-sm whitespace-pre-wrap"
                    : "rounded-2xl rounded-bl-sm px-4 py-2.5 bg-surface border border-gray-200 text-gray-800 text-sm whitespace-pre-wrap"
                }
                style={m.role === "user" ? { backgroundColor: theme } : undefined}
              >
                {m.content || (busy && i === messages.length - 1 ? "…" : "")}
              </div>
              {m.citations && m.citations.length > 0 && (
                <details className="mt-1 text-xs text-gray-400">
                  <summary className="cursor-pointer">{m.citations.length} source(s)</summary>
                  {m.citations.map((c, j) => (
                    <p key={j} className="mt-1 rounded bg-gray-50 border border-gray-200 px-2 py-1 text-gray-500">
                      {c.snippet}
                    </p>
                  ))}
                </details>
              )}
            </div>
          ))}
        </div>
      </div>

      <form onSubmit={send} className="border-t border-gray-200 bg-surface px-4 py-3">
        <div className="mx-auto max-w-2xl flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message…"
            className="flex-1 rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2"
            style={{ ["--tw-ring-color" as string]: theme }}
          />
          {/* Browser engine only: this page is public, so there is no session
              to authenticate a server transcription with. */}
          <DictateButton
            value={input}
            onChange={setInput}
            allowServer={false}
            className="self-center"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-xl px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: theme }}
          >
            Send
          </button>
        </div>
        <p className="text-center text-[10px] text-gray-400 mt-2">Powered by Evara AI</p>
      </form>
    </div>
  );
}
