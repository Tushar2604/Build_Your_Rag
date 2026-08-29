// "Web Call" as a dialog rather than a docked panel.
//
// Testing a voice assistant is not the same activity as testing a chat one.
// Chat is a side-by-side loop — read a reply, edit the section that caused it —
// which is why that one stays docked. A voice call is a single thing you do
// with your full attention for its duration: you are listening and talking, not
// reading and editing, and a 380px column with a transcript scrolling past is
// the wrong shape for it. A modal states plainly that a call is in progress and
// gives the two controls that matter — the orb and hanging up — the room to be
// unmissable.
//
// The call itself is `useVoiceCall`, shared with the inline VoiceCallPanel.
import { useEffect, useRef, useState } from "react";
import { Mic, RotateCcw, PhoneOff, Send, X } from "lucide-react";

import { useVoiceCall, VoiceCallAdapter } from "../hooks/useVoiceCall";

/** The headline under the orb. Deliberately the caller's own words rather than
 * the raw state name — "Connecting to Agent" tells someone what is happening
 * to them; "connecting" is a state machine leaking into the UI. */
const HEADLINE: Record<string, { title: string; sub: string }> = {
  idle: { title: "Ready when you are", sub: "Tap the mic to start the call" },
  connecting: { title: "Connecting to Agent…", sub: "One moment" },
  thinking: { title: "Connecting to Agent…", sub: "One moment" },
  listening: { title: "Listening…", sub: "Speak naturally — pause when you're done" },
  speaking: { title: "Agent is speaking…", sub: "Tap the orb to jump in" },
};

export default function VoiceCallModal({
  adapter,
  botName,
  onClose,
  lang = "en-US",
}: {
  adapter: VoiceCallAdapter;
  botName: string;
  onClose: () => void;
  /** BCP-47. Sets what the microphone listens for — see `useVoice`. */
  lang?: string;
}) {
  const call = useVoiceCall(adapter, lang);
  const { state, ended, captions, active, sttSupported } = call;
  const [typedInput, setTypedInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // React 18 double-invokes effects in development; without this the modal
  // opens two sessions and the assistant greets twice.
  const startedRef = useRef(false);

  // The call starts on open. Someone who clicked "Web Call" has already said
  // they want a call — making them press a second button inside the dialog is
  // a step that answers nothing.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void call.startCall();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [captions]);

  // Escape hangs up as well as closing — leaving a live mic and a speaking
  // assistant behind a dismissed dialog is the one outcome nobody wants.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") hangUp();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function hangUp() {
    call.endCall();
    onClose();
  }

  function sendTyped() {
    const text = typedInput.trim();
    if (!text) return;
    setTypedInput("");
    call.send(text);
  }

  const headline = ended
    ? { title: "Call ended", sub: "Start again whenever you're ready" }
    : HEADLINE[state] ?? HEADLINE.idle;

  // Live while the call is up, muted once it has ended.
  const live = active && !ended;

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={`Voice call with ${botName}`}
      onClick={(e) => e.target === e.currentTarget && hangUp()}
    >
      <div className="card animate-scale-in flex max-h-[86vh] w-full max-w-2xl flex-col overflow-hidden">
        {/* ── Header ── */}
        <header className="flex flex-shrink-0 items-center gap-2.5 border-b border-gray-200 px-6 py-4">
          <span
            className={live ? "dot-live" : "dot bg-gray-400"}
            aria-hidden="true"
          />
          <h2 className="font-display text-[19px] font-semibold text-gray-900">
            {ended ? "Voice Call Ended" : "Voice Call in Progress"}
          </h2>
          <button
            type="button"
            onClick={hangUp}
            aria-label="End call and close"
            className="icon-btn ml-auto"
          >
            <X className="h-[18px] w-[18px]" strokeWidth={2} />
          </button>
        </header>

        {/* ── Stage ── */}
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-8">
          <div className="flex flex-col items-center">
            {/* The orb. Pale mint disc, teal waveform — it reads as "audio is
                happening here" without needing a label, and doubles as the
                barge-in target while the assistant is talking. */}
            <button
              type="button"
              onClick={call.orbTap}
              disabled={state === "connecting" || state === "thinking"}
              aria-label={
                state === "speaking"
                  ? "Interrupt the assistant and speak"
                  : state === "idle"
                    ? "Start the call"
                    : "Voice call in progress"
              }
              className={`relative flex h-[116px] w-[116px] items-center justify-center rounded-full
                          bg-emerald-500/10 transition-transform ${
                            state === "speaking" ? "hover:scale-105" : ""
                          } disabled:cursor-default`}
            >
              {live && (
                <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/15" />
              )}
              <Waveform active={state === "listening" || state === "speaking"} />
            </button>

            <p className="mt-6 text-center font-display text-[18px] font-semibold text-gray-900">
              {headline.title}
            </p>
            <p className="mt-1 text-center text-[13px] text-gray-500">{headline.sub}</p>

            {!sttSupported && (
              <p className="mt-4 max-w-sm rounded-lg bg-amber-50 px-3 py-2 text-center text-xs text-amber-700">
                Voice input isn't supported in this browser — try Chrome or Edge. You can
                still type below.
              </p>
            )}
          </div>

          {/* Transcript, once there is one. Kept below the orb rather than
              beside it so the empty state matches the screenshot exactly: a
              call that has not said anything yet shows nothing. */}
          {captions.length > 0 && (
            <div className="mx-auto mt-8 w-full max-w-lg space-y-2.5">
              {captions.map((c) => (
                <div
                  key={c.id}
                  className={`flex ${c.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-[13.5px]
                                leading-relaxed ${
                                  c.role === "user"
                                    ? "rounded-br-sm bg-emerald-600 text-white"
                                    : c.role === "system"
                                      ? "bg-amber-50 text-[12px] text-amber-800"
                                      : "rounded-bl-sm border border-gray-200 bg-surface-2 text-gray-800"
                                }`}
                  >
                    {c.text || "…"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Controls ── */}
        <footer className="flex-shrink-0 border-t border-gray-200 px-6 py-5">
          <div className="flex justify-center">
            {ended ? (
              <CallButton
                label="Start the call again"
                tone="teal"
                onClick={() => void call.startCall()}
                icon={<RotateCcw className="h-7 w-7" strokeWidth={2} />}
              />
            ) : active ? (
              <CallButton
                label="End call"
                tone="red"
                onClick={hangUp}
                icon={<PhoneOff className="h-7 w-7" strokeWidth={2} />}
              />
            ) : (
              <CallButton
                label="Start the call"
                tone="teal"
                onClick={() => void call.startCall()}
                icon={<Mic className="h-7 w-7" strokeWidth={2} />}
              />
            )}
          </div>

          {/* Typing is always available — it is the only way in when speech
              recognition is unsupported, and the fastest way to check one
              specific reply without saying it out loud. */}
          {live && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendTyped();
              }}
              className="mx-auto mt-4 flex w-full max-w-lg items-center gap-2"
            >
              <input
                value={typedInput}
                onChange={(e) => setTypedInput(e.target.value)}
                placeholder={sttSupported ? "…or type instead" : "Type your message"}
                aria-label="Type a message to the assistant"
                className="input h-10 flex-1 rounded-full text-[13.5px]"
              />
              <button
                type="submit"
                disabled={!typedInput.trim() || state === "thinking"}
                aria-label="Send"
                className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full
                           bg-emerald-600 text-white transition-colors hover:bg-emerald-700
                           disabled:opacity-40"
              >
                <Send className="h-4 w-4" strokeWidth={2} />
              </button>
            </form>
          )}
        </footer>
      </div>
    </div>
  );
}

/** The big round control under the stage. */
function CallButton({
  label,
  tone,
  onClick,
  icon,
}: {
  label: string;
  tone: "teal" | "red";
  onClick: () => void;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`flex h-[72px] w-[72px] items-center justify-center rounded-full text-white
                  shadow-lg transition-transform hover:scale-105 active:scale-95 ${
                    tone === "teal"
                      ? "bg-emerald-600 hover:bg-emerald-700"
                      : "bg-red-500 hover:bg-red-600"
                  }`}
    >
      {icon}
    </button>
  );
}

/** Five bars that breathe while audio is flowing and sit still otherwise, so
 * the orb says whether the call is actually alive rather than just decorating
 * it. Hand-rolled rather than an icon: the animation is the whole point. */
function Waveform({ active }: { active: boolean }) {
  const heights = [10, 18, 26, 18, 10];
  return (
    <span className="relative flex items-center gap-[3px]" aria-hidden="true">
      {heights.map((h, i) => (
        <span
          key={i}
          className={`w-[3px] rounded-full bg-emerald-600 ${active ? "animate-pulse" : "opacity-70"}`}
          style={{
            height: h,
            // Offsetting each bar is what makes it read as a waveform rather
            // than five bars blinking in unison.
            animationDelay: `${i * 110}ms`,
            animationDuration: "900ms",
          }}
        />
      ))}
    </span>
  );
}
