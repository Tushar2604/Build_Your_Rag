import { useState, useEffect, useRef, FormEvent } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, X, Upload, Sparkles } from "lucide-react";
import { listChatbots, createChatbot, Chatbot, Channel } from "../api/chatbots";
import { listDocuments, createUpload, uploadFile, completeUpload, Document } from "../api/documents";
import { ApiError } from "../api/client";

const ATTACHMENT_UPLOAD_CONCURRENCY = 4;

interface AttachedFileRow {
  filename: string;
  status: "uploading" | "done" | "failed";
  error?: string;
}

/* ── helpers ── */
function StatusPill({ bot }: { bot: Chatbot }) {
  return bot.is_public
    ? <span className="badge badge-live"><span className="dot-live mr-1" />Live</span>
    : <span className="badge badge-draft"><span className="dot-draft mr-1" />Draft</span>;
}

/* ── 3-step create flow ── */
const USE_CASES = [
  { id: "support",   label: "Customer Support",   desc: "Tier-1 support queries, billing, onboarding" },
  { id: "hr",        label: "Internal HR / Ops",  desc: "Policy docs, benefits, internal processes" },
  { id: "sales",     label: "Sales Enablement",   desc: "Battlecards, pricing, objection handling" },
  { id: "technical", label: "Technical Docs",     desc: "API references, developer documentation" },
  { id: "custom",    label: "Custom",             desc: "Define your own use case" },
];

const DEFAULT_PROMPTS: Record<string, string> = {
  support:   "You are a customer support assistant. Answer questions based only on the provided context. If the answer is not in the context, say so clearly and offer to escalate.",
  hr:        "You are an internal HR assistant. Answer employee questions based on company policies and documentation. Do not speculate or invent policy details.",
  sales:     "You are a sales enablement assistant. Help sales reps with product knowledge, competitive positioning, and objection handling based on approved materials only.",
  technical: "You are a technical documentation assistant. Provide precise, accurate answers with direct references to documentation. Never guess at technical details.",
  custom:    "You are a helpful assistant. Answer questions based only on the provided context. If the answer isn't in the context, say you don't know.",
};

interface CreateModalProps {
  documents: Document[];
  onCreate: (bot: Chatbot) => void;
  onClose: () => void;
}

function CreateModal({ documents, onCreate, onClose }: CreateModalProps) {
  const [step, setStep]               = useState<1 | 2 | 3>(1);
  const [name, setName]               = useState("");
  const [channel, setChannel]         = useState<Channel>("text");
  const [useCase, setUseCase]         = useState<string>("support");
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_PROMPTS.support);
  const [topK, setTopK]               = useState(5);
  const [error, setError]             = useState<string | null>(null);
  const [loading, setLoading]         = useState(false);

  // Attach new files (PDF/DOCX/TXT/MD, or images — a screenshot/scan/photo is
  // transcribed into text by a vision-capable LLM during ingestion) directly
  // at creation time, instead of requiring a trip to Knowledge first.
  const [attachedFiles, setAttachedFiles] = useState<AttachedFileRow[]>([]);
  const [attaching, setAttaching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function pickUseCase(id: string) {
    setUseCase(id);
    setSystemPrompt(DEFAULT_PROMPTS[id] ?? DEFAULT_PROMPTS.custom);
  }

  function toggleDoc(id: string) {
    setSelectedDocs((prev) => prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]);
  }

  async function handleAttachFiles(files: FileList | null) {
    if (!files || !files.length) return;
    const fileList = Array.from(files);
    const startIndex = attachedFiles.length;
    setAttachedFiles((prev) => [...prev, ...fileList.map((f) => ({ filename: f.name, status: "uploading" as const }))]);
    setAttaching(true);

    function updateRow(i: number, patch: Partial<AttachedFileRow>) {
      setAttachedFiles((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
    }

    let cursor = 0;
    async function worker() {
      while (true) {
        const i = cursor++;
        if (i >= fileList.length) return;
        const file = fileList[i];
        const rowIndex = startIndex + i;
        try {
          const { document_id, upload_url } = await createUpload(
            file.name, file.type || "application/octet-stream", file.size,
          );
          await uploadFile(upload_url, file);
          await completeUpload(document_id);
          setSelectedDocs((prev) => [...prev, document_id]);
          updateRow(rowIndex, { status: "done" });
        } catch (err) {
          updateRow(rowIndex, {
            status: "failed",
            error: err instanceof ApiError ? err.message : "Upload failed.",
          });
        }
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(ATTACHMENT_UPLOAD_CONCURRENCY, fileList.length) }, worker),
    );
    setAttaching(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const bot = await createChatbot({
        name,
        channel,
        system_prompt: systemPrompt,
        top_k: topK,
        is_public: false,
        allowed_document_ids: selectedDocs,
      });
      onCreate(bot);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create assistant.");
    } finally {
      setLoading(false);
    }
  }

  const readyDocs = documents.filter((d) => d.status === "ready");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 backdrop-blur-sm px-4 animate-fade-in"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in">
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 id="create-title" className="text-sm font-semibold text-gray-900">New assistant</h2>
            <p className="text-xs text-gray-400 mt-0.5">Step {step} of 3</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex px-6 pt-4 gap-1.5">
          {[1, 2, 3].map((n) => (
            <div key={n} className={`flex-1 h-1 rounded-full transition-colors ${n <= step ? "bg-ink-900" : "bg-gray-100"}`} />
          ))}
        </div>

        <form onSubmit={handleCreate}>
          {/* Step 1 — Identity */}
          {step === 1 && (
            <div className="px-6 py-5 space-y-5">
              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-3">How will people talk to it?</h3>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setChannel("text")}
                    className={`text-left px-3 py-3 rounded-lg border text-xs transition-colors ${
                      channel === "text"
                        ? "border-brand-500 bg-brand-50 text-brand-800"
                        : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                    }`}
                  >
                    <span className="font-medium block">💬 Text chatbot</span>
                    <span className="text-[10px] text-gray-400 mt-0.5 block">Chat bubbles — playground, share link, embed</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setChannel("voice")}
                    className={`text-left px-3 py-3 rounded-lg border text-xs transition-colors ${
                      channel === "voice"
                        ? "border-brand-500 bg-brand-50 text-brand-800"
                        : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                    }`}
                  >
                    <span className="font-medium block">🎙️ Voice chatbot</span>
                    <span className="text-[10px] text-gray-400 mt-0.5 block">Phone-call style — listens and speaks replies</span>
                  </button>
                </div>
                <p className="text-xs text-gray-400 mt-2">Changeable anytime in Configuration.</p>
              </div>
              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-3">What is this assistant for?</h3>
                <label className="label">Name</label>
                <input
                  type="text"
                  className="input"
                  placeholder="Customer Support Assistant"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  minLength={1}
                  maxLength={120}
                  autoFocus
                />
              </div>
              <div>
                <label className="label">Use case</label>
                <div className="grid grid-cols-2 gap-2">
                  {USE_CASES.map((uc) => (
                    <button
                      key={uc.id}
                      type="button"
                      onClick={() => pickUseCase(uc.id)}
                      className={`text-left px-3 py-2.5 rounded-lg border text-xs transition-colors ${
                        useCase === uc.id
                          ? "border-brand-500 bg-brand-50 text-brand-800"
                          : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                      }`}
                    >
                      <span className="font-medium block">{uc.label}</span>
                      <span className="text-[10px] text-gray-400 mt-0.5 block">{uc.desc}</span>
                    </button>
                  ))}
                </div>
                <p className="text-xs text-gray-400 mt-2">Pre-fills sensible defaults for tone and fallback behavior.</p>
              </div>
            </div>
          )}

          {/* Step 2 — Knowledge */}
          {step === 2 && (
            <div className="px-6 py-5 space-y-4">
              <div>
                <h3 className="text-sm font-medium text-gray-900">Connect knowledge sources</h3>
                <p className="text-xs text-gray-500 mt-1">The assistant will only answer from selected sources.</p>
              </div>

              {/* Attach files right here — PDF, DOCX, TXT, MD, or an image
                  (screenshot/scan/photo — transcribed into text automatically). */}
              <div>
                <label className={`flex items-center gap-3 rounded-lg border-2 border-dashed px-4 py-3 cursor-pointer transition-colors ${
                  attaching ? "border-gray-200 bg-gray-50" : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                }`}>
                  <Upload className="w-5 h-5 flex-shrink-0 text-gray-400" strokeWidth={1.5} />
                  <span className="text-sm text-gray-600 flex-1 min-w-0">
                    Attach files — PDF, DOCX, TXT, MD, or images
                  </span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                    className="sr-only"
                    onChange={(e) => handleAttachFiles(e.target.files)}
                  />
                </label>
                {attachedFiles.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {attachedFiles.map((f, i) => (
                      <div key={i} className="flex items-center justify-between text-xs px-1">
                        <span className="text-gray-600 truncate flex-1 min-w-0">{f.filename}</span>
                        <span className={
                          f.status === "done" ? "text-emerald-600"
                          : f.status === "failed" ? "text-red-600"
                          : "text-gray-400"
                        }>
                          {f.status === "uploading" && "Uploading…"}
                          {f.status === "done" && "✓ Attached"}
                          {f.status === "failed" && (f.error || "Failed")}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {readyDocs.length === 0 ? (
                <p className="text-xs text-gray-400 text-center">
                  Or attach existing documents — <Link to="/knowledge" className="text-brand-600 hover:underline">Knowledge</Link> has none yet.
                  You can also skip this and assign sources later.
                </p>
              ) : (
                <div className="space-y-1 max-h-52 overflow-y-auto rounded-lg border border-gray-200 p-2">
                  {readyDocs.map((d) => (
                    <label key={d.id} className="flex items-center gap-2.5 px-2 py-2 rounded cursor-pointer hover:bg-gray-50">
                      <input
                        type="checkbox"
                        className="w-3.5 h-3.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                        checked={selectedDocs.includes(d.id)}
                        onChange={() => toggleDoc(d.id)}
                      />
                      <span className="text-sm text-gray-700 truncate flex-1">{d.filename}</span>
                      <span className="text-xs text-gray-400 tabular-nums">{d.chunk_count} chunks</span>
                    </label>
                  ))}
                </div>
              )}
              <p className="text-xs text-gray-400">
                {selectedDocs.length === 0
                  ? "Leave empty to search all documents."
                  : `${selectedDocs.length} source${selectedDocs.length !== 1 ? "s" : ""} selected`
                }
              </p>
            </div>
          )}

          {/* Step 3 — Behaviour */}
          {step === 3 && (
            <div className="px-6 py-5 space-y-4">
              <div>
                <h3 className="text-sm font-medium text-gray-900">Instructions &amp; retrieval</h3>
                <p className="text-xs text-gray-500 mt-1">Pre-filled from your use case. You can change this later.</p>
              </div>

              <div>
                <label className="label">System instructions</label>
                <textarea
                  className="input resize-none text-xs"
                  rows={5}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  maxLength={4000}
                />
                <p className="text-xs text-gray-400 text-right mt-1">{systemPrompt.length}/4000</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Top-K results</label>
                  <input
                    type="number"
                    className="input"
                    min={1}
                    max={20}
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                  />
                  <p className="text-xs text-gray-400 mt-1">Chunks retrieved per query.</p>
                </div>
              </div>

              {error && (
                <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50/60">
            <button
              type="button"
              onClick={() => step > 1 ? setStep((s) => (s - 1) as 1 | 2 | 3) : onClose()}
              className="btn-secondary"
            >
              {step === 1 ? "Cancel" : "← Back"}
            </button>

            {step < 3 ? (
              <button
                type="button"
                onClick={() => {
                  if (step === 1 && !name.trim()) return;
                  setStep((s) => (s + 1) as 2 | 3);
                }}
                disabled={step === 1 && !name.trim()}
                className="btn-primary"
              >
                Continue →
              </button>
            ) : (
              <button type="submit" disabled={loading} className="btn-primary">
                {loading ? "Creating…" : "Create assistant →"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

/* ── Main page ── */
export default function AssistantsPage() {
  const [bots, setBots]           = useState<Chatbot[]>([]);
  const [docs, setDocs]           = useState<Document[]>([]);
  const [loading, setLoading]     = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([listChatbots(), listDocuments()])
      .then(([b, d]) => { setBots(b); setDocs(d); })
      .finally(() => setLoading(false));
  }, []);

  function handleCreated(bot: Chatbot) {
    setBots((prev) => [bot, ...prev]);
    setShowCreate(false);
  }

  return (
    <div className="page">
      {showCreate && (
        <CreateModal
          documents={docs}
          onCreate={handleCreated}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="page-title">Assistants</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? "Loading…" : `${bots.length} assistant${bots.length !== 1 ? "s" : ""} · ${bots.filter((b) => b.is_public).length} live`}
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-cta">
          <Plus className="w-4 h-4" strokeWidth={2.25} />
          New assistant
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead><tr><th>Name</th><th>Status</th><th>Sources</th><th>Top-K</th><th /></tr></thead>
            <tbody>
              {[...Array(3)].map((_, i) => (
                <tr key={i}>
                  <td><div className="skeleton h-4 w-40" /></td>
                  <td><div className="skeleton h-5 w-14 rounded-full" /></td>
                  <td><div className="skeleton h-4 w-8" /></td>
                  <td><div className="skeleton h-4 w-6" /></td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : bots.length === 0 ? (
        <div className="relative overflow-hidden rounded-2xl mesh-bg border border-gray-200/80">
          <div className="empty-state relative">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center shadow-lift">
              <Sparkles className="w-7 h-7 text-white" strokeWidth={1.75} />
            </div>
            <p className="empty-state-title text-lg">No assistants yet</p>
            <p className="empty-state-desc">Build your first AI assistant in minutes. Connect knowledge, configure behavior, deploy to production.</p>
            <button onClick={() => setShowCreate(true)} className="btn-cta mt-5">
              Create your first assistant
            </button>
          </div>
        </div>
      ) : (
        <div className="card card-hover overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>System prompt</th>
                <th className="text-right">Top-K</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {bots.map((bot, i) => (
                <motion.tr
                  key={bot.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: i * 0.03, ease: "easeOut" }}
                >
                  <td>
                    <Link
                      to={`/assistants/${bot.id}`}
                      className="font-medium text-gray-900 hover:text-brand-700 transition-colors"
                    >
                      {bot.channel === "voice" ? "🎙️" : "💬"} {bot.name}
                    </Link>
                  </td>
                  <td><StatusPill bot={bot} /></td>
                  <td>
                    <span className="text-gray-500 text-xs truncate max-w-xs block" title={bot.system_prompt}>
                      {bot.system_prompt.slice(0, 60)}{bot.system_prompt.length > 60 ? "…" : ""}
                    </span>
                  </td>
                  <td className="text-right tabular-nums text-gray-600">{bot.top_k}</td>
                  <td className="text-right">
                    <Link
                      to={`/assistants/${bot.id}`}
                      className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                    >
                      Open →
                    </Link>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
