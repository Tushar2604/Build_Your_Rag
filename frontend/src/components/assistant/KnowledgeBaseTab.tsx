// Knowledge Base — the documents this one assistant may retrieve from.
//
// An assistant works fine with nothing attached: it falls back to searching
// every ready document in the workspace, and if there are none it simply
// answers from its Conversational Flow alone. That is a legitimate
// configuration, not an error — so this tab nudges rather than blocks, and says
// plainly what the current setting means for answers.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, FileText, Info, Loader2, Upload } from "lucide-react";
import {
  AssistantKnowledge,
  getAssistantKnowledge,
  setAssistantKnowledge,
} from "../../api/chatbots";
import { completeUpload, createUpload, uploadFile } from "../../api/documents";
import { ApiError } from "../../api/client";

const UPLOAD_CONCURRENCY = 4;
/** Documents mid-ingestion settle within seconds; poll until they do. */
const POLL_MS = 4000;

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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
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

  async function toggle(documentId: string) {
    if (!data) return;
    const next = data.documents.some((d) => d.id === documentId && d.attached)
      ? data.documents.filter((d) => d.attached && d.id !== documentId).map((d) => d.id)
      : [...data.documents.filter((d) => d.attached).map((d) => d.id), documentId];

    setSaving(true);
    setError(null);
    try {
      setData(await setAssistantKnowledge(chatbotId, next));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the selection.");
    } finally {
      setSaving(false);
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    const list = Array.from(files);
    const start = uploads.length;
    setUploads((prev) => [
      ...prev,
      ...list.map((f) => ({ filename: f.name, status: "uploading" as const })),
    ]);

    function updateRow(i: number, patch: Partial<UploadRow>) {
      setUploads((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
    }

    // Uploaded files are attached to this assistant automatically — a file
    // dropped on an assistant's own Knowledge tab was clearly meant for it.
    const attachedIds: string[] = [];
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
          attachedIds.push(document_id);
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

    if (attachedIds.length) {
      const already = (data?.documents ?? []).filter((d) => d.attached).map((d) => d.id);
      try {
        setData(await setAssistantKnowledge(chatbotId, [...already, ...attachedIds]));
      } catch {
        await load(true);
      }
    } else {
      await load(true);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
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
  const scopeIsAll = data?.scope_is_all ?? true;
  const readyCount = data?.ready_count ?? 0;

  return (
    <div className="space-y-5">
      {/* Scope explanation — the two meanings of "nothing attached" differ a lot. */}
      <div
        className={`rounded-xl border px-4 py-3.5 flex items-start gap-3 ${
          readyCount === 0
            ? "border-amber-200 bg-amber-50"
            : scopeIsAll
              ? "border-blue-200 bg-blue-50"
              : "border-emerald-200 bg-emerald-50"
        }`}
      >
        <Info
          className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
            readyCount === 0 ? "text-amber-700" : scopeIsAll ? "text-blue-700" : "text-emerald-700"
          }`}
          strokeWidth={2}
        />
        <div className="text-[13px] leading-relaxed">
          {readyCount === 0 ? (
            <p className="text-amber-900">
              <strong className="font-semibold">No knowledge base yet.</strong> This
              assistant still works — it answers from its Conversational Flow alone —
              but it can't quote prices, policies, or product detail. Upload a
              document below and its answers get specific and checkable.
            </p>
          ) : scopeIsAll ? (
            <p className="text-blue-900">
              <strong className="font-semibold">Searching all {readyCount} documents.</strong>{" "}
              Nothing is attached, so this assistant retrieves from every ready
              document in the workspace. Tick specific files to narrow it.
            </p>
          ) : (
            <p className="text-emerald-900">
              <strong className="font-semibold">
                Scoped to {data?.attached_count} document
                {data?.attached_count === 1 ? "" : "s"}.
              </strong>{" "}
              This assistant only retrieves from the ticked files. Untick them all to
              search everything again.
            </p>
          )}
        </div>
      </div>

      {/* Upload */}
      <label
        className="flex items-center gap-3 rounded-xl border-2 border-dashed border-gray-200 bg-surface
                   px-5 py-5 cursor-pointer transition-colors hover:border-brand-500/50 hover:bg-surface-2"
      >
        <Upload className="w-5 h-5 flex-shrink-0 text-brand-400" strokeWidth={1.75} />
        <span className="min-w-0">
          <span className="block text-[14px] font-medium text-gray-900">
            Upload documents for this assistant
          </span>
          <span className="block text-xs text-gray-500 mt-0.5">
            PDF, DOCX, TXT, MD, or an image — screenshots and scans are transcribed
            automatically. Files land attached to this assistant.
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
                {u.status === "done" && "✓ Attached"}
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

      {/* Document list */}
      <section className="rounded-2xl border border-gray-200 bg-surface overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-200">
          <h2 className="text-[14px] font-semibold text-gray-900">
            Workspace documents
            {docs.length > 0 && <span className="text-gray-500 font-normal"> · {docs.length}</span>}
          </h2>
          {saving && <span className="text-xs text-gray-500">Saving…</span>}
        </div>

        {docs.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <FileText className="w-8 h-8 text-gray-400 mx-auto" strokeWidth={1.5} />
            <p className="text-sm text-gray-500 mt-3">
              No documents in this workspace yet. Upload one above, or add them from{" "}
              <Link to="/knowledge" className="link">
                Files
              </Link>
              .
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {docs.map((doc) => (
              <li key={doc.id}>
                <label
                  className={`flex items-center gap-3 px-5 py-3 transition-colors ${
                    doc.status === "ready"
                      ? "cursor-pointer hover:bg-surface-2"
                      : "opacity-60 cursor-not-allowed"
                  }`}
                >
                  <input
                    type="checkbox"
                    // Attaching a document that has not finished ingesting would
                    // scope the assistant to something with no chunks to search.
                    disabled={doc.status !== "ready" || saving}
                    checked={doc.attached}
                    onChange={() => toggle(doc.id)}
                    className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                  />
                  <FileText className="w-4 h-4 text-gray-500 flex-shrink-0" strokeWidth={1.75} />
                  <span className="text-[13.5px] text-gray-900 truncate flex-1 min-w-0">
                    {doc.filename}
                  </span>
                  <span className="text-xs text-gray-500 tabular-nums whitespace-nowrap">
                    {doc.chunk_count} chunks
                  </span>
                  <StatusPill status={doc.status} error={doc.error} />
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
