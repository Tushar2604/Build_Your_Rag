// Voice AI Assistants — the front door.
//
// Creation is one box: describe the assistant in prose, optionally pick a
// use-case chip, hit Create. The server's generator writes the name, the
// welcome message, and a Conversational Flow specific to that description, then
// drops you straight into the builder to edit it. There is no wizard, because
// every field a wizard would ask for is one the description already answers.
import { useState, useEffect, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowUpRight, Bot, MoreVertical, Sparkles, Loader2 } from "lucide-react";
import {
  listChatbots,
  generateAssistant,
  getAssistantOptions,
  Chatbot,
  AssistantOptions,
} from "../api/chatbots";
import { ApiError } from "../api/client";

const MAX_DESCRIPTION = 4000;
const MIN_DESCRIPTION = 10;

/* ── Create box ── */
function CreateAssistantCard({ onCreated }: { onCreated: (bot: Chatbot) => void }) {
  const [description, setDescription] = useState("");
  const [useCase, setUseCase] = useState<string | null>(null);
  const [options, setOptions] = useState<AssistantOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // A failure here only costs the chips — the box still creates assistants,
    // so it is not worth surfacing as an error.
    getAssistantOptions().then(setOptions).catch(() => setOptions(null));
  }, []);

  const tooShort = description.trim().length < MIN_DESCRIPTION;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (tooShort || busy) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await generateAssistant({
          description: description.trim(),
          use_case: useCase,
          channel: "voice",
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the assistant.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-2xl border border-brand-500/30 bg-surface overflow-hidden"
    >
      <div className="px-6 pt-5 pb-4 border-b border-brand-500/15 bg-brand-500/[0.04]">
        <h2 className="text-[15px] font-semibold text-brand-400">
          Create a new voice AI assistant
        </h2>
        <p className="text-[13px] text-gray-500 mt-0.5">
          Describe the type of voice AI assistant you want to create
        </p>
      </div>

      <div className="px-6 py-5">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={MAX_DESCRIPTION}
          rows={7}
          autoFocus
          aria-label="Assistant description"
          placeholder="Describe your voice AI assistant's purpose, personality, and how it should handle calls."
          className="input resize-y text-[13.5px] leading-relaxed bg-surface-2 rounded-xl px-4 py-3.5"
          // Ctrl/⌘+Enter submits — the button is a long way from the caret in a
          // box this tall.
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit(e);
          }}
        />

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
                        : "bg-surface-2 text-gray-400 hover:text-gray-200 hover:bg-gray-100"
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
            disabled={tooShort || busy}
            className="btn-primary px-5 py-2.5 flex-shrink-0"
          >
            {busy ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                Building your assistant…
              </>
            ) : (
              "Create Voice AI Assistant"
            )}
          </button>
        </div>
      </div>
    </form>
  );
}

/* ── Assistant card ── */
function AssistantCard({ bot, index }: { bot: Chatbot; index: number }) {
  const live = bot.is_public;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: Math.min(index, 8) * 0.03, ease: "easeOut" }}
    >
      <Link
        to={`/assistants/${bot.id}`}
        className="group block rounded-xl border border-gray-200 bg-surface px-4 py-3.5
                   transition-colors hover:border-brand-500/40 hover:bg-surface-2"
      >
        <div className="flex items-start gap-3">
          <ArrowUpRight
            className="w-4 h-4 mt-0.5 flex-shrink-0 text-brand-400 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
            strokeWidth={2.25}
          />
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold text-gray-900 truncate">{bot.name}</p>
            <p className="text-xs text-gray-500 mt-1 flex items-center gap-2 flex-wrap">
              <span className="capitalize">{bot.assistant.direction}</span>
              <span className="text-gray-300">·</span>
              <span>{bot.assistant.languages[0] ?? "English"}</span>
              <span className="text-gray-300">·</span>
              <span>{bot.flow_sections.length || "raw"} section{bot.flow_sections.length === 1 ? "" : "s"}</span>
            </p>
          </div>
          <span className={live ? "badge badge-live" : "badge badge-draft"}>
            <span className={live ? "dot-live mr-1" : "dot-draft mr-1"} />
            {live ? "Live" : "Draft"}
          </span>
          <MoreVertical className="w-4 h-4 text-gray-500 flex-shrink-0" strokeWidth={1.75} />
        </div>
      </Link>
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
    <div className="max-w-6xl mx-auto px-8 py-8 animate-fade-in">
      <header className="mb-7">
        <h1 className="text-[30px] font-bold text-gray-900 tracking-tight">Voice AI Assistants</h1>
        <p className="text-[15px] text-gray-500 mt-1">Create and manage your voice AI assistants</p>
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
              <AssistantCard key={bot.id} bot={bot} index={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
