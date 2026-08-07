// Conversational Flow editor: the system prompt as an ordered list of named,
// individually toggleable sections rather than one opaque textarea.
//
// Reordering is offered two ways on purpose — a drag handle (what people reach
// for) and move up/down buttons (keyboard- and screen-reader-reachable, since
// HTML5 drag-and-drop is neither).
import { useState } from "react";
import { FlowSection } from "../api/chatbots";

interface Props {
  sections: FlowSection[];
  onChange: (sections: FlowSection[]) => void;
  /** Used when `sections` is empty — the raw-prompt escape hatch. */
  rawPrompt: string;
  onRawPromptChange: (prompt: string) => void;
  /** Loads the stock section set (server-side); also converts a raw-prompt bot. */
  onUseSections: () => void;
  busy?: boolean;
}

const MAX_BODY = 6000;

export default function FlowSectionsEditor({
  sections,
  onChange,
  rawPrompt,
  onRawPromptChange,
  onUseSections,
  busy = false,
}: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  function toggleExpanded(index: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(index) ? next.delete(index) : next.add(index);
      return next;
    });
  }

  function patch(index: number, changes: Partial<FlowSection>) {
    onChange(sections.map((s, i) => (i === index ? { ...s, ...changes } : s)));
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= sections.length || from === to) return;
    const next = [...sections];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
    // Expansion is tracked by position, so it has to travel with the row.
    setExpanded((prev) => {
      const shifted = new Set<number>();
      prev.forEach((i) => {
        if (i === from) shifted.add(to);
        else if (from < i && i <= to) shifted.add(i - 1);
        else if (to <= i && i < from) shifted.add(i + 1);
        else shifted.add(i);
      });
      return shifted;
    });
  }

  function remove(index: number) {
    onChange(sections.filter((_, i) => i !== index));
    setExpanded(new Set());
  }

  function add() {
    onChange([...sections, { title: "New section", body: "", enabled: true }]);
    setExpanded((prev) => new Set(prev).add(sections.length));
  }

  const enabledCount = sections.filter((s) => s.enabled && s.body.trim()).length;

  /* ── Raw-prompt mode ── */
  if (sections.length === 0) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
          <p className="text-sm text-amber-900 font-medium">
            This assistant uses a single raw prompt.
          </p>
          <p className="text-xs text-amber-800 mt-1">
            Switch to Conversational Flow to reorder behaviours and toggle them
            individually. Your current prompt will be replaced by the stock
            sections.
          </p>
          <button
            type="button"
            onClick={onUseSections}
            disabled={busy}
            className="btn-secondary text-xs px-3 py-1.5 h-auto mt-3"
          >
            {busy ? "Loading…" : "Use Conversational Flow"}
          </button>
        </div>
        <textarea
          className="input resize-none text-xs leading-relaxed"
          rows={10}
          value={rawPrompt}
          onChange={(e) => onRawPromptChange(e.target.value)}
          maxLength={40000}
        />
        <p className="text-xs text-gray-400 text-right">{rawPrompt.length} characters</p>
      </div>
    );
  }

  /* ── Section mode ── */
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          {sections.length} section{sections.length !== 1 ? "s" : ""} ·{" "}
          <span className={enabledCount === 0 ? "text-red-600 font-medium" : ""}>
            {enabledCount} active
          </span>
        </p>
        <button
          type="button"
          onClick={add}
          className="btn-secondary text-xs px-3 py-1.5 h-auto"
        >
          + Add Section
        </button>
      </div>

      {enabledCount === 0 && (
        <div role="alert" className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
          Every section is off or empty. Saving now restores the stock prompt —
          an assistant with no instructions would answer unguarded.
        </div>
      )}

      <ul className="space-y-2">
        {sections.map((section, index) => {
          const isOpen = expanded.has(index);
          return (
            <li
              key={section.id ?? `new-${index}`}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragIndex !== null) move(dragIndex, index);
                setDragIndex(null);
              }}
              onDragEnd={() => setDragIndex(null)}
              className={`rounded-lg border bg-white transition ${
                dragIndex === index ? "opacity-50 border-brand-400" : "border-gray-200"
              } ${section.enabled ? "" : "bg-gray-50"}`}
            >
              <div className="flex items-center gap-2 p-2">
                <button
                  type="button"
                  onClick={() => toggleExpanded(index)}
                  aria-expanded={isOpen}
                  aria-label={isOpen ? "Collapse section" : "Expand section"}
                  className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-700 rounded"
                >
                  <span className={`transition-transform inline-block ${isOpen ? "rotate-90" : ""}`}>
                    ›
                  </span>
                </button>

                <span
                  className="cursor-grab select-none text-gray-300 hover:text-gray-500 px-1"
                  aria-hidden="true"
                  title="Drag to reorder"
                >
                  ⠿
                </span>

                <span className="text-xs tabular-nums text-gray-400 w-5 text-right">
                  {index + 1}.
                </span>

                <input
                  className="input flex-1 h-8 text-sm"
                  value={section.title}
                  maxLength={120}
                  aria-label={`Section ${index + 1} title`}
                  onChange={(e) => patch(index, { title: e.target.value })}
                />

                <div className="flex items-center gap-0.5">
                  <button
                    type="button"
                    onClick={() => move(index, index - 1)}
                    disabled={index === 0}
                    aria-label={`Move ${section.title} up`}
                    className="w-6 h-6 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:hover:text-gray-400"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, index + 1)}
                    disabled={index === sections.length - 1}
                    aria-label={`Move ${section.title} down`}
                    className="w-6 h-6 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 disabled:hover:text-gray-400"
                  >
                    ↓
                  </button>
                </div>

                <button
                  type="button"
                  role="switch"
                  aria-checked={section.enabled}
                  aria-label={`${section.title} enabled`}
                  onClick={() => patch(index, { enabled: !section.enabled })}
                  className={`flex items-center gap-1.5 rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                    section.enabled
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-gray-200 text-gray-500"
                  }`}
                >
                  {section.enabled ? "On" : "Off"}
                  <span
                    className={`block w-6 h-3 rounded-full relative transition ${
                      section.enabled ? "bg-emerald-500" : "bg-gray-400"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 w-2 h-2 rounded-full bg-white transition-all ${
                        section.enabled ? "left-3.5" : "left-0.5"
                      }`}
                    />
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => remove(index)}
                  aria-label={`Delete ${section.title}`}
                  className="w-7 h-7 flex items-center justify-center text-gray-300 hover:text-red-600 rounded"
                >
                  🗑
                </button>
              </div>

              {isOpen && (
                <div className="px-3 pb-3 pl-12">
                  <textarea
                    className="input resize-y text-xs leading-relaxed"
                    rows={6}
                    value={section.body}
                    maxLength={MAX_BODY}
                    aria-label={`Section ${index + 1} instructions`}
                    placeholder="What should the assistant do in this part of the conversation?"
                    onChange={(e) => patch(index, { body: e.target.value })}
                  />
                  <p className="text-[10px] text-gray-400 text-right mt-1 tabular-nums">
                    {section.body.length}/{MAX_BODY}
                  </p>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        onClick={onUseSections}
        disabled={busy}
        className="text-xs text-gray-400 hover:text-gray-700 underline"
      >
        Reset to the stock flow
      </button>
    </div>
  );
}
