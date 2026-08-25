// Clone Voice — build a custom AI voice from a recording or an uploaded file.
//
// The 20-second floor is enforced here (the Clone button stays disabled and the
// progress ring shows how far in you are) and again on the server, which also
// cross-checks the reported duration against the actual byte count.
import { useEffect, useRef, useState } from "react";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import {
  VoiceGender,
  VoiceOptions,
  VoiceProfile,
  createVoice,
  deleteVoice,
  fetchSampleUrl,
  getVoiceOptions,
  listVoices,
  retryClone,
  speakUrl,
} from "../api/voices";
import { ApiError } from "../api/client";

const PREVIEW_TEXT =
  "Hi, this is a preview of your cloned voice. It'll be used for spoken replies.";

const STATUS_STYLES: Record<VoiceProfile["status"], string> = {
  ready: "bg-emerald-100 text-emerald-700",
  pending: "bg-gray-100 text-gray-600",
  failed: "bg-red-100 text-red-700",
};

function fmt(seconds: number): string {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Circular progress toward the minimum, then toward the maximum. */
function RecordButton({
  recording,
  seconds,
  minSeconds,
  onClick,
}: {
  recording: boolean;
  seconds: number;
  minSeconds: number;
  onClick: () => void;
}) {
  const pct = Math.min(1, seconds / minSeconds);
  const R = 46;
  const circumference = 2 * Math.PI * R;
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative w-28 h-28 rounded-full flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
      aria-label={recording ? "Stop recording" : "Start recording"}
    >
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 100 100" aria-hidden="true">
        {/* Themed rather than hardcoded: a fixed light-grey track glares badly
            against the dark canvas. */}
        <circle cx="50" cy="50" r={R} fill="none" stroke="rgb(var(--c-gray-200))" strokeWidth="5" />
        <circle
          cx="50" cy="50" r={R} fill="none"
          stroke={pct >= 1 ? "rgb(var(--c-emerald-500))" : "rgb(var(--c-brand-500))"}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - pct)}
          style={{ transition: "stroke-dashoffset 200ms linear" }}
        />
      </svg>
      <span
        className={`w-16 h-16 rounded-full flex items-center justify-center text-2xl transition ${
          recording ? "bg-red-500 text-white animate-pulse" : "bg-brand-50 text-brand-700"
        }`}
      >
        {recording ? "■" : "🎙"}
      </span>
    </button>
  );
}

function VoiceRow({
  voice,
  onChanged,
}: {
  voice: VoiceProfile;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Revoke whatever object URL is playing when this row goes away.
  useEffect(
    () => () => {
      if (audioRef.current?.src.startsWith("blob:")) URL.revokeObjectURL(audioRef.current.src);
    },
    [],
  );

  async function play(getUrl: () => Promise<string>) {
    setBusy(true);
    setNote(null);
    try {
      const url = await getUrl();
      if (audioRef.current?.src.startsWith("blob:")) URL.revokeObjectURL(audioRef.current.src);
      const audio = new Audio(url);
      audioRef.current = audio;
      await audio.play();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Playback failed.");
    } finally {
      setBusy(false);
    }
  }

  async function run(action: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    setNote(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900">{voice.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_STYLES[voice.status]}`}>
              {voice.status}
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            {voice.gender} · {voice.language} · {fmt(voice.duration_seconds)}
            {voice.provider && ` · ${voice.provider}`}
          </p>
          {voice.description && (
            <p className="text-xs text-gray-500 mt-1">{voice.description}</p>
          )}
          {voice.error && (
            <p className="text-xs text-red-600 mt-1">{voice.error}</p>
          )}
          {note && <p className="text-xs text-amber-700 mt-1">{note}</p>}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            disabled={busy}
            onClick={() => play(() => fetchSampleUrl(voice.id))}
            className="btn-secondary text-xs px-3 py-1.5 h-auto"
          >
            Sample
          </button>
          {voice.status === "ready" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => play(() => speakUrl(voice.id, PREVIEW_TEXT))}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Preview
            </button>
          )}
          {voice.status === "failed" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => retryClone(voice.id), "Retry failed.")}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Retry
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => deleteVoice(voice.id), "Delete failed.")}
            className="text-xs text-gray-400 hover:text-red-600 px-2"
            aria-label={`Delete ${voice.name}`}
          >
            Delete
          </button>
        </div>
      </div>
    </li>
  );
}

export default function CloneVoicePage() {
  const [options, setOptions] = useState<VoiceOptions | null>(null);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [mode, setMode] = useState<"record" | "upload">("record");

  const [name, setName] = useState("");
  const [gender, setGender] = useState<VoiceGender>("female");
  const [language, setLanguage] = useState("en");
  const [description, setDescription] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [fileSeconds, setFileSeconds] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const maxSeconds = options?.max_seconds ?? 300;
  const minSeconds = options?.min_seconds ?? 20;
  const recorder = useAudioRecorder(maxSeconds);

  async function load() {
    setVoices(await listVoices());
  }

  useEffect(() => {
    getVoiceOptions().then(setOptions).catch(() => setOptions(null));
    load().catch(() => setVoices([]));
  }, []);

  /** Read a picked file's real duration — an uploaded container usually has a
   * proper duration header, unlike a fresh MediaRecorder blob. */
  function onPickFile(picked: File | null) {
    setFile(picked);
    setFileSeconds(0);
    setError(null);
    if (!picked) return;
    const url = URL.createObjectURL(picked);
    const audio = new Audio(url);
    audio.addEventListener("loadedmetadata", () => {
      const d = audio.duration;
      setFileSeconds(Number.isFinite(d) ? d : 0);
      URL.revokeObjectURL(url);
    });
    audio.addEventListener("error", () => {
      setError("That file doesn't look like readable audio.");
      URL.revokeObjectURL(url);
    });
  }

  const blob: Blob | null = mode === "record" ? recorder.blob : file;
  const seconds = mode === "record" ? recorder.seconds : fileSeconds;
  const longEnough = seconds >= minSeconds;
  const canSubmit = Boolean(blob) && longEnough && name.trim().length > 0 && !saving;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!blob) return;
    setSaving(true);
    setError(null);
    try {
      await createVoice({
        sample: blob,
        filename: mode === "upload" && file ? file.name : "recording.webm",
        name,
        gender,
        language,
        description,
        durationSeconds: seconds,
      });
      setName("");
      setDescription("");
      recorder.reset();
      setFile(null);
      setFileSeconds(0);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the voice.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-sm">
      <div className="page-header">
        <div>
          <h1 className="page-title">Clone Voice</h1>
          <p className="text-sm text-gray-500 mt-1">
            Create custom AI voices by uploading audio samples. Minimum{" "}
            {minSeconds} seconds, {minSeconds + 10}–60 seconds of clear speech
            recommended.
          </p>
        </div>
      </div>

      {options && !options.cloning_enabled && (
        <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800">
          Voice cloning isn't configured on this server (needs ELEVENLABS_API_KEY).
          You can still record and save samples — they'll show as <em>failed</em>{" "}
          with a Retry button that works once a key is set.
        </div>
      )}

      <form onSubmit={submit} className="card p-5 space-y-5">
        <div>
          <h2 className="section-title">Clone your voice</h2>
          <p className="text-xs text-gray-500 mt-1">
            Record from your microphone or upload a file. Speak clearly with
            minimal background noise.
          </p>
        </div>

        <div className="segmented inline-flex">
          <button
            type="button"
            onClick={() => setMode("record")}
            className={mode === "record" ? "segmented-item-active" : "segmented-item"}
          >
            🎙 Record Voice
          </button>
          <button
            type="button"
            onClick={() => setMode("upload")}
            className={mode === "upload" ? "segmented-item-active" : "segmented-item"}
          >
            ⬆ Upload File
          </button>
        </div>

        {mode === "record" ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 flex flex-col items-center">
            <RecordButton
              recording={recorder.state === "recording"}
              seconds={recorder.seconds}
              minSeconds={minSeconds}
              onClick={() => (recorder.state === "recording" ? recorder.stop() : recorder.start())}
            />
            <p className="text-sm font-medium text-gray-900 mt-4">
              {recorder.state === "recording"
                ? fmt(recorder.seconds)
                : recorder.state === "recorded"
                  ? `Recorded ${fmt(recorder.seconds)}`
                  : "Click to start recording"}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              {recorder.state === "recording"
                ? longEnough
                  ? "Long enough — stop whenever you're ready."
                  : `Keep going — ${Math.ceil(minSeconds - recorder.seconds)}s to go`
                : `Speak clearly · at least ${minSeconds} seconds`}
            </p>

            {recorder.blobUrl && (
              <div className="mt-4 w-full flex flex-col items-center gap-2">
                <audio controls src={recorder.blobUrl} className="w-full max-w-sm" />
                <button
                  type="button"
                  onClick={recorder.reset}
                  className="text-xs text-gray-400 hover:text-gray-700 underline"
                >
                  Record again
                </button>
              </div>
            )}

            {recorder.error && (
              <p role="alert" className="text-xs text-red-600 mt-3">{recorder.error}</p>
            )}

            <div className="flex gap-5 text-xs text-gray-400 mt-5">
              <span>🔇 Quiet room</span>
              <span>🎙 15–30 cm away</span>
              <span>🌊 Normal pace</span>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border-2 border-dashed border-gray-200 p-8 text-center">
            <input
              type="file"
              accept="audio/*"
              onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              className="text-sm"
            />
            {file && (
              <p className="text-xs text-gray-500 mt-3">
                {file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB
                {fileSeconds > 0 && ` · ${fmt(fileSeconds)}`}
              </p>
            )}
            {file && fileSeconds > 0 && !longEnough && (
              <p className="text-xs text-amber-700 mt-2">
                That clip is {fmt(fileSeconds)} — at least {minSeconds} seconds is
                needed for a usable clone.
              </p>
            )}
            <p className="text-xs text-gray-400 mt-3">
              Up to {options?.max_mb ?? 25} MB · mp3, wav, m4a, ogg, webm, flac
            </p>
          </div>
        )}

        <div>
          <label className="label">Voice name *</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., My Professional Voice"
            maxLength={80}
            required
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Gender *</label>
            <select
              className="input"
              value={gender}
              onChange={(e) => setGender(e.target.value as VoiceGender)}
            >
              {(options?.genders ?? []).map((g) => (
                <option key={g.value} value={g.value}>{g.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Language *</label>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {(options?.languages ?? []).map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="label">Description</label>
          <textarea
            className="input resize-none"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            placeholder="Describe this voice or its intended use…"
          />
        </div>

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <button type="submit" disabled={!canSubmit} className="btn-primary w-full">
          {saving
            ? "Cloning…"
            : !blob
              ? "Record or upload a sample first"
              : !longEnough
                ? `Need at least ${minSeconds} seconds`
                : "🎙 Clone Voice"}
        </button>
      </form>

      <div className="card p-5 mt-6">
        <h2 className="section-title mb-4">Your cloned voices</h2>
        {voices.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-3xl mb-2">🎙</div>
            <p className="text-sm font-medium text-gray-700">No cloned voices yet</p>
            <p className="text-xs text-gray-400 mt-1">
              Record or upload your first audio sample above to create a custom AI voice.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {voices.map((v) => (
              <VoiceRow key={v.id} voice={v} onChanged={() => void load()} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
