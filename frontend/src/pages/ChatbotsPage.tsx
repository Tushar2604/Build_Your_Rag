import { useState, useEffect, FormEvent } from "react";
import { Link } from "react-router-dom";
import { listChatbots, createChatbot, Chatbot } from "../api/chatbots";
import { listDocuments, Document } from "../api/documents";
import { ApiError } from "../api/client";

const DEFAULT_PROMPT =
  "You are a helpful assistant. Answer questions based only on the provided context. If the answer isn't in the context, say you don't know.";

function CreateChatbotModal({
  documents,
  onCreate,
  onClose,
}: {
  documents: Document[];
  onCreate: (bot: Chatbot) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_PROMPT);
  const [topK, setTopK] = useState(5);
  const [isPublic, setIsPublic] = useState(false);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function toggleDoc(id: string) {
    setSelectedDocs((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const bot = await createChatbot({
        name,
        system_prompt: systemPrompt,
        top_k: topK,
        is_public: isPublic,
        allowed_document_ids: selectedDocs,
      });
      onCreate(bot);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create chatbot.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-bot-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
    >
      <div className="card w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <h2 id="create-bot-title" className="text-base font-semibold text-gray-900">
            New chatbot
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="space-y-4">
            <div>
              <label htmlFor="bot-name" className="label">Name</label>
              <input
                id="bot-name"
                type="text"
                name="bot-name"
                required
                minLength={1}
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input"
                placeholder="Support Assistant…"
              />
            </div>

            <div>
              <label htmlFor="system-prompt" className="label">System prompt</label>
              <textarea
                id="system-prompt"
                rows={4}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                className="input resize-none"
              />
            </div>

            <div className="flex gap-6">
              <div className="flex-1">
                <label htmlFor="top-k" className="label">
                  Top&#8209;K results
                </label>
                <input
                  id="top-k"
                  type="number"
                  name="top-k"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="input"
                />
              </div>
              <div className="flex items-end pb-1.5">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={isPublic}
                    onChange={(e) => setIsPublic(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span className="text-sm text-gray-700">Public</span>
                </label>
              </div>
            </div>

            {documents.filter((d) => d.status === "ready").length > 0 && (
              <div>
                <span className="label">Allowed documents (optional)</span>
                <div className="mt-1 space-y-1 max-h-36 overflow-y-auto rounded-lg border border-gray-200 p-2">
                  {documents
                    .filter((d) => d.status === "ready")
                    .map((d) => (
                      <label key={d.id} className="flex items-center gap-2 cursor-pointer rounded px-2 py-1 hover:bg-gray-50">
                        <input
                          type="checkbox"
                          checked={selectedDocs.includes(d.id)}
                          onChange={() => toggleDoc(d.id)}
                          className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                        />
                        <span className="text-sm text-gray-700 truncate">{d.filename}</span>
                      </label>
                    ))}
                </div>
                <p className="text-xs text-gray-400 mt-1">Leave empty to search all documents.</p>
              </div>
            )}

            {error && (
              <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="flex gap-3 justify-end pt-2">
              <button type="button" onClick={onClose} className="btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={loading} className="btn-primary">
                {loading ? "Creating…" : "Create chatbot"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function ChatbotsPage() {
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([listChatbots(), listDocuments()])
      .then(([bots, docs]) => {
        setChatbots(bots);
        setDocuments(docs);
      })
      .finally(() => setLoading(false));
  }, []);

  function handleCreated(bot: Chatbot) {
    setChatbots((prev) => [bot, ...prev]);
    setShowCreate(false);
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 sm:px-6">
      {showCreate && (
        <CreateChatbotModal
          documents={documents}
          onCreate={handleCreated}
          onClose={() => setShowCreate(false)}
        />
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Chatbots</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            AI assistants grounded in your documents
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New chatbot
        </button>
      </div>

      {loading ? (
        <div aria-live="polite" className="text-center py-16 text-sm text-gray-400">
          Loading chatbots…
        </div>
      ) : chatbots.length === 0 ? (
        <div className="text-center py-16">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-brand-50 mb-4">
            <svg className="w-7 h-7 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>
          <p className="text-sm text-gray-500">No chatbots yet — create one to start chatting.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {chatbots.map((bot) => (
            <Link
              key={bot.id}
              to={`/chatbots/${bot.id}`}
              className="card p-5 group hover:border-brand-300 hover:shadow-md transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <h2 className="font-semibold text-gray-900 group-hover:text-brand-700 truncate transition-colors">
                    {bot.name}
                  </h2>
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{bot.system_prompt}</p>
                </div>
                <div className="flex-shrink-0 flex items-center gap-1.5">
                  {bot.is_public && (
                    <span className="badge bg-green-100 text-green-700">Public</span>
                  )}
                </div>
              </div>
              <div className="mt-4 flex items-center gap-4 text-xs text-gray-400">
                <span>Top&#8209;{bot.top_k} results</span>
                <span className="flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  Chat
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
