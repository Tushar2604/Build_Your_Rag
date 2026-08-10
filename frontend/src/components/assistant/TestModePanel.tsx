// Test Mode — talk to the assistant you are editing, beside the thing you edit.
//
// A docked right-hand panel rather than a modal, so the flow stays on screen:
// the point of a test is to read a reply and go change the section that caused
// it. The header goes into a locked state for the duration, because an
// assistant that changes mid-conversation makes the transcript meaningless —
// you would no longer know which version said what.
import { useEffect, useRef, useState } from "react";
import { Loader2, Send, Sparkles, X } from "lucide-react";
import { Chatbot } from "../../api/chatbots";
import { askStream, createSession, greetStream } from "../../api/chat";
import VoiceCallPanel from "../VoiceCallPanel";

export type TestMode = "chat" | "web-call";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

interface Props {
  bot: Chatbot;
  mode: TestMode;
  onClose: () => void;
}

function ChatTest({ bot }: { bot: Chatbot }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Open the session and let the assistant greet, exactly as a real caller
  // would experience it. The ref guards React 18's double-invoked effects,
  // which would otherwise open two sessions and greet twice.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    (async () => {
      setBusy(true);
      try {
        const { session_id } = await createSession(bot.id);
        setSessionId(session_id);
        const id = crypto.randomUUID();
        setMessages([{ id, role: "assistant", content: "", streaming: true }]);
        greetStream(session_id, {
          onToken: (token) =>
            setMessages((prev) =>
              prev.map((m) => (m.id === id ? { ...m, content: m.content + token } : m)),
            ),
          onDone: () => {
            setMessages((prev) =>
              prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
            );
            setBusy(false);
          },
          onError: (message) => {
            setError(message);
            setBusy(false);
          },
        });
      } catch {
        setError("Could not start the test session.");
        setBusy(false);
      }
    })();
  }, [bot.id]);

  function send() {
    const text = input.trim();
    if (!text || !sessionId || busy) return;

    const answerId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: text },
      { id: answerId, role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setBusy(true);
    setError(null);

    askStream(sessionId, text, {
      onToken: (token) =>
        setMessages((prev) =>
          prev.map((m) => (m.id === answerId ? { ...m, content: m.content + token } : m)),
        ),
      onDone: () => {
        setMessages((prev) =>
          prev.map((m) => (m.id === answerId ? { ...m, streaming: false } : m)),
        );
        setBusy(false);
      },
      onError: (message) => {
        setError(message);
        setMessages((prev) => prev.filter((m) => m.id !== answerId));
        setBusy(false);
      },
    });
  }

  return (
    <>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3 min-h-0">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[88%] rounded-xl px-3.5 py-2.5 text-[13.5px] leading-relaxed whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-brand-500/15 text-gray-900 rounded-br-sm"
                  : "bg-surface-2 border border-gray-200 text-gray-800 rounded-bl-sm"
              }`}
            >
              {m.content || (m.streaming ? "…" : "")}
              {m.streaming && m.content && (
                <span className="inline-block w-1.5 h-3.5 bg-brand-400 ml-0.5 align-middle animate-pulse" />
              )}
            </div>
          </div>
        ))}

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="flex-shrink-0 border-t border-gray-200 p-3"
      >
        <div className="relative">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter breaks the line — chat convention.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            disabled={!sessionId}
            aria-label="Message the assistant"
            placeholder="Reply as a caller would…"
            className="input resize-none text-[13.5px] bg-surface-2 pr-12"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy || !sessionId}
            aria-label="Send"
            className="absolute right-2 bottom-2 inline-flex items-center justify-center w-9 h-9
                       rounded-lg bg-brand-600 text-white transition-colors hover:bg-brand-700
                       disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
            ) : (
              <Send className="w-4 h-4" strokeWidth={2} />
            )}
          </button>
        </div>
      </form>
    </>
  );
}

export default function TestModePanel({ bot, mode, onClose }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      aria-label="Test mode"
      className="w-[380px] flex-shrink-0 border-l border-gray-200 bg-surface flex flex-col h-full"
    >
      <header className="flex items-center gap-2 px-4 h-[52px] border-b border-gray-200 flex-shrink-0">
        <Sparkles className="w-4 h-4 text-brand-400 flex-shrink-0" strokeWidth={2} />
        <span className="text-[14px] font-semibold text-gray-900">AI Assistant</span>
        <button
          onClick={onClose}
          aria-label="Close test mode"
          className="ml-auto icon-btn"
        >
          <X className="w-4 h-4" strokeWidth={2} />
        </button>
      </header>

      <div className="flex items-center gap-3 px-4 py-3 bg-brand-500/[0.06] border-b border-gray-200 flex-shrink-0">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold text-gray-900 leading-tight">Test Mode</p>
          <p className="text-[11.5px] text-gray-500 leading-tight mt-0.5">
            {mode === "chat"
              ? "Chatting directly with the assistant"
              : "Speaking with the assistant"}
          </p>
        </div>
        <button
          onClick={onClose}
          className="flex-shrink-0 rounded-lg bg-red-500/90 px-3 py-1.5 text-[12.5px] font-semibold
                     text-white transition-colors hover:bg-red-600"
        >
          End Test
        </button>
      </div>

      {mode === "chat" ? (
        <ChatTest bot={bot} />
      ) : (
        <div className="flex-1 min-h-0 overflow-hidden">
          <VoiceCallPanel
            botName={bot.name}
            adapter={{
              createSession: async () => (await createSession(bot.id)).session_id,
              greet: (sid, h) =>
                greetStream(sid, {
                  onToken: h.onToken,
                  onDone: () => h.onDone?.(),
                  onError: h.onError,
                }),
              ask: (sid, text, h) =>
                askStream(sid, text, {
                  onToken: h.onToken,
                  onDone: (tokens) => h.onDone?.(tokens),
                  onError: h.onError,
                }),
            }}
          />
        </div>
      )}
    </aside>
  );
}
