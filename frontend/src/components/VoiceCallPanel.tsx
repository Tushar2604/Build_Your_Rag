// Phone-call-style interface for "voice" channel chatbots: one big mic
// control driving a continuous listen -> auto-send -> auto-speak-reply loop,
// with a live transcript. Shared by the Playground tab, the public share
// page, and the iframe embed — each supplies a small adapter over its own
// existing session/stream API (no new backend surface).
import { useEffect, useRef, useState } from "react";
import { useVoice } from "../hooks/useVoice";

export interface VoiceCallHandlers {
  onToken?: (token: string) => void;
  onDone?: (tokensUsed?: number) => void;
  /** Optional: the adapter calls this INSTEAD of onDone when this exchange
   * was the last one (e.g. a structured interview just answered its final
   * question). Callers that never invoke it (regular chatbots) get the
   * existing open-ended listen loop unchanged. */
  onEnded?: () => void;
  onError?: (err: string) => void;
}

export interface VoiceCallAdapter {
  createSession: () => Promise<string>;
  greet: (sessionId: string, handlers: VoiceCallHandlers) => () => void;
  ask: (sessionId: string, text: string, handlers: VoiceCallHandlers) => () => void;
}

interface Caption {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
}

type CallState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

const STATE_LABEL: Record<CallState, string> = {
  idle: "Tap to start the call",
  connecting: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

export default function VoiceCallPanel({
  adapter,
  botName,
  theme = "#4f46e5",
}: {
  adapter: VoiceCallAdapter;
  botName: string;
  theme?: string;
}) {
  const [state, setState] = useState<CallState>("idle");
  const [ended, setEnded] = useState(false);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [typedInput, setTypedInput] = useState("");
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<CallState>("idle");
  stateRef.current = state;

  const { sttSupported, ttsSupported, startListening, stopListening, speak } = useVoice((transcript) =>
    handleTranscript(transcript),
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [captions]);

  useEffect(
    () => () => {
      abortRef.current?.();
      stopListening();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  function addCaption(role: Caption["role"], text: string): string {
    const id = crypto.randomUUID();
    setCaptions((c) => [...c, { id, role, text }]);
    return id;
  }

  function appendCaption(id: string, token: string) {
    setCaptions((c) => c.map((m) => (m.id === id ? { ...m, text: m.text + token } : m)));
  }

  function afterReply(fullText: string) {
    if (ttsSupported) {
      setState("speaking");
      speak(fullText, () => {
        if (sttSupported) {
          setState("listening");
          startListening();
        } else {
          setState("idle");
        }
      });
    } else if (sttSupported) {
      setState("listening");
      startListening();
    } else {
      setState("idle");
    }
  }

  function finishCall(fullText: string) {
    stopListening();
    if (ttsSupported) {
      setState("speaking");
      speak(fullText, () => {
        setState("idle");
        setEnded(true);
      });
    } else {
      setState("idle");
      setEnded(true);
    }
  }

  function handleTranscript(text: string) {
    if (!sessionRef.current || stateRef.current === "thinking") return;
    addCaption("user", text);
    setState("thinking");
    let full = "";
    const captionId = addCaption("assistant", "");
    abortRef.current = adapter.ask(sessionRef.current, text, {
      onToken: (t) => {
        full += t;
        appendCaption(captionId, t);
      },
      onDone: () => afterReply(full),
      onEnded: () => finishCall(full),
      onError: (e) => {
        appendCaption(captionId, e || "Something went wrong.");
        afterReply("");
      },
    });
  }

  function sendTyped() {
    const text = typedInput.trim();
    if (!text) return;
    setTypedInput("");
    handleTranscript(text);
  }

  async function startCall() {
    setState("connecting");
    setEnded(false);
    setCaptions([]);
    try {
      const sid = await adapter.createSession();
      sessionRef.current = sid;
      let full = "";
      const captionId = addCaption("assistant", "");
      setState("thinking");
      abortRef.current = adapter.greet(sid, {
        onToken: (t) => {
          full += t;
          appendCaption(captionId, t);
        },
        onDone: () => afterReply(full),
        onError: () => {
          appendCaption(captionId, "Hi! How can I help?");
          afterReply("Hi! How can I help?");
        },
      });
    } catch {
      addCaption("system", "Could not connect. Please try again.");
      setState("idle");
    }
  }

  function endCall() {
    abortRef.current?.();
    stopListening();
    window.speechSynthesis?.cancel();
    sessionRef.current = null;
    setState("idle");
  }

  function orbTap() {
    if (state === "idle") {
      startCall();
    } else if (state === "speaking") {
      // barge-in: cut the reply short and start listening immediately
      window.speechSynthesis?.cancel();
      if (sttSupported) {
        setState("listening");
        startListening();
      }
    }
  }

  const active = state !== "idle";
  const ringClass =
    state === "listening"
      ? "animate-pulse"
      : state === "connecting" || state === "thinking"
        ? "animate-pulse"
        : "";

  return (
    <div className="flex flex-col h-full items-center">
      {/* Orb */}
      <div className="flex flex-col items-center pt-10 pb-6 flex-shrink-0">
        <button
          type="button"
          onClick={orbTap}
          disabled={state === "connecting" || state === "thinking" || ended}
          aria-label={active ? "Voice call in progress" : ended ? "Call ended" : "Start voice call"}
          className={`relative w-28 h-28 rounded-full flex items-center justify-center text-white shadow-lg transition-transform ${ringClass} ${
            state === "idle" && !ended ? "hover:scale-105" : ""
          }`}
          style={{ backgroundColor: ended ? "#10b981" : theme }}
        >
          {(state === "listening" || state === "speaking") && (
            <span
              className="absolute inset-0 rounded-full animate-ping opacity-30"
              style={{ backgroundColor: theme }}
            />
          )}
          <svg className="w-10 h-10 relative" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            {ended ? (
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            ) : state === "thinking" ? (
              <>
                <circle cx="6" cy="12" r="1.5" fill="currentColor" stroke="none" />
                <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
                <circle cx="18" cy="12" r="1.5" fill="currentColor" stroke="none" />
              </>
            ) : (
              <>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15a3 3 0 003-3V6a3 3 0 10-6 0v6a3 3 0 003 3z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-14 0M12 18v4" />
              </>
            )}
          </svg>
        </button>
        <p className="text-sm text-gray-600 mt-4 font-medium">
          {ended ? "Call complete — thank you!" : STATE_LABEL[state]}
        </p>
        {active && (
          <button type="button" onClick={endCall} className="text-xs text-red-600 hover:underline mt-2">
            End call
          </button>
        )}
        {!sttSupported && (
          <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5 mt-3 max-w-xs text-center">
            Voice input isn't supported in this browser — try Chrome or Edge. You can still type below.
          </p>
        )}
      </div>

      {/* Transcript */}
      <div ref={scrollRef} className="flex-1 w-full max-w-lg overflow-y-auto px-4 space-y-3">
        {captions.length === 0 && (
          <p className="text-center text-xs text-gray-400 mt-4">
            {botName} will greet you when the call starts.
          </p>
        )}
        {captions.map((c) => (
          <div key={c.id} className={`flex ${c.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                c.role === "user"
                  ? "text-white rounded-br-sm"
                  : c.role === "system"
                    ? "bg-amber-50 text-amber-800 text-xs"
                    : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm"
              }`}
              style={c.role === "user" ? { backgroundColor: theme } : undefined}
            >
              {c.text || "…"}
            </div>
          </div>
        ))}
      </div>

      {/* Typed fallback — always available, essential when STT is unsupported */}
      {active && (
        <form
          onSubmit={(e) => { e.preventDefault(); sendTyped(); }}
          className="w-full max-w-lg flex gap-2 px-4 py-4 flex-shrink-0"
        >
          <input
            value={typedInput}
            onChange={(e) => setTypedInput(e.target.value)}
            placeholder={sttSupported ? "…or type instead" : "Type your message"}
            className="input flex-1 text-sm"
          />
          <button type="submit" disabled={!typedInput.trim() || state === "thinking"} className="btn-primary px-4">
            Send
          </button>
        </form>
      )}
    </div>
  );
}
