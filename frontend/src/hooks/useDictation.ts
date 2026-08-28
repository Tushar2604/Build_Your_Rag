// Dictation for ordinary text fields — the mic button next to a textarea.
//
// Deliberately a second hook rather than a widening of `useVoice`. That one
// drives a *conversation*: it owns a 5-second silence timeout, finalises once,
// and hands the whole utterance to a send() call. Dictation is the opposite
// shape — it runs until the user stops it, streams partial text as they speak,
// and never sends anything. Folding both into one hook would mean a flag on
// every branch, and the voice-call flow is the last thing worth destabilising.
//
// Two engines, picked per browser:
//
//   "browser" — the Web Speech API. Instant, free, live interim text. Chrome
//               and Edge only; Firefox has none and Safari's is unreliable.
//   "server"  — MediaRecorder captures a clip, /voices/transcribe returns text.
//               Works everywhere with a microphone, more accurate, but the
//               text only arrives once you stop talking.
//
// Browser first when available, because seeing words appear as you speak is
// most of what makes dictation feel like it is working.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { getTranscriptionStatus, transcribe } from "../api/voices";

export type DictationEngine = "browser" | "server" | "none";
export type DictationState = "idle" | "listening" | "transcribing";

/** Mirrors useAudioRecorder's list — Safari only does mp4. */
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

// Hard ceiling on one server-engine take. The browser engine has no equivalent
// because it streams: there is nothing accumulating that could get too large.
const SERVER_MAX_SECONDS = 120;

function speechRecognitionCtor(): any {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

function canRecord(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

export interface Dictation {
  /** Which engine will run, once probing finishes. "none" hides the button. */
  engine: DictationEngine;
  state: DictationState;
  /** Words heard but not yet final — for a live preview. Browser engine only. */
  interim: string;
  error: string | null;
  /** False until the server-engine probe settles, so the button can wait
   * rather than flicker from "none" to "available". */
  ready: boolean;
  start: () => void;
  stop: () => void;
  toggle: () => void;
  clearError: () => void;
}

/**
 * @param onText Called with each finished chunk of speech. Fires repeatedly on
 *   the browser engine (once per finalised phrase) and exactly once on the
 *   server engine. Callers append rather than replace — dictation adds to
 *   whatever is already typed.
 * @param language ISO-639-1 hint, e.g. "en".
 * @param allowServer Set false on unauthenticated surfaces (the public widget,
 *   the iframe embed). The transcribe endpoint needs a session, and probing it
 *   from a page that has none would fire a pointless 401 — which the shared API
 *   client treats as an expired session and answers with a redirect to /login.
 *   Those pages get the browser engine or no button at all.
 */
export function useDictation(
  onText: (text: string) => void,
  language = "en",
  allowServer = true,
): Dictation {
  const browserSupported = !!speechRecognitionCtor();

  const [engine, setEngine] = useState<DictationEngine>(
    browserSupported ? "browser" : "none",
  );
  const [state, setState] = useState<DictationState>("idle");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(browserSupported);

  const onTextRef = useRef(onText);
  onTextRef.current = onText;
  const recognitionRef = useRef<any>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const capRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Set when the user stops on purpose, so an auto-stop at the cap can be
  // told apart from a deliberate one.
  const stoppingRef = useRef(false);

  // Only probe the server when the browser can't do it itself — a Chrome user
  // never needs the round-trip, and the endpoint is authenticated, so asking
  // from a public widget would 401 for nothing.
  useEffect(() => {
    if (browserSupported) return;
    if (!allowServer) { setEngine("none"); setReady(true); return; }
    if (!canRecord()) { setEngine("none"); setReady(true); return; }

    let cancelled = false;
    getTranscriptionStatus()
      .then((s) => { if (!cancelled) setEngine(s.enabled ? "server" : "none"); })
      .catch(() => { if (!cancelled) setEngine("none"); })
      .finally(() => { if (!cancelled) setReady(true); });
    return () => { cancelled = true; };
  }, [browserSupported, allowServer]);

  const releaseMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (capRef.current) { clearTimeout(capRef.current); capRef.current = null; }
  }, []);

  // --- Browser engine ---

  const startBrowser = useCallback(() => {
    const Ctor = speechRecognitionCtor();
    if (!Ctor) return;

    const rec = new Ctor();
    rec.lang = language || "en-US";
    // Continuous so a pause mid-sentence doesn't end the take: someone
    // dictating a prompt thinks between clauses, and the browser's own
    // endpointing would cut them off every time.
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (e: any) => {
      let pending = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript;
        // Final chunks go straight to the field; interim ones only preview,
        // so the field never shows text that is about to be rewritten.
        if (e.results[i].isFinal) onTextRef.current(chunk.trim());
        else pending += chunk;
      }
      setInterim(pending);
    };
    rec.onerror = (e: any) => {
      const code = e?.error;
      if (code === "not-allowed" || code === "service-not-allowed") {
        setError("Microphone access was blocked. Allow it in your browser settings.");
      } else if (code === "no-speech") {
        setError("No speech was detected.");
      } else if (code !== "aborted") {
        setError("Dictation stopped unexpectedly. Try again.");
      }
      setInterim("");
      setState("idle");
    };
    rec.onend = () => {
      setInterim("");
      setState("idle");
      recognitionRef.current = null;
    };

    recognitionRef.current = rec;
    setError(null);
    setState("listening");
    rec.start();
  }, [language]);

  // --- Server engine ---

  const startServer = useCallback(async () => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      setError("Microphone access was blocked. Allow it in your browser settings.");
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];
    stoppingRef.current = false;

    const mimeType = MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = async () => {
      releaseMic();
      const clip = new Blob(chunksRef.current, {
        type: recorder.mimeType || mimeType || "audio/webm",
      });
      chunksRef.current = [];
      // Anything this short is a mis-click, not speech. Uploading it would
      // spend a round-trip to be told there was no speech in it.
      if (clip.size < 1200) { setState("idle"); return; }

      setState("transcribing");
      try {
        const text = await transcribe(clip, language);
        if (text) onTextRef.current(text.trim());
      } catch (e) {
        setError(
          e instanceof ApiError ? e.message : "Could not transcribe that recording.",
        );
      } finally {
        setState("idle");
      }
    };

    setState("listening");
    recorder.start();
    capRef.current = setTimeout(() => {
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    }, SERVER_MAX_SECONDS * 1000);
  }, [language, releaseMic]);

  // --- Public controls ---

  const start = useCallback(() => {
    if (state !== "idle" || engine === "none") return;
    if (engine === "browser") startBrowser();
    else void startServer();
  }, [state, engine, startBrowser, startServer]);

  const stop = useCallback(() => {
    stoppingRef.current = true;
    if (engine === "browser") {
      try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
      // onend clears the rest.
      return;
    }
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    else releaseMic();
  }, [engine, releaseMic]);

  const toggle = useCallback(() => {
    // Mid-transcription the button is busy, not a toggle — stopping would
    // discard a clip already on its way to the server.
    if (state === "listening") stop();
    else if (state === "idle") start();
  }, [state, start, stop]);

  const clearError = useCallback(() => setError(null), []);

  // Releasing the mic on unmount is what makes the browser's recording
  // indicator go away when someone navigates mid-dictation.
  useEffect(
    () => () => {
      try { recognitionRef.current?.stop(); } catch { /* ignore */ }
      if (recorderRef.current?.state === "recording") {
        try { recorderRef.current.stop(); } catch { /* ignore */ }
      }
      releaseMic();
    },
    [releaseMic],
  );

  return { engine, state, interim, error, ready, start, stop, toggle, clearError };
}
