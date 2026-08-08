// Microphone capture for voice cloning.
//
// Duration is measured by a wall-clock timer rather than read off the recorded
// Blob: MediaRecorder's webm/opus output frequently carries no duration header
// until it's been fully decoded, so `new Audio(blob).duration` is `Infinity`
// right after recording. The timer is what the 20-second gate depends on, and
// it's what the server is told.
import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "recording" | "recorded" | "denied" | "unsupported";

// Ordered by preference; the first the browser accepts wins. Safari only does
// mp4, everything else prefers webm/opus.
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

export interface AudioRecorder {
  state: RecorderState;
  seconds: number;
  blob: Blob | null;
  blobUrl: string | null;
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
}

export function useAudioRecorder(maxSeconds: number): AudioRecorder {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const startedAtRef = useRef(0);
  // The auto-stop at maxSeconds fires from inside the interval, which closes
  // over `stop` — a ref avoids re-creating the callback every tick.
  const maxRef = useRef(maxSeconds);
  maxRef.current = maxSeconds;

  const cleanupStream = useCallback(() => {
    // Releases the mic so the browser's recording indicator goes away.
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
    cleanupStream();
  }, [cleanupStream]);

  const start = useCallback(async () => {
    setError(null);
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      setError("This browser can't record audio. Upload a file instead.");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      setState("denied");
      setError("Microphone access was blocked. Allow it in your browser, or upload a file.");
      return;
    }

    // Starting a new take invalidates the previous one.
    setBlobUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    setBlob(null);

    streamRef.current = stream;
    chunksRef.current = [];
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const recorded = new Blob(chunksRef.current, { type });
      setBlob(recorded);
      setBlobUrl(URL.createObjectURL(recorded));
      setState("recorded");
      // Trust the wall clock over the interval's tick count.
      setSeconds((Date.now() - startedAtRef.current) / 1000);
    };

    startedAtRef.current = Date.now();
    setSeconds(0);
    setState("recording");
    recorder.start();

    timerRef.current = setInterval(() => {
      const elapsed = (Date.now() - startedAtRef.current) / 1000;
      setSeconds(elapsed);
      if (elapsed >= maxRef.current) stop();
    }, 200);
  }, [stop]);

  const reset = useCallback(() => {
    stop();
    setBlobUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    setBlob(null);
    setSeconds(0);
    setState("idle");
    setError(null);
  }, [stop]);

  // Release the mic and the object URL if the page unmounts mid-recording.
  useEffect(
    () => () => {
      cleanupStream();
      setBlobUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return null;
      });
    },
    [cleanupStream],
  );

  return { state, seconds, blob, blobUrl, error, start, stop, reset };
}
