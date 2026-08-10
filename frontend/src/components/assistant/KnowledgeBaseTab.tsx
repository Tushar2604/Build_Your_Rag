// Knowledge Base — the documents this one assistant answers from.
//
// Its own documents and nothing else. There is no workspace picker: files
// uploaded for a different assistant are not this assistant's knowledge, and
// listing them would invite attaching a pricing sheet to a recruiting bot by
// accident. Upload here, and it belongs to this assistant.
//
// An assistant with an empty knowledge base still works — it answers from its
// Conversational Flow alone — so this nudges rather than blocks.
import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, FileText, Info, Loader2, Trash2, Upload } from "lucide-react";
import {
  AssistantKnowledge,
  attachAssistantKnowledge,
  detachAssistantKnowledge,
  getAssistantKnowledge,
} from "../../api/chatbots";
import { completeUpload, createUpload, uploadFile } from "../../api/documents";
import { ApiError } from "../../api/client";

const UPLOAD_CONCURRENCY = 4;
/** Documents mid-ingestion settle within seconds; poll until they do. */
const POLL_MS = 3000;

interface UploadRow {
  filename: string;
  status: "uploading" | "done" | "failed";
  error?: string;
}

function StatusPill({ status, error }: { status: string; error: string | null }) {
  if (status === "ready") {
    return (
      <span className="badge badge-live">
        <CheckCircle2 className="w-3 h-3 mr-0.5" strokeWidth={2} />
        Ready
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="badge badge-error" title={error ?? undefined}>
        Failed
      </span>
    );
  }
  return (
    <span className="badge badge-paused">
      <Loader2 className="w-3 h-3 mr-0.5 animate-spin" strokeWidth={2} />
      Processing
    </span>
  );
}

export default function KnowledgeBaseTab({ chatbotId }: { chatbotId: string }) {
  const [data, setData] = useState<AssistantKnowledge | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        setData(await getAssistantKnowledge(chatbotId));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not load the knowledge base.");
      } finally {
        setLoading(false);
      }
    },
    [chatbotId],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while something is actually mid-ingestion.
  const pending = (data?.documents ?? []).some(
    (d) => d.status !== "ready" && d.status !== "failed",
  );
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => load(true), POLL_MS);
    return () => clearInterval(timer);
  }, [pending, load]);

  async function handleFiles(files: FileList | File[] | null) {
    if (!files) return;
    const list = Array.from(files);
    if (!list.length) return;

    const start = uploads.length;
    setUploads((prev) => [
      ...prev,
      ...list.map((f) => ({ filename: f.name, status: "uploading" as const })),
    ]);
    setError(null);

    function updateRow(i: number, patch: Partial<UploadRow>) {
      setUploads((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
    }

    const uploadedIds: string[] = [];
    let cursor = 0;
    async function worker() {
      for (;;) {
        const i = cursor++;
        if (i >= list.length) return;
        const file = list[i];
        try {
          const { document_id, upload_url } = await createUpload(
            file.name,
            file.type || "application/octet-stream",
            file.size,
          );
          await uploadFile(upload_url, file);
          await completeUpload(document_id);
          uploadedIds.push(document_id);
          updateRow(start + i, { status: "done" });
        } catch (err) {
          updateRow(start + i, {
            status: "failed",
            error: err instanceof ApiError ? err.message : "Upload failed.",
          });
        }
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(UPLOAD_CONCURRENCY, list.length) }, worker),
    );

    if (uploadedIds.length) {
      try {
        // Attaching is additive server-side, so two batches finishing together
        // can't overwrite each other.
        setData(await attachAssistantKnowledge(chatbotId, uploadedIds));
      } catch {
        await load(true);
      }
    }
    // Clear finished rows once they're represented in the list below.
    setTimeout(() => setUploads((prev) => prev.filter((r) => r.status === "failed")), 1500);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function remove(documentId: string) {
    setBusyId(documentId);
    setError(null);
    try {
      setData(await detachAssistantKnowledge(chatbotId, documentId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not remove the document.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="skeleton h-14 rounded-xl" />
        ))}
      </div>
    );
  }

  const docs = data?.documents ?? [];
  const readyCount = data?.ready_count ?? 0;

  return (
    <div className="space-y-5">
      {/* What the current state means for answers */}
      <div
        className={`rounded-xl border px-4 py-3.5 flex items-start gap-3 ${
          docs.length === 0
            ? "border-amber-200 bg-amber-50"
            : "border-emerald-200 bg-emerald-50"
        }`}
      >
        <Info
          className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
            docs.length === 0 ? "text-amber-700" : "text-emerald-700"
          }`}
          strokeWidth={2}
        />
        <div className="text-[13px] leading-relaxed">
          {docs.length === 0 ? (
            <p className="text-amber-900">
              <strong className="font-semibold">No knowledge base yet.</strong> This
              assistant works without one — it answers from its Conversational Flow
              alone — but it can't quote prices, policies, or product detail. Upload a
              document and its answers get specific and checkable.
            </p>
          ) : (
            <p className="text-emerald-900">
              <strong className="font-semibold">
                Answering from {readyCount} document{readyCount === 1 ? "" : "s"}.
              </strong>{" "}
              Only these files — nothing uploaded for another assistant is used here.
              {readyCount < docs.length &&
                ` ${docs.length - readyCount} still processing.`}
            </p>
          )}
        </div>
      </div>

      {/* Upload */}
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={`flex items-center gap-3 rounded-xl border-2 border-dashed px-5 py-6 cursor-pointer
                    transition-colors ${
                      dragging
                        ? "border-brand-500 bg-brand-500/[0.06]"
                        : "border-gray-200 bg-surface hover:border-brand-500/50 hover:bg-surface-2"
                    }`}
      >
        <Upload className="w-5 h-5 flex-shrink-0 text-brand-400" strokeWidth={1.75} />
        <span className="min-w-0">
          <span className="block text-[14px] font-medium text-gray-900">
            Upload documents for this assistant
          </span>
          <span className="block text-xs text-gray-500 mt-0.5">
            Drop files here or click to browse — PDF, DOCX, TXT, MD, or an image
            (screenshots and scans are transcribed automatically).
          </span>
        </span>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>

      {uploads.length > 0 && (
        <ul className="space-y-1">
          {uploads.map((u, i) => (
            <li key={i} className="flex items-center justify-between text-xs px-1">
              <span className="text-gray-600 truncate flex-1 min-w-0">{u.filename}</span>
              <span
                className={
                  u.status === "done"
                    ? "text-emerald-600"
                    : u.status === "failed"
                      ? "text-red-600"
                      : "text-gray-500"
                }
              >
                {u.status === "uploading" && "Uploading…"}
                {u.status === "done" && "✓ Added"}
                {u.status === "failed" && (u.error || "Failed")}
              </span>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* This assistant's documents */}
      {docs.length > 0 && (
        <section className="rounded-2xl border border-gray-200 bg-surface overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-200">
            <h2 className="text-[14px] font-semibold text-gray-900">
              This assistant's documents
              <span className="text-gray-500 font-normal"> · {docs.length}</span>
            </h2>
          </div>

          <ul className="divide-y divide-gray-100">
            {docs.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3 px-5 py-3">
                <FileText className="w-4 h-4 text-gray-500 flex-shrink-0" strokeWidth={1.75} />
                <span className="text-[13.5px] text-gray-900 truncate flex-1 min-w-0">
                  {doc.filename}
                </span>
                <span className="text-xs text-gray-500 tabular-nums whitespace-nowrap">
                  {doc.chunk_count} chunks
                </span>
                <StatusPill status={doc.status} error={doc.error} />
                <button
                  onClick={() => remove(doc.id)}
                  disabled={busyId === doc.id}
                  aria-label={`Remove ${doc.filename} from this assistant`}
                  title="Remove from this assistant"
                  className="w-8 h-8 flex items-center justify-center rounded text-gray-500
                             hover:text-red-500 disabled:opacity-40"
                >
                  {busyId === doc.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                  ) : (
                    <Trash2 className="w-4 h-4" strokeWidth={1.75} />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
