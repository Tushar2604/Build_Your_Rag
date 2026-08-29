// Phone-call-style interface for "voice" channel chatbots: one big mic
// control driving a continuous listen -> auto-send -> auto-speak-reply loop,
// with a live transcript. Shared by the public share page and the iframe
// embed — each supplies a small adapter over its own existing session/stream
// API (no new backend surface).
//
// The loop itself lives in `useVoiceCall`; this file is only its inline
// presentation. `VoiceCallModal` renders the same call as a dialog.
import { useEffect, useRef, useState } from "react";
import { STATE_LABEL, useVoiceCall, VoiceCallAdapter } from "../hooks/useVoiceCall";

export type { VoiceCallAdapter, VoiceCallHandlers } from "../hooks/useVoiceCall";

export default function VoiceCallPanel({
  adapter,
  botName,
  theme = "#7c3aed",
}: {
  adapter: VoiceCallAdapter;
  botName: string;
  theme?: string;
}) {
  const call = useVoiceCall(adapter);
  const { state, ended, captions, active, sttSupported } = call;
  const [typedInput, setTypedInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [captions]);

  function sendTyped() {
    const text = typedInput.trim();
    if (!text) return;
    setTypedInput("");
    call.send(text);
  }

  const ringClass =
    state === "listening" || state === "connecting" || state === "thinking"
      ? "animate-pulse"
      : "";

  return (
    <div className="flex flex-col h-full items-center">
      {/* Orb */}
      <div className="flex flex-col items-center pt-6 pb-4 flex-shrink-0">
        <button
          type="button"
          onClick={call.orbTap}
          disabled={state === "connecting" || state === "thinking" || ended}
          aria-label={active ? "Voice call in progress" : ended ? "Call ended" : "Start voice call"}
          className={`relative w-16 h-16 rounded-full flex items-center justify-center text-white shadow-lg transition-transform ${ringClass} ${
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
          <svg className="w-6 h-6 relative" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
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
        <p className="text-[13px] text-gray-600 mt-3 font-medium">
          {ended ? "Call complete — thank you!" : STATE_LABEL[state]}
        </p>
        {active && (
          <button type="button" onClick={call.endCall} className="text-xs text-red-600 hover:underline mt-2">
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
                    : "bg-surface border border-gray-200 text-gray-800 rounded-bl-sm"
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
