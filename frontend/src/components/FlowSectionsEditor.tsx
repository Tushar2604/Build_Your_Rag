// Conversational Flow editor: the system prompt as an ordered list of named,
// individually toggleable sections rather than one opaque textarea.
//
// Reordering is offered two ways on purpose — a drag handle (what people reach
// for) and move up/down buttons (keyboard- and screen-reader-reachable, since
// HTML5 drag-and-drop is neither).
import { useState } from "react";
import { ChevronDown, GripVertical, Plus, Trash2 } from "lucide-react";
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

function Toggle({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onClick}
      className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] font-bold uppercase
                  tracking-wide transition-colors ${
                    on ? "bg-brand-500/10 text-brand-400" : "bg-gray-100 text-gray-500"
                  }`}
    >
      {on ? "On" : "Off"}
      <span
        className={`block w-8 h-[18px] rounded-full relative transition-colors ${
          on ? "bg-brand-500" : "bg-gray-300"
        }`}
      >
        <span
          className={`absolute top-[3px] w-3 h-3 rounded-full bg-white transition-all ${
            on ? "left-[17px]" : "left-[3px]"
          }`}
        />
      </span>
    </button>
  );
}

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
            sections — or use Ask AI in the header to have one written from a
            description instead.
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
          rows={12}
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
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs text-gray-500">
          {sections.length} section{sections.length !== 1 ? "s" : ""} ·{" "}
          <span className={enabledCount === 0 ? "text-red-600 font-medium" : ""}>
            {enabledCount} active
          </span>
        </p>
        <button
          type="button"
          onClick={add}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-surface
                     px-3.5 py-2 text-[13px] font-medium text-gray-700 transition-colors
                     hover:bg-gray-100 hover:text-gray-900"
        >
          <Plus className="w-4 h-4" strokeWidth={2} />
          Add Section
        </button>
      </div>

      {enabledCount === 0 && (
        <div role="alert" className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
          Every section is off or empty. Saving now restores the stock prompt —
          an assistant with no instructions would answer unguarded.
        </div>
      )}

      <ul className="space-y-3">
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
              className={`rounded-xl border bg-surface transition ${
                dragIndex === index ? "opacity-50 border-brand-500" : "border-gray-200"
              }`}
            >
              <div className="flex items-center gap-2 p-3">
                <button
                  type="button"
                  onClick={() => toggleExpanded(index)}
                  aria-expanded={isOpen}
                  aria-label={isOpen ? `Collapse ${section.title}` : `Expand ${section.title}`}
                  className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:text-gray-900"
                >
                  <ChevronDown
                    className={`w-4 h-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
                    strokeWidth={2}
                  />
                </button>

                <span
                  className="cursor-grab select-none text-gray-500 hover:text-gray-800"
                  aria-hidden="true"
                  title="Drag to reorder"
                >
                  <GripVertical className="w-4 h-4" strokeWidth={2} />
                </span>

                <span className="text-[13px] font-semibold tabular-nums text-gray-600 w-5 text-right">
                  {index + 1}.
                </span>

                <input
                  className="input flex-1 h-9 text-[14px] font-semibold bg-surface-2"
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
                    className="w-6 h-6 text-xs text-gray-500 hover:text-gray-900 disabled:opacity-30"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, index + 1)}
                    disabled={index === sections.length - 1}
                    aria-label={`Move ${section.title} down`}
                    className="w-6 h-6 text-xs text-gray-500 hover:text-gray-900 disabled:opacity-30"
                  >
                    ↓
                  </button>
                </div>

                <Toggle
                  on={section.enabled}
                  onClick={() => patch(index, { enabled: !section.enabled })}
                  label={`${section.title} enabled`}
                />

                <button
                  type="button"
                  onClick={() => remove(index)}
                  aria-label={`Delete ${section.title}`}
                  className="w-8 h-8 flex items-center justify-center rounded text-gray-500 hover:text-red-500"
                >
                  <Trash2 className="w-4 h-4" strokeWidth={1.75} />
                </button>
              </div>

              {isOpen && (
                <div className="px-4 pb-4">
                  <textarea
                    className="input resize-y text-[13px] leading-relaxed bg-surface-2 rounded-lg"
                    rows={8}
                    value={section.body}
                    maxLength={MAX_BODY}
                    aria-label={`Section ${index + 1} instructions`}
                    placeholder="What should the assistant do in this part of the conversation?"
                    onChange={(e) => patch(index, { body: e.target.value })}
                  />
                  <p className="text-[10px] text-gray-500 text-right mt-1 tabular-nums">
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
        className="mt-4 text-xs text-gray-500 hover:text-gray-800 underline"
      >
        Reset to the stock flow
      </button>
    </div>
  );
}
