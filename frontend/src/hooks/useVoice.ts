// Browser-native voice mode: speech-to-text (dictate a message) and
// text-to-speech (hear replies read aloud). Zero backend/infra cost — uses the
// Web Speech API directly, so it silently disables itself on browsers that
// don't support it (Safari/Firefox have weak or no SpeechRecognition support).
//
// Not wired to any chat transport — callers decide what to do with a
// transcript (populate + send a message) and when to speak (e.g. once a
// streamed reply finishes).

import { useCallback, useEffect, useRef, useState } from "react";

function getSpeechRecognitionCtor(): any {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

// How long to wait after the candidate/user stops speaking before we treat
// the utterance as finished and hand it off. The browser's own built-in
// endpointing (used when interimResults=false) is inconsistent across
// browsers/sessions — on some machines a second recognition session in the
// same page never finalizes at all, which is exactly the "keeps on
// listening forever" bug this replaces. Driving our own pause-detection off
// interim results (continuous mode) fixes that and gives predictable,
// tunable behavior. Also doubles as the "the user hasn't said anything at
// all" check-in threshold, per the user's explicit "~5 seconds" ask.
const SILENCE_TIMEOUT_MS = 5000;

export function useVoice(
  onTranscript: (text: string) => void,
  onSilence?: () => void,
  storageKey = "kore:voiceMode",
) {
  const SpeechRecognitionCtor = getSpeechRecognitionCtor();
  const sttSupported = !!SpeechRecognitionCtor;
  const ttsSupported = typeof window !== "undefined" && "speechSynthesis" in window;

  const [listening, setListening] = useState(false);
  const [voiceMode, setVoiceModeState] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });
  const recognitionRef = useRef<any>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const onSilenceRef = useRef(onSilence);
  onSilenceRef.current = onSilence;

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const setVoiceMode = useCallback(
    (value: boolean) => {
      setVoiceModeState(value);
      try {
        window.localStorage.setItem(storageKey, value ? "1" : "0");
      } catch {
        // ignore (private browsing, storage disabled, etc.)
      }
      if (!value) window.speechSynthesis?.cancel();
    },
    [storageKey],
  );

  const startListening = useCallback(() => {
    if (!sttSupported || listening) return;
    const rec = new SpeechRecognitionCtor();
    rec.lang = "en-US";
    // continuous + interim results so WE control when an utterance is "done"
    // (a real pause in speech) instead of trusting the browser's own
    // endpointing, which is what was causing the mic to hang open forever
    // on repeat use.
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    let finalizedText = "";
    let latestInterim = "";
    let stopping = false;

    function armSilenceTimer() {
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        if (!stopping) {
          stopping = true;
          try {
            rec.stop();
          } catch {
            // already stopped
          }
        }
      }, SILENCE_TIMEOUT_MS);
    }

    rec.onresult = (e: any) => {
      armSilenceTimer();
      latestInterim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalizedText += chunk + " ";
        else latestInterim += chunk;
      }
    };
    rec.onerror = () => {
      stopping = true;
      clearSilenceTimer();
      setListening(false);
    };
    rec.onend = () => {
      stopping = true;
      clearSilenceTimer();
      setListening(false);
      const text = (finalizedText + " " + latestInterim).trim();
      if (text) onTranscriptRef.current(text);
      else onSilenceRef.current?.();
    };
    recognitionRef.current = rec;
    setListening(true);
    armSilenceTimer(); // in case the user never says anything at all
    rec.start();
  }, [SpeechRecognitionCtor, sttSupported, listening, clearSilenceTimer]);

  const stopListening = useCallback(() => {
    clearSilenceTimer();
    recognitionRef.current?.stop();
    setListening(false);
  }, [clearSilenceTimer]);

  const speak = useCallback(
    (text: string, onEnd?: () => void) => {
      if (!ttsSupported || !text.trim()) {
        onEnd?.();
        return;
      }
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      if (onEnd) {
        utter.onend = onEnd;
        utter.onerror = onEnd;
      }
      window.speechSynthesis.speak(utter);
    },
    [ttsSupported],
  );

  useEffect(
    () => () => {
      clearSilenceTimer();
      recognitionRef.current?.stop();
      window.speechSynthesis?.cancel();
    },
    [clearSilenceTimer],
  );

  return {
    sttSupported,
    ttsSupported,
    listening,
    startListening,
    stopListening,
    voiceMode,
    setVoiceMode,
    speak,
  };
}
