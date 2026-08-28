// Assistant Details — the tab you land on.
//
// Four stacked blocks, in the order you reason about an assistant: what it
// speaks and listens with (Assistant Settings), the first thing it says
// (Welcome Message), whether it can actually book (Appointments), and
// everything it does after that (Conversational Flow).
import { useEffect, useState } from "react";
import { AudioLines, Brain, CalendarCheck, Globe, Info, Mic } from "lucide-react";
import {
  AssistantConfig,
  AssistantOptions,
  Chatbot,
  FlowSection,
  getAssistantOptions,
  resetChatbotFlow,
} from "../../api/chatbots";
import { ApiError } from "../../api/client";
import FlowSectionsEditor from "../FlowSectionsEditor";

const MAX_WELCOME = 600;

interface Props {
  bot: Chatbot;
  /** Local draft state lives in the parent so the header's Save/Saved
   * indicator and this tab can never disagree about what is unsaved. */
  draft: Draft;
  onDraftChange: (patch: Partial<Draft>) => void;
  onReplaceBot: (bot: Chatbot) => void;
}

export interface Draft {
  name: string;
  assistant: AssistantConfig;
  sections: FlowSection[];
  rawPrompt: string;
}

/* ── One card in the Assistant Settings row ── */
function SettingCard({
  icon: Icon,
  label,
  value,
  options,
  onChange,
  hint,
}: {
  icon: typeof Globe;
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-surface-2 px-4 py-3.5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center">
          <Icon className="w-[17px] h-[17px] text-brand-400" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="text-[13px] font-semibold text-gray-900">{label}</p>
            <span title={hint} className="text-gray-500 cursor-help">
              <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
            </span>
          </div>
          <select
            aria-label={label}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="mt-1 w-full bg-transparent text-[13px] text-gray-500 border-0 p-0
                       focus:outline-none focus:text-gray-900 cursor-pointer"
          >
            {/* A value saved before an option was retired would otherwise vanish
                from the select and silently change on the next save. */}
            {!options.includes(value) && <option value={value}>{value}</option>}
            {options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

/* ── Languages: multi-select, rendered as chips ── */
function LanguagesCard({
  selected,
  options,
  onChange,
}: {
  selected: string[];
  options: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);

  function toggle(lang: string) {
    // The last language cannot be removed — an assistant with no language has
    // nothing to transcribe or speak in, and the backend would just re-add one.
    if (selected.includes(lang)) {
      if (selected.length === 1) return;
      onChange(selected.filter((l) => l !== lang));
    } else {
      onChange([...selected, lang]);
    }
  }

  return (
    <div className="relative rounded-xl border border-gray-200 bg-surface-2 px-4 py-3.5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center">
          <Globe className="w-[17px] h-[17px] text-brand-400" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="text-[13px] font-semibold text-gray-900">Languages</p>
            <span title="Languages the assistant can understand and speak." className="text-gray-500 cursor-help">
              <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
            </span>
          </div>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="mt-1 text-left text-[13px] text-gray-500 hover:text-gray-900 truncate w-full"
          >
            {selected.join(", ")}
          </button>
        </div>
      </div>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute z-20 left-3 right-3 top-full mt-1 max-h-56 overflow-y-auto rounded-lg
                          border border-gray-200 bg-surface shadow-modal py-1">
            {options.map((lang) => (
              <label
                key={lang}
                className="flex items-center gap-2.5 px-3 py-2 text-[13px] text-gray-700 cursor-pointer hover:bg-gray-100"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(lang)}
                  onChange={() => toggle(lang)}
                  className="w-3.5 h-3.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                />
                {lang}
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Small pill toggle used by the Welcome Message header ── */
function PillToggle({
  label,
  on,
  onChange,
  hint,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
  hint: string;
}) {
  return (
    <div className="flex items-center gap-2" title={hint}>
      <span className="text-[13px] text-gray-500">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={() => onChange(!on)}
        className={`block w-9 h-5 rounded-full relative transition-colors ${
          on ? "bg-brand-500" : "bg-gray-300"
        }`}
      >
        <span
          className={`absolute top-[3px] w-3.5 h-3.5 rounded-full bg-white transition-all ${
            on ? "left-[19px]" : "left-[3px]"
          }`}
        />
      </button>
    </div>
  );
}

export default function AssistantDetailsTab({ bot, draft, onDraftChange, onReplaceBot }: Props) {
  const [options, setOptions] = useState<AssistantOptions | null>(null);
  const [flowBusy, setFlowBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAssistantOptions().then(setOptions).catch(() => setOptions(null));
  }, []);

  function patchAssistant(patch: Partial<AssistantConfig>) {
    onDraftChange({ assistant: { ...draft.assistant, ...patch } });
  }

  /** Adopt the stock flow (server-side), then mirror the result locally. */
  async function useSections() {
    setFlowBusy(true);
    setError(null);
    try {
      const updated = await resetChatbotFlow(bot.id);
      onReplaceBot(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load the stock flow.");
    } finally {
      setFlowBusy(false);
    }
  }

  const a = draft.assistant;

  return (
    <div className="space-y-5">
      {/* ── Assistant Settings ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-center gap-1.5 mb-4">
          <h2 className="text-[15px] font-semibold text-gray-900">Assistant Settings</h2>
          <span
            title="How this assistant speaks, listens, and thinks. Changing these affects every call."
            className="text-gray-500 cursor-help"
          >
            <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
          </span>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <LanguagesCard
            selected={a.languages}
            options={options?.languages ?? a.languages}
            onChange={(languages) => patchAssistant({ languages })}
          />
          <SettingCard
            icon={Mic}
            label="Voice (TTS)"
            hint="The voice used to speak replies."
            value={a.tts_voice}
            options={options?.tts_voices ?? [a.tts_voice]}
            onChange={(tts_voice) => patchAssistant({ tts_voice })}
          />
          <SettingCard
            icon={Brain}
            label="AI Model (LLM)"
            hint="The model that decides what to say."
            value={a.llm_model}
            options={options?.llm_models ?? [a.llm_model]}
            onChange={(llm_model) => patchAssistant({ llm_model })}
          />
          <SettingCard
            icon={AudioLines}
            label="Transcription (STT)"
            hint="Converts what the caller says into text."
            value={a.stt_model}
            options={options?.stt_models ?? [a.stt_model]}
            onChange={(stt_model) => patchAssistant({ stt_model })}
          />
        </div>
      </section>

      {/* ── Welcome Message ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-center justify-between gap-4 mb-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-brand-500/10 flex items-center justify-center">
              <span className="text-brand-400 text-sm">💬</span>
            </span>
            <h2 className="text-[15px] font-semibold text-gray-900">Welcome Message</h2>
            <span
              title="The first thing the assistant says. Use [square_brackets] for values filled in from call data."
              className="text-gray-500 cursor-help"
            >
              <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
            </span>
          </div>
          <div className="flex items-center gap-5">
            <PillToggle
              label="Dynamic"
              on={a.welcome_dynamic}
              onChange={(welcome_dynamic) => patchAssistant({ welcome_dynamic })}
              hint="On: the model says this in its own words each call. Off: it is spoken word for word."
            />
            <PillToggle
              label="Interruptible"
              on={a.welcome_interruptible}
              onChange={(welcome_interruptible) => patchAssistant({ welcome_interruptible })}
              hint="Lets the caller talk over the greeting instead of waiting for it to finish."
            />
          </div>
        </div>

        <textarea
          value={a.welcome_message}
          onChange={(e) => patchAssistant({ welcome_message: e.target.value })}
          maxLength={MAX_WELCOME}
          rows={5}
          aria-label="Welcome message"
          placeholder="Hi [user_name], this is the team calling about your enquiry. Is now a good time to talk?"
          className="input resize-y text-[14px] leading-relaxed bg-surface-2 rounded-xl px-4 py-3"
        />
        <p className="text-[11px] text-gray-500 text-right mt-1 tabular-nums">
          {a.welcome_message.length}/{MAX_WELCOME}
        </p>
        {!a.welcome_message && (
          <p className="text-xs text-gray-500 -mt-1">
            Leave empty and the assistant opens the conversation itself, following
            its Conversational Flow.
          </p>
        )}
      </section>

      {/* ── Appointments ──
          Its own card rather than a row of switches beside the welcome message:
          this one changes what the assistant *is* — from something that answers
          questions to something that books real appointments — so it should not
          read as a formatting preference. */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 rounded-lg bg-brand-500/10 flex items-center justify-center">
                <CalendarCheck className="w-4 h-4 text-brand-400" strokeWidth={1.75} />
              </span>
              <h2 className="text-[15px] font-semibold text-gray-900">Appointments</h2>
            </div>
            <p className="text-xs text-gray-500 mt-1.5 ml-9 max-w-xl leading-relaxed">
              Let this assistant check real availability and book, reschedule or
              cancel appointments — on WhatsApp and in chat. It can only offer
              times the calendar actually has, and never says an appointment is
              booked unless it is.
            </p>
          </div>
          <div className="flex-shrink-0 pt-1">
            <PillToggle
              label={a.appointments_enabled ? "On" : "Off"}
              on={a.appointments_enabled}
              onChange={(appointments_enabled) => patchAssistant({ appointments_enabled })}
              hint="Gives this assistant the booking tools. Off: it answers from your knowledge base only."
            />
          </div>
        </div>

        {a.appointments_enabled && (
          // Named plainly, because a booking assistant with no services silently
          // has nothing to offer and the reason is not obvious from here.
          <p className="text-xs text-gray-500 mt-4 ml-9 rounded-lg bg-surface-2 px-3 py-2">
            Needs at least one location, one service with staff assigned, and
            opening hours — set those up under <strong>Appointments</strong> in
            the sidebar.
          </p>
        )}
      </section>

      {/* ── Conversational Flow ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-7 h-7 rounded-lg bg-brand-500/10 flex items-center justify-center">
            <span className="text-brand-400 text-sm">☰</span>
          </span>
          <h2 className="text-[15px] font-semibold text-gray-900">Conversational Flow</h2>
          <span
            title="The assistant's instructions, as ordered sections. Reorder them, switch one off to test a behaviour, or add a branch."
            className="text-gray-500 cursor-help"
          >
            <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
          </span>
        </div>
        <p className="text-xs text-gray-500 mb-4 ml-9">
          Sections run top to bottom. Switching one off removes it from the prompt
          without deleting it — no redeploy needed.
        </p>

        {error && (
          <div role="alert" className="mb-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <FlowSectionsEditor
          sections={draft.sections}
          onChange={(sections) => onDraftChange({ sections })}
          rawPrompt={draft.rawPrompt}
          onRawPromptChange={(rawPrompt) => onDraftChange({ rawPrompt })}
          onUseSections={useSections}
          busy={flowBusy}
        />
      </section>
    </div>
  );
}
