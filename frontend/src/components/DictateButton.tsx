// The mic button that sits on a text field. Press, speak, and the words land
// in the field — the same gesture as dictating to ChatGPT or Claude.
//
// It owns the append, not the caller. Every field it attaches to wants the
// same rule (add to what is already typed, with exactly one separating space,
// respecting a trailing newline), and leaving that to each call site is how
// six fields end up with five behaviours.
//
// Renders nothing when no engine is available (Firefox with dictation
// unconfigured on the server). A dead mic button is worse than no mic button:
// it advertises a capability and then does nothing when pressed.
import { Loader2, Mic, Square } from "lucide-react";

import { useDictation } from "../hooks/useDictation";

interface Props {
  /** Current field text. */
  value: string;
  /** Called with the field's new text, dictation appended. */
  onChange: (next: string) => void;
  /** ISO-639-1 hint passed to the recogniser. */
  language?: string;
  /** "sm" for inline composers, "md" for standalone fields. */
  size?: "sm" | "md";
  /** Hides the floating live-transcript chip on cramped layouts. */
  showInterim?: boolean;
  /** False on unauthenticated pages — see useDictation's `allowServer`. */
  allowServer?: boolean;
  disabled?: boolean;
  className?: string;
}

/** One space between what was typed and what was said — unless the field is
 * empty or already ends in whitespace, where adding one would be wrong. */
export function appendDictated(current: string, addition: string): string {
  const text = addition.trim();
  if (!text) return current;
  if (!current) return text;
  return /\s$/.test(current) ? current + text : `${current} ${text}`;
}

export default function DictateButton({
  value, onChange, language = "en", size = "md",
  showInterim = true, allowServer = true, disabled = false, className = "",
}: Props) {
  const dictation = useDictation(
    (text) => onChange(appendDictated(value, text)),
    language,
    allowServer,
  );

  // Probing the server engine resolves asynchronously; rendering nothing until
  // it settles avoids a button that pops into existence a beat late.
  if (!dictation.ready || dictation.engine === "none") return null;

  const listening = dictation.state === "listening";
  const busy = dictation.state === "transcribing";
  const dim = size === "sm" ? "h-7 w-7" : "h-9 w-9";
  const icon = size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4";

  const label = listening
    ? "Stop dictating"
    : busy
      ? "Transcribing…"
      : dictation.engine === "server"
        ? "Dictate (records, then transcribes)"
        : "Dictate";

  return (
    <span className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={dictation.toggle}
        disabled={disabled || busy}
        aria-label={label}
        aria-pressed={listening}
        title={dictation.error || label}
        className={`${dim} inline-flex flex-shrink-0 items-center justify-center rounded-full
                    transition-all duration-200 disabled:opacity-50 disabled:pointer-events-none ${
          listening
            ? // Red while live, and pulsing: an open microphone must never be
              // something you can leave running without noticing.
              "bg-red-500 text-white shadow-[0_0_0_4px_rgba(239,68,68,0.18)] animate-pulse"
            : busy
              ? "bg-brand-500/15 text-brand-600"
              : "bg-brand-500/10 text-brand-600 hover:bg-brand-500/20 hover:text-brand-700"
        }`}
      >
        {busy ? (
          <Loader2 className={`${icon} animate-spin`} strokeWidth={2} />
        ) : listening ? (
          <Square className={icon} strokeWidth={2.5} fill="currentColor" />
        ) : (
          <Mic className={icon} strokeWidth={2} />
        )}
      </button>

      {/* Live preview of words not yet committed. Floats above the button
          rather than entering the field, so the text you can see is only ever
          text that will actually stay. */}
      {showInterim && listening && dictation.interim && (
        <span
          className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 max-w-[260px]
                     truncate rounded-lg bg-ink-950/90 px-2.5 py-1.5 text-[11.5px]
                     text-white shadow-lg backdrop-blur-sm"
        >
          {dictation.interim}
        </span>
      )}

      {dictation.error && !listening && !busy && (
        <span
          role="alert"
          onClick={dictation.clearError}
          className="absolute bottom-full right-0 z-20 mb-2 max-w-[260px] cursor-pointer
                     rounded-lg bg-red-600 px-2.5 py-1.5 text-[11.5px] text-white shadow-lg"
        >
          {dictation.error}
        </span>
      )}
    </span>
  );
}
