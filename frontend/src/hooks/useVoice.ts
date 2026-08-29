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

/**
 * The assistant's configured language, as a BCP-47 tag.
 *
 * Speech recognition needs this BEFORE anyone speaks — a recogniser set to
 * `en-US` does not transcribe Hindi badly, it transcribes it as nonsense
 * English, and no amount of downstream prompting recovers from that. Which is
 * why the language lives on the assistant rather than being detected: there is
 * nothing to detect until the first word has already been misheard.
 */
/**
 * The assistant's configured language label -> a BCP-47 tag.
 *
 * The labels come from `LANGUAGE_OPTIONS` in the domain and are written for
 * people ("English (India)"), while both speech APIs want tags. Kept here
 * beside the two functions that consume them so a new option added to the
 * domain has one obvious place to be taught.
 */
const LANGUAGE_TAGS: Record<string, string> = {
  "English (India)": "en-IN",
  "English (US)": "en-US",
  "English (UK)": "en-GB",
  Hindi: "hi-IN",
  Spanish: "es-ES",
  French: "fr-FR",
  German: "de-DE",
  Portuguese: "pt-BR",
  Arabic: "ar-SA",
  Japanese: "ja-JP",
};

/** The tag for an assistant's configured languages. The first is the one the
 * recogniser is set to — it has to pick one before anybody speaks, and the
 * assistant's primary language is the best available guess. */
export function voiceTagFor(languages: string[] | undefined): string {
  for (const label of languages ?? []) {
    const tag = LANGUAGE_TAGS[label];
    if (tag) return tag;
  }
  return "en-US";
}

/** Script ranges that identify a language on sight. Only scripts one language
 * uses in practice are listed — Latin is deliberately absent, because it is
 * shared by dozens and guessing between them from characters alone is how you
 * end up reading Spanish in a German accent. */
const SCRIPTS: { re: RegExp; lang: string }[] = [
  { re: /[\u0900-\u097F]/, lang: "hi-IN" },   // Devanagari
  { re: /[\u0600-\u06FF]/, lang: "ar-SA" },   // Arabic
  { re: /[\u3040-\u30FF]/, lang: "ja-JP" },   // Kana
  { re: /[\u0980-\u09FF]/, lang: "bn-IN" },   // Bengali
  { re: /[\u0C00-\u0C7F]/, lang: "te-IN" },   // Telugu
  { re: /[\u0B80-\u0BFF]/, lang: "ta-IN" },   // Tamil
  { re: /[\u0A80-\u0AFF]/, lang: "gu-IN" },   // Gujarati
  { re: /[\u0400-\u04FF]/, lang: "ru-RU" },   // Cyrillic
  { re: /[\uAC00-\uD7AF]/, lang: "ko-KR" },   // Hangul
  { re: /[\u4E00-\u9FFF]/, lang: "zh-CN" },   // Han
];

/** The language of a reply, from its script. Returns "" for Latin text, where
 * the caller falls back to the assistant's configured language rather than
 * guessing. */
export function detectLang(text: string): string {
  for (const { re, lang } of SCRIPTS) if (re.test(text)) return lang;
  return "";
}

/** The closest installed voice for a tag. Exact match first, then any voice
 * for the same base language — `hi-IN` is worth speaking with a `hi` voice,
 * and far better than the browser default reading Hindi as English. */
function pickVoice(tag: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis?.getVoices?.() ?? [];
  if (!voices.length) return undefined;
  const base = tag.split("-")[0].toLowerCase();
  return (
    voices.find((v) => v.lang.toLowerCase() === tag.toLowerCase()) ||
    voices.find((v) => v.lang.toLowerCase().startsWith(base + "-")) ||
    voices.find((v) => v.lang.toLowerCase() === base)
  );
}

export function useVoice(
  onTranscript: (text: string) => void,
  onSilence?: () => void,
  storageKey = "kore:voiceMode",
  lang = "en-US",
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
    // Was hardcoded to en-US, which made every non-English assistant deaf.
    rec.lang = lang;
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
      // What the reply is actually written in beats what the assistant is
      // configured for: a caller can switch language mid-call and the answer
      // follows them, so the voice has to follow the answer.
      const spoken = detectLang(text) || lang;
      utter.lang = spoken;
      const match = pickVoice(spoken);
      if (match) utter.voice = match;
      if (onEnd) {
        utter.onend = onEnd;
        utter.onerror = onEnd;
      }
      window.speechSynthesis.speak(utter);
    },
    [ttsSupported, lang],
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
