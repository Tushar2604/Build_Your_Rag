// Voice AI Assistants — the front door.
//
// Creation is one box: describe the assistant in prose, optionally pick a
// use-case chip, hit Create. The server's generator writes the name, the
// welcome message, and a Conversational Flow specific to that description, then
// drops you straight into the builder to edit it. There is no wizard, because
// every field a wizard would ask for is one the description already answers.
import { useState, useEffect, useRef, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowDownUp, ArrowUpRight, Bot, Brain, FileText, Mic, MoreVertical, Settings2, Sparkles,
  Trash2, Zap,
} from "lucide-react";
import {
  listChatbots,
  deleteChatbot,
  generateAssistantStream,
  getAssistantOptions,
  Chatbot,
  AssistantOptions,
} from "../api/chatbots";
import { ApiError } from "../api/client";
import FlowWritingView, { WritingSection } from "../components/assistant/FlowWritingView";
import DictateButton from "../components/DictateButton";

const MAX_DESCRIPTION = 4000;
const MIN_DESCRIPTION = 10;

/* ── Create box ── */
function CreateAssistantCard({ onCreated }: { onCreated: (bot: Chatbot) => void }) {
  const [description, setDescription] = useState("");
  const [useCase, setUseCase] = useState<string | null>(null);
  const [options, setOptions] = useState<AssistantOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // What the generator has produced so far. Replaces the form while writing.
  const [writtenName, setWrittenName] = useState("");
  const [writtenWelcome, setWrittenWelcome] = useState("");
  const [writtenSections, setWrittenSections] = useState<WritingSection[]>([]);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    // A failure here only costs the chips — the box still creates assistants,
    // so it is not worth surfacing as an error.
    getAssistantOptions().then(setOptions).catch(() => setOptions(null));
  }, []);

  // Leaving mid-generation must not leave a stream running.
  useEffect(() => () => abortRef.current?.(), []);

  const tooShort = description.trim().length < MIN_DESCRIPTION;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (tooShort || busy) return;
    setBusy(true);
    setError(null);
    setWrittenName("");
    setWrittenWelcome("");
    setWrittenSections([]);

    abortRef.current = generateAssistantStream(
      { description: description.trim(), use_case: useCase, channel: "voice" },
      {
        onMeta: (meta) => {
          setWrittenName(meta.name);
          setWrittenWelcome(meta.welcome_message);
        },
        onSection: (section) => setWrittenSections((prev) => [...prev, section]),
        onDone: (bot) => {
          abortRef.current = null;
          setBusy(false);
          // A beat so the last section finishes revealing rather than being
          // yanked away mid-word.
          setTimeout(() => onCreated(bot), 700);
        },
        onError: (message) => {
          abortRef.current = null;
          setBusy(false);
          setError(message || "Could not create the assistant.");
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-2xl border border-brand-500/30 bg-surface overflow-hidden"
    >
      <div className="px-6 pt-5 pb-4 border-b border-brand-500/15 bg-brand-500/[0.04]">
        <h2 className="text-[15px] font-semibold text-brand-400">
          {busy ? "Building your voice AI assistant" : "Create a new voice AI assistant"}
        </h2>
        <p className="text-[13px] text-gray-500 mt-0.5">
          {busy
            ? "Watch the conversational flow being written — you can edit every word of it next."
            : "Describe the type of voice AI assistant you want to create"}
        </p>
      </div>

      {/* While generating, the form gives way to the flow being written. The
          description is preserved underneath, so a failure returns you to it
          with your text intact rather than an empty box. */}
      {busy ? (
        <div className="px-6 py-5">
          <FlowWritingView
            name={writtenName}
            welcomeMessage={writtenWelcome}
            sections={writtenSections}
            writing={busy}
          />
        </div>
      ) : (
      <div className="px-6 py-5">
        {/* Relative, so the mic can sit inside the box's bottom-right corner
            rather than stealing a row beneath it. */}
        <div className="relative">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={MAX_DESCRIPTION}
            rows={7}
            autoFocus
            aria-label="Assistant description"
            placeholder="Describe your voice AI assistant's purpose, personality, and how it should handle calls. Or press the mic and just say it."
            className="input resize-y text-[13.5px] leading-relaxed bg-surface-2 rounded-xl px-4 py-3.5 pb-12"
            // Ctrl/⌘+Enter submits — the button is a long way from the caret in a
            // box this tall.
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit(e);
            }}
          />
          <DictateButton
            value={description}
            onChange={setDescription}
            className="absolute bottom-3 right-3"
          />
        </div>

        {error && (
          <div role="alert" className="mt-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[13px] text-gray-400 mb-2.5">Choose from Use Case Categories:</p>
            <div className="flex flex-wrap gap-2">
              {(options?.use_cases ?? []).map((uc) => {
                const active = useCase === uc.id;
                return (
                  <button
                    key={uc.id}
                    type="button"
                    aria-pressed={active}
                    // Re-clicking clears it — the chips are a hint, not a
                    // required field, and there is no other way back to "none".
                    onClick={() => setUseCase(active ? null : uc.id)}
                    className={`rounded-lg px-4 py-2 text-[13px] font-medium transition-colors ${
                      active
                        ? "bg-brand-500/15 text-brand-400 ring-1 ring-inset ring-brand-500/40"
                        : "bg-surface-2 text-gray-400 hover:text-gray-900 hover:bg-gray-100"
                    }`}
                  >
                    {uc.label}
                  </button>
                );
              })}
            </div>
          </div>

          <button
            type="submit"
            disabled={tooShort}
            className="btn-primary px-5 py-2.5 flex-shrink-0"
          >
            Create Voice AI Assistant
          </button>
        </div>
      </div>
      )}
    </form>
  );
}

/* ── Assistant card ── */
function CardStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Brain;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <Icon className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" strokeWidth={1.75} />
      <span className="text-[12.5px] text-gray-500 flex-shrink-0">{label}:</span>
      <span className="text-[12.5px] font-semibold text-gray-800 truncate">{value}</span>
    </div>
  );
}

/** Per-card overflow menu. One item today (delete), but built as a menu because
 * "duplicate", "publish" and the rest belong here rather than as more buttons
 * competing for room on the card. */
function CardMenu({ bot, onDeleted }: { bot: Chatbot; onDeleted: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape — a menu that only closes by re-clicking
  // its own trigger feels stuck.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteChatbot(bot.id);
      onDeleted(bot.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete this assistant.");
      setBusy(false);
    }
  }

  return (
    <div className="relative flex-shrink-0" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Actions for ${bot.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        className="p-1 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100"
      >
        <MoreVertical className="w-4 h-4" strokeWidth={2} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-7 z-20 w-56 rounded-lg border border-gray-200 bg-surface shadow-pop p-1"
        >
          {!confirming ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => setConfirming(true)}
              className="w-full text-left rounded px-2.5 py-1.5 text-[13px] text-red-600 hover:bg-red-50 flex items-center gap-2"
            >
              <Trash2 className="w-3.5 h-3.5" strokeWidth={2} />
              Delete assistant
            </button>
          ) : (
            <div className="p-2">
              <p className="text-[12.5px] text-gray-700 mb-1">
                Delete <span className="font-semibold">{bot.name}</span>?
              </p>
              {/* Named explicitly: "are you sure" tells nobody what they lose. */}
              <p className="text-[11px] text-gray-500 mb-2.5">
                Its conversations and logs go too. A linked WhatsApp number stays paired, it just
                stops having an assistant. This cannot be undone.
              </p>
              {error && <p className="text-[11px] text-red-600 mb-2">{error}</p>}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={remove}
                  disabled={busy}
                  className="btn-danger text-xs px-2.5 py-1 h-auto disabled:opacity-50"
                >
                  {busy ? "Deleting…" : "Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  disabled={busy}
                  className="btn-secondary text-xs px-2.5 py-1 h-auto"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AssistantCard({
  bot,
  index,
  onDeleted,
}: {
  bot: Chatbot;
  index: number;
  onDeleted: (id: string) => void;
}) {
  const live = bot.is_public;
  // The voice label carries a provider prefix ("Cartesia - Riya") that the card
  // has no room for and the operator already chose; the provider is the part
  // that identifies it at a glance.
  const voice = (bot.assistant.tts_voice.split(" - ")[0] || "Default").toLowerCase();

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: Math.min(index, 8) * 0.03, ease: "easeOut" }}
      className="rounded-xl border border-gray-200 bg-surface flex flex-col
                 transition-colors hover:border-brand-500/40"
    >
      <div className="px-4 pt-3.5 pb-3">
        <div className="flex items-start gap-2.5">
          <ArrowUpRight className="w-4 h-4 mt-0.5 flex-shrink-0 text-cta-500" strokeWidth={2.25} />
          <Link
            to={`/assistants/${bot.id}`}
            className="text-[16px] font-semibold text-gray-900 hover:text-brand-400 transition-colors
                       truncate flex-1 min-w-0"
          >
            {bot.name}
          </Link>
          <span className={live ? "badge badge-live" : "badge badge-draft"}>
            <span className={live ? "dot-live mr-1" : "dot-draft mr-1"} />
            {live ? "Live" : "Draft"}
          </span>
          <CardMenu bot={bot} onDeleted={onDeleted} />
        </div>
        <p className="text-[12.5px] text-gray-500 mt-1 ml-[26px] truncate">
          {bot.assistant.languages.join(", ")}
        </p>
      </div>

      <div className="border-t border-gray-100 px-4 py-3 grid grid-cols-2 gap-x-4 gap-y-2">
        <CardStat icon={Brain} label="LLM" value={bot.assistant.llm_model} />
        <CardStat icon={Mic} label="Voice" value={voice} />
        <CardStat icon={FileText} label="KB Files" value={String(bot.counts.knowledge_files)} />
        <CardStat icon={ArrowDownUp} label="Direction" value={bot.assistant.direction} />
        <CardStat
          icon={Settings2}
          label={`Post-call (${bot.counts.post_call_actions})`}
          value={bot.counts.post_call_actions === 0 ? "None" : "Configured"}
        />
        <CardStat
          icon={Zap}
          label={`Integrations (${bot.counts.integrations})`}
          value={bot.counts.integrations === 0 ? "None" : "Connected"}
        />
      </div>

      <div className="border-t border-gray-100 px-4 py-3 flex items-center gap-3 mt-auto">
        <span
          title="This assistant's short id — stable, unique, and safe to quote in a ticket."
          className="rounded-lg border border-gray-200 bg-surface-2 px-3 py-2 text-[12.5px]
                     font-mono text-gray-500 flex-shrink-0"
        >
          {bot.display_id ? `ID: #${bot.display_id}` : "ID: —"}
        </span>
        <Link
          to={`/assistants/${bot.id}`}
          className="btn-primary flex-1 justify-center py-2 text-[13.5px]"
        >
          Edit Agent
        </Link>
      </div>
    </motion.div>
  );
}

/* ── Page ── */
export default function AssistantsPage() {
  const [bots, setBots] = useState<Chatbot[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listChatbots()
      .then(setBots)
      .catch(() => setBots([]))
      .finally(() => setLoading(false));
  }, []);

  function handleCreated(bot: Chatbot) {
    setBots((prev) => [bot, ...prev]);
    // Straight into the builder — reviewing the generated flow is the whole
    // point, and a list row is not where you do that.
    navigate(`/assistants/${bot.id}`);
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Voice AI Assistants</h1>
          <p className="page-subtitle">Create and manage your voice AI assistants</p>
        </div>
      </header>

      <CreateAssistantCard onCreated={handleCreated} />

      <section className="mt-10">
        <h2 className="text-[19px] font-bold text-gray-900 tracking-tight mb-4">
          My Voice AI Assistants
        </h2>

        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="skeleton h-[74px] rounded-xl" />
            ))}
          </div>
        ) : bots.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-200 py-14 text-center">
            <div className="mx-auto w-12 h-12 rounded-xl bg-brand-500/10 flex items-center justify-center">
              <Bot className="w-6 h-6 text-brand-400" strokeWidth={1.75} />
            </div>
            <p className="text-[15px] font-semibold text-gray-800 mt-4">No assistants yet</p>
            <p className="text-sm text-gray-500 mt-1.5 max-w-sm mx-auto leading-relaxed">
              Describe what you want in the box above — the AI writes the conversational
              flow for you, and you edit it from there.
            </p>
            <p className="text-xs text-gray-500 mt-4 inline-flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-brand-400" strokeWidth={1.75} />
              Every assistant gets its own flow — nothing is templated.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {bots.map((bot, i) => (
              <AssistantCard
                key={bot.id}
                bot={bot}
                index={i}
                onDeleted={(id) => setBots((prev) => prev.filter((b) => b.id !== id))}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
