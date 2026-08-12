import { useEffect, useRef, useState, FormEvent } from "react";
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

interface Message {
  role: "user" | "bot";
  text: string;
  citations?: PublicCitation[];
  streaming?: boolean;
}

const NUDGE_LINES = [
  "Just checking in — are you still there?",
  "No rush! I'm here whenever you're ready to continue.",
  "Still with me? Let me know if you have any questions.",
];

function TypingDots() {
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center", padding: "2px 0" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 7, height: 7, borderRadius: "50%",
            background: "#9ca3af",
            display: "inline-block",
            animation: "pulse 1.2s ease-in-out infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </span>
  );
}

function CitationList({ citations }: { citations: PublicCitation[] }) {
  const [open, setOpen] = useState(false);
  if (!citations.length) return null;
  return (
    <div style={{ marginTop: 6, fontSize: 11 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#6b7280", fontSize: 11, display: "flex",
          alignItems: "center", gap: 4, padding: "2px 0",
        }}
      >
        <span style={{
          display: "inline-block",
          transform: open ? "rotate(90deg)" : "none",
          transition: "transform 0.15s",
          fontSize: 10,
        }}>▶</span>
        {citations.length} source{citations.length !== 1 ? "s" : ""}
      </button>
      {open && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
          {citations.map((c, i) => (
            <div
              key={i}
              style={{
                background: "#f9fafb", border: "1px solid #e5e7eb",
                borderRadius: 6, padding: "6px 8px",
                color: "#4b5563", fontSize: 11, lineHeight: 1.45,
              }}
            >
              {i + 1}. {c.snippet}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EmbedChatPage() {
  const { publicKey = "" } = useParams<{ publicKey: string }>();
  const [config,  setConfig]  = useState<PublicConfig | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    getPublicConfig(publicKey)
      .then((cfg) => {
        setConfig(cfg);
        window.parent.postMessage({ type: "kore:ready", name: cfg.name }, "*");
      })
      .catch((e) => setLoadErr(e.message || "Failed to load assistant."));
  }, [publicKey]);

  if (loadErr) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
        height: "100dvh", fontFamily: "sans-serif", background: "#f9fafb" }}>
        <div style={{ textAlign: "center" }}>
          <p style={{ fontSize: 14, fontWeight: 600, color: "#111827", margin: 0 }}>Assistant unavailable</p>
          <p style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>{loadErr}</p>
        </div>
      </div>
    );
  }

  if (!config) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
        height: "100dvh", background: "#f9fafb" }}>
        <div style={{ display: "flex", gap: 6 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 8, height: 8, borderRadius: "50%", background: "#d1d5db",
              animation: "pulse 1.2s ease-in-out infinite", animationDelay: `${i * 0.2}s`,
            }} />
          ))}
        </div>
      </div>
    );
  }

  const theme = config.widget.theme_color;
  const name  = config.widget.display_name || config.name;

  if (config.channel === "voice") {
    return (
      <>
        <style>{`* { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; } html, body { margin: 0; padding: 0; height: 100%; }`}</style>
        <div style={{ display: "flex", flexDirection: "column", height: "100dvh", background: "#fff" }}>
          <div style={{ background: theme, color: "#fff", padding: "12px 16px", flexShrink: 0 }}>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{name}</p>
          </div>
          <div style={{ flex: 1, overflow: "hidden" }}>
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
      </>
    );
  }

  return <TextEmbedChat publicKey={publicKey} config={config} />;
}

function TextEmbedChat({ publicKey, config }: { publicKey: string; config: PublicConfig }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input,    setInput]    = useState("");
  const [busy,     setBusy]     = useState(false);
  const sessionRef              = useRef<string | null>(null);
  const scrollRef               = useRef<HTMLDivElement>(null);
  const inputRef                = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // AI-generated opening turn — falls back to the static welcome message
    // if greeting generation fails.
    setMessages([{ role: "bot", text: "", streaming: true }]);
    setBusy(true);
    createPublicSession(publicKey)
      .then((sid) => {
        sessionRef.current = sid;
        streamPublicGreeting(publicKey, sid, {
          onToken: (tok) =>
            setMessages((m) => {
              const copy = [...m];
              copy[0] = { ...copy[0], text: copy[0].text + tok };
              return copy;
            }),
          onDone: () => {
            setMessages((m) => {
              const copy = [...m];
              copy[0] = { ...copy[0], streaming: false };
              return copy;
            });
            setBusy(false);
          },
          onError: () => {
            setMessages([{ role: "bot", text: config.widget.welcome_message }]);
            setBusy(false);
          },
        });
      })
      .catch(() => {
        setMessages([{ role: "bot", text: config.widget.welcome_message }]);
        setBusy(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [publicKey]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useIdleNudge(!busy && messages.length > 0, () => {
    setMessages((m) => [
      ...m,
      { role: "bot", text: NUDGE_LINES[Math.floor(Math.random() * NUDGE_LINES.length)] },
    ]);
  });

  /* Listen for programmatic messages from the parent page */
  useEffect(() => {
    function handler(ev: MessageEvent) {
      if (ev.data?.type === "kore:ask" && typeof ev.data.text === "string") {
        setInput(ev.data.text);
        inputRef.current?.focus();
      }
    }
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");

    setMessages((m) => [
      ...m,
      { role: "user", text },
      { role: "bot",  text: "", streaming: true },
    ]);

    try {
      if (!sessionRef.current) {
        sessionRef.current = await createPublicSession(publicKey);
      }
      let pendingCites: PublicCitation[] = [];

      streamPublic(publicKey, sessionRef.current, text, {
        onCitations: (c) => { pendingCites = c; },
        onToken: (tok) => {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              text: copy[copy.length - 1].text + tok,
            };
            return copy;
          });
        },
        onDone: () => {
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = { ...last, streaming: false, citations: pendingCites };
            window.parent.postMessage({ type: "kore:message", role: "bot", text: last.text }, "*");
            return copy;
          });
          setBusy(false);
          inputRef.current?.focus();
        },
        onError: (msg) => {
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { role: "bot", text: msg || "Something went wrong.", streaming: false };
            return copy;
          });
          setBusy(false);
        },
      });
    } catch (err) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "bot", text: (err as Error).message || "Could not connect.", streaming: false,
        };
        return copy;
      });
      setBusy(false);
    }
  }

  const theme = config.widget.theme_color;
  const name  = config.widget.display_name || config.name;

  return (
    <>
      <style>{`
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        html, body { margin: 0; padding: 0; height: 100%; }
        @keyframes pulse { 0%,60%,100% { opacity: .25; transform: scale(.85); } 30% { opacity: 1; transform: scale(1); } }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }
      `}</style>

      <div style={{ display: "flex", flexDirection: "column", height: "100dvh", background: "#fff" }}>
        {/* Header */}
        <div style={{
          background: theme, color: "#fff",
          padding: "12px 16px",
          display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: "50%",
            background: "rgba(255,255,255,0.2)",
            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{name}</p>
            <p style={{ margin: 0, fontSize: 11, opacity: 0.7 }}>AI Assistant</p>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={scrollRef}
          style={{
            flex: 1, overflowY: "auto",
            padding: "16px 14px",
            display: "flex", flexDirection: "column", gap: 10,
            background: "#f7f8fa",
          }}
          role="log" aria-live="polite"
        >
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "84%",
              }}
            >
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: 16,
                  borderBottomRightRadius: m.role === "user" ? 4 : 16,
                  borderBottomLeftRadius:  m.role === "bot"  ? 4 : 16,
                  fontSize: 14, lineHeight: 1.5,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                  background: m.role === "user" ? theme : "#fff",
                  color: m.role === "user" ? "#fff" : "#1a1d2e",
                  border: m.role === "bot" ? "1px solid #e5e7eb" : "none",
                  boxShadow: m.role === "bot" ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                }}
              >
                {m.text ? m.text : (m.streaming ? <TypingDots /> : <span style={{ color: "#9ca3af", fontStyle: "italic" }}>No response</span>)}
              </div>
              {m.citations && <CitationList citations={m.citations} />}
            </div>
          ))}
        </div>

        {/* Composer */}
        <form
          onSubmit={send}
          style={{
            display: "flex", gap: 8, padding: 12,
            borderTop: "1px solid #e5e7eb", background: "#fff", flexShrink: 0,
          }}
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 96)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
            placeholder="Type a message… (Enter to send)"
            disabled={busy}
            aria-label="Message"
            style={{
              flex: 1, resize: "none",
              border: "1px solid #d1d5db", borderRadius: 10,
              padding: "9px 12px", fontSize: 14,
              fontFamily: "inherit", lineHeight: 1.45,
              minHeight: 40, maxHeight: 96,
              outline: "none",
              transition: "border-color 0.15s",
            }}
            onFocus={(e) => { e.target.style.borderColor = theme; }}
            onBlur={(e) => { e.target.style.borderColor = "#d1d5db"; }}
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="Send"
            style={{
              width: 40, height: 40, flexShrink: 0,
              background: theme, color: "#fff",
              border: "none", borderRadius: 10,
              cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              opacity: busy || !input.trim() ? 0.4 : 1,
              transition: "opacity 0.15s",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
            </svg>
          </button>
        </form>

        <div style={{ textAlign: "center", fontSize: 10, color: "#d1d5db", padding: "4px 0 8px" }}>
          Powered by Evara AI
        </div>
      </div>
    </>
  );
}
