// The voice-call state machine, extracted from VoiceCallPanel so more than one
// surface can render it.
//
// There are two presentations of the same call — the inline panel used by the
// public share page, the widget and the interview page, and the modal used when
// you hit "Web Call" while building an assistant — and they differ only in
// chrome. Keeping the loop here means a fix to barge-in, silence handling or
// the greet sequence lands on both, which is exactly what stopped being true
// once the modal existed.
import { useEffect, useRef, useState } from "react";
import { useVoice } from "./useVoice";

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

export interface Caption {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
}

export type CallState = "idle" | "connecting" | "listening" | "thinking" | "speaking";

export const STATE_LABEL: Record<CallState, string> = {
  idle: "Tap to start the call",
  connecting: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

// Varied check-in lines so a real silence doesn't feel like a canned bot
// message repeating itself.
const CHECK_IN_LINES = [
  "Are you still there?",
  "Just checking in — take your time, I'm still here whenever you're ready.",
  "Hello? Let me know when you'd like to continue.",
];

// After this many check-ins, stop nudging and end the call gracefully instead
// of looping forever.
const MAX_CHECK_INS = 2;

// How long the candidate must actually be silent before we check in.
//
// Speech recognition ends a turn after ~5s of quiet (SILENCE_TIMEOUT_MS in
// useVoice), which is a "you stopped speaking" signal, NOT a "you've gone away"
// signal. Nudging on the first such turn interrupted people who were simply
// thinking. Silent turns are now accumulated until this much real time has
// passed, so the mic keeps re-arming quietly in between.
const SILENCE_BEFORE_CHECK_IN_MS = 45000;

export interface VoiceCall {
  state: CallState;
  ended: boolean;
  captions: Caption[];
  /** True whenever a call is up — anything other than idle. */
  active: boolean;
  sttSupported: boolean;
  startCall: () => Promise<void>;
  endCall: () => void;
  /** Start when idle, barge in when the assistant is mid-sentence. */
  orbTap: () => void;
  /** Type instead of speaking. Essential where STT is unsupported. */
  send: (text: string) => void;
}

export function useVoiceCall(adapter: VoiceCallAdapter): VoiceCall {
  const [state, setState] = useState<CallState>("idle");
  const [ended, setEnded] = useState(false);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const stateRef = useRef<CallState>("idle");
  stateRef.current = state;
  const silenceStreakRef = useRef(0);
  // When the current uninterrupted silent stretch began. Reset on any real
  // activity, so "45 seconds" means 45 seconds since the candidate last did
  // something — not 45 seconds since the call started.
  const silenceSinceRef = useRef(Date.now());
  // The adapter is captured in callbacks that outlive the render they were
  // made in; a ref keeps those on the current one without restarting the call
  // every time a parent re-renders with a fresh object literal.
  const adapterRef = useRef(adapter);
  adapterRef.current = adapter;

  const { sttSupported, ttsSupported, startListening, stopListening, speak } = useVoice(
    (transcript) => handleTranscript(transcript),
    () => handleSilence(),
  );

  useEffect(
    () => () => {
      abortRef.current?.();
      stopListening();
      window.speechSynthesis?.cancel();
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

  /** Begin (or resume) waiting on the candidate, starting a fresh silence
   * window. Speaking a long reply must not eat into their thinking time, so the
   * clock starts here rather than when the reply was requested. */
  function resumeListening() {
    silenceSinceRef.current = Date.now();
    if (sttSupported) {
      setState("listening");
      startListening();
    } else {
      setState("idle");
    }
  }

  function afterReply(fullText: string) {
    if (ttsSupported) {
      setState("speaking");
      speak(fullText, resumeListening);
    } else {
      resumeListening();
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

  function handleSilence() {
    // Only relevant while we were actively waiting on the user — ignore
    // stray onend firings from a mic that was stopped for another reason.
    if (stateRef.current !== "listening") return;

    // The candidate hasn't been quiet long enough to be treated as gone. Re-arm
    // the mic without saying anything — this is someone thinking, not someone
    // who left.
    if (Date.now() - silenceSinceRef.current < SILENCE_BEFORE_CHECK_IN_MS) {
      if (sttSupported) startListening();
      return;
    }

    silenceStreakRef.current += 1;
    if (silenceStreakRef.current < MAX_CHECK_INS) {
      const line = CHECK_IN_LINES[Math.floor(Math.random() * CHECK_IN_LINES.length)];
      addCaption("assistant", line);
      setState("speaking");
      // resumeListening restarts the clock, so the second check-in is another
      // full wait away rather than firing on the very next silent turn.
      speak(line, resumeListening);
    } else {
      const closing =
        "It looks like we've lost you — feel free to start the call again whenever you're ready.";
      addCaption("system", closing);
      finishCall(closing);
    }
  }

  function handleTranscript(text: string) {
    if (!sessionRef.current || stateRef.current === "thinking") return;
    silenceStreakRef.current = 0;
    silenceSinceRef.current = Date.now();
    addCaption("user", text);
    setState("thinking");
    let full = "";
    const captionId = addCaption("assistant", "");
    abortRef.current = adapterRef.current.ask(sessionRef.current, text, {
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

  async function startCall() {
    setState("connecting");
    setEnded(false);
    setCaptions([]);
    silenceStreakRef.current = 0;
    silenceSinceRef.current = Date.now();
    try {
      const sid = await adapterRef.current.createSession();
      sessionRef.current = sid;
      let full = "";
      const captionId = addCaption("assistant", "");
      setState("thinking");
      abortRef.current = adapterRef.current.greet(sid, {
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
    silenceStreakRef.current = 0;
    silenceSinceRef.current = Date.now();
    setState("idle");
  }

  function orbTap() {
    if (state === "idle") {
      void startCall();
    } else if (state === "speaking") {
      // barge-in: cut the reply short and start listening immediately
      window.speechSynthesis?.cancel();
      resumeListening();
    }
  }

  function send(text: string) {
    const trimmed = text.trim();
    if (trimmed) handleTranscript(trimmed);
  }

  return {
    state,
    ended,
    captions,
    active: state !== "idle",
    sttSupported,
    startCall,
    endCall,
    orbTap,
    send,
  };
}
