// The flow being written, live.
//
// Generation takes several seconds, and a spinner over that window tells you
// nothing about what the machine decided. Streaming the sections as they are
// authored turns the wait into the explanation: you watch it name the
// assistant, state the facts, draw its limits, then lay out each branch of the
// conversation — and each one landing is a natural moment to notice one is
// wrong.
//
// The reveal is deliberately fast. This is "watch it think", not a typewriter
// affectation, so text arrives quicker than anyone reads it and the eye follows
// the structure rather than individual characters.
import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Sparkles } from "lucide-react";

export interface WritingSection {
  title: string;
  body: string;
}

interface Props {
  name: string;
  welcomeMessage: string;
  sections: WritingSection[];
  /** False once the stream ends — the caret stops and the header settles. */
  writing: boolean;
}

/** Characters revealed per tick. A whole line at a time reads as "fast", where
 * one char at a time reads as "slow computer". */
const CHARS_PER_TICK = 14;
const TICK_MS = 16;

/** Reveals `text` quickly, then holds it. Restarts only when `text` changes. */
function useFastReveal(text: string, enabled: boolean): string {
  const [shown, setShown] = useState(enabled ? "" : text);

  useEffect(() => {
    if (!enabled) {
      setShown(text);
      return;
    }
    setShown("");
    let i = 0;
    const timer = setInterval(() => {
      i += CHARS_PER_TICK;
      if (i >= text.length) {
        setShown(text);
        clearInterval(timer);
        return;
      }
      setShown(text.slice(0, i));
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [text, enabled]);

  return shown;
}

function SectionCard({
  section,
  index,
  isNewest,
}: {
  section: WritingSection;
  index: number;
  isNewest: boolean;
}) {
  // Only the section still arriving animates; earlier ones are settled text, so
  // re-revealing them on every render would make the list flicker.
  const body = useFastReveal(section.body, isNewest);
  const complete = body.length === section.body.length;

  return (
    <li className="rounded-xl border border-gray-200 bg-surface overflow-hidden animate-slide-up">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-100">
        <span className="text-[13px] font-semibold tabular-nums text-gray-500 w-5 text-right">
          {index + 1}.
        </span>
        <span className="text-[14px] font-semibold text-gray-900 flex-1 truncate">
          {section.title}
        </span>
        {complete ? (
          <Check className="w-4 h-4 text-brand-400" strokeWidth={2.5} />
        ) : (
          <Loader2 className="w-3.5 h-3.5 text-brand-400 animate-spin" strokeWidth={2} />
        )}
      </div>
      <p className="px-4 py-3 text-[13px] leading-relaxed text-gray-600 whitespace-pre-wrap">
        {body}
        {!complete && <span className="inline-block w-1.5 h-3.5 bg-brand-400 ml-0.5 align-middle animate-pulse" />}
      </p>
    </li>
  );
}

export default function FlowWritingView({ name, welcomeMessage, sections, writing }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest section in view as it arrives.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [sections.length]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2.5">
        <span className="w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center flex-shrink-0">
          {writing ? (
            <Loader2 className="w-4 h-4 text-brand-400 animate-spin" strokeWidth={2} />
          ) : (
            <Sparkles className="w-4 h-4 text-brand-400" strokeWidth={2} />
          )}
        </span>
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-gray-900 truncate">
            {name || "Designing your assistant…"}
          </p>
          <p className="text-xs text-gray-500">
            {writing
              ? `Writing the conversational flow — ${sections.length} section${sections.length === 1 ? "" : "s"} so far`
              : `${sections.length} sections written. Opening the builder…`}
          </p>
        </div>
      </div>

      {welcomeMessage && (
        <div className="rounded-xl border border-brand-500/25 bg-brand-500/[0.05] px-4 py-3 animate-slide-up">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-brand-400 mb-1">
            Welcome message
          </p>
          <p className="text-[13.5px] text-gray-800 leading-relaxed">{welcomeMessage}</p>
        </div>
      )}

      <ul className="space-y-2.5">
        {sections.map((section, i) => (
          <SectionCard
            key={`${section.title}-${i}`}
            section={section}
            index={i}
            isNewest={writing && i === sections.length - 1}
          />
        ))}
      </ul>

      {writing && sections.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-surface px-4 py-6 text-center">
          <Loader2 className="w-5 h-5 text-brand-400 animate-spin mx-auto" strokeWidth={2} />
          <p className="text-[13px] text-gray-500 mt-2.5">
            Reading your description and deciding what this assistant needs…
          </p>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}
