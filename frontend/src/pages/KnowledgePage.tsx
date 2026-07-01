import { useState, useEffect, useRef, useCallback } from "react";
import {
  listDocuments, createUpload, uploadFile, completeUpload,
  retryDocument, deleteDocument, getDocument, Document,
} from "../api/documents";
import { ApiError } from "../api/client";

const STATUS_META: Record<string, { label: string; cls: string; dot: string }> = {
  pending:   { label: "Pending",   cls: "badge-draft",   dot: "dot-draft"   },
  uploading: { label: "Uploading", cls: "badge bg-blue-50 text-blue-700",    dot: "dot-draft"  },
  uploaded:  { label: "Uploaded",  cls: "badge bg-blue-50 text-blue-700",    dot: "dot-draft"  },
  parsing:   { label: "Parsing",   cls: "badge-paused",  dot: "dot-paused"  },
  chunking:  { label: "Chunking",  cls: "badge-paused",  dot: "dot-paused"  },
  embedding: { label: "Embedding", cls: "badge-paused",  dot: "dot-paused"  },
  ready:     { label: "Indexed",   cls: "badge-live",    dot: "dot-live"    },
  failed:    { label: "Failed",    cls: "badge-error",   dot: "dot-error"   },
};

const PROCESSING = new Set(["pending", "uploading", "uploaded", "parsing", "chunking", "embedding"]);

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { label: status, cls: "badge-draft", dot: "dot-draft" };
  return (
    <span className={`badge ${m.cls} inline-flex items-center gap-1.5`}>
      <span className={m.dot} />
      {m.label}
      {PROCESSING.has(status) && (
        <svg className="w-3 h-3 animate-spin ml-0.5 opacity-70" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
      )}
    </span>
  );
}

function ConfirmModal({ filename, onConfirm, onCancel }: { filename: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="confirm-del"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="card w-full max-w-sm p-6">
        <h2 id="confirm-del" className="text-sm font-semibold text-gray-900">Delete document?</h2>
        <p className="mt-2 text-sm text-gray-600">
          <span className="font-medium">{filename}</span> and all its indexed chunks will be permanently removed.
        </p>
        <div className="mt-5 flex gap-3 justify-end">
          <button onClick={onCancel} className="btn-secondary">Cancel</button>
          <button onClick={onConfirm} className="btn-danger">Delete</button>
        </div>
      </div>
    </div>
  );
}

function FileIcon({ filename }: { filename: string }) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const colors: Record<string, string> = { pdf: "text-red-500", docx: "text-blue-500", txt: "text-gray-500", md: "text-purple-500", html: "text-orange-500" };
  return (
    <svg className={`w-8 h-8 flex-shrink-0 ${colors[ext] ?? "text-gray-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

export default function KnowledgePage() {
  const [docs,        setDocs]        = useState<Document[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading,   setUploading]   = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null);
  const [dragActive,  setDragActive]  = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef   = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDocs = useCallback(async () => {
    try {
      const data = await listDocuments();
      setDocs(data);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  // Poll processing docs every 3 s
  useEffect(() => {
    const hasProcessing = docs.some((d) => PROCESSING.has(d.status));
    if (hasProcessing && !pollingRef.current) {
      pollingRef.current = setInterval(async () => {
        const processing = docs.filter((d) => PROCESSING.has(d.status));
        const updates = await Promise.allSettled(processing.map((d) => getDocument(d.id)));
        setDocs((prev) => {
          const map = new Map(prev.map((d) => [d.id, d]));
          updates.forEach((r, i) => { if (r.status === "fulfilled") map.set(processing[i].id, r.value); });
          return Array.from(map.values());
        });
      }, 3000);
    } else if (!hasProcessing && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; } };
  }, [docs]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadError(null); setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const { document_id, upload_url } = await createUpload(file.name, file.type || "application/octet-stream", file.size);
        await uploadFile(upload_url, file);
        await completeUpload(document_id);
      }
      await fetchDocs();
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleRetry(id: string) {
    try { await retryDocument(id); await fetchDocs(); }
    catch (err) { setUploadError(err instanceof ApiError ? err.message : "Retry failed."); }
  }

  async function handleDelete(doc: Document) {
    try {
      await deleteDocument(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Delete failed.");
    } finally { setDeleteTarget(null); }
  }

  const readyCount = docs.filter((d) => d.status === "ready").length;
  const totalChunks = docs.filter((d) => d.status === "ready").reduce((s, d) => s + d.chunk_count, 0);

  return (
    <div className="page">
      {deleteTarget && (
        <ConfirmModal
          filename={deleteTarget.filename}
          onConfirm={() => handleDelete(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="page-title">Knowledge</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? "Loading…" : `${docs.length} source${docs.length !== 1 ? "s" : ""} · ${readyCount} indexed · ${totalChunks.toLocaleString()} chunks`}
          </p>
        </div>
        <label className={`btn-primary cursor-pointer ${uploading ? "opacity-60 pointer-events-none" : ""}`}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          {uploading ? "Uploading…" : "Upload files"}
        </label>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.html"
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {/* Error banner */}
      {uploadError && (
        <div role="alert" aria-live="polite" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
          <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <span className="flex-1">{uploadError}</span>
          <button onClick={() => setUploadError(null)} className="text-red-500 hover:text-red-700 ml-auto">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => { e.preventDefault(); setDragActive(false); handleFiles(e.dataTransfer.files); }}
        className={`mb-6 rounded-xl border-2 border-dashed px-8 py-10 text-center transition-colors ${
          dragActive ? "border-brand-400 bg-brand-50" : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50"
        }`}
        aria-label="Drop files here to upload"
      >
        <svg className="mx-auto w-10 h-10 text-gray-300 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.25}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.338-2.32 5.75 5.75 0 011.044 11.095" />
        </svg>
        <p className="text-sm text-gray-600 font-medium">Drop files here to upload</p>
        <p className="text-xs text-gray-400 mt-1">
          PDF, DOCX, TXT, MD, HTML · Max 100 MB per file ·{" "}
          <label className="text-brand-600 hover:text-brand-700 cursor-pointer font-medium">
            browse
            <input type="file" multiple accept=".pdf,.docx,.txt,.md,.html" className="sr-only"
              onChange={(e) => handleFiles(e.target.files)} />
          </label>
        </p>
      </div>

      {/* Stats row */}
      {!loading && docs.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="metric-card">
            <p className="metric-card-label">Total sources</p>
            <p className="metric-card-value">{docs.length}</p>
          </div>
          <div className="metric-card">
            <p className="metric-card-label">Indexed</p>
            <p className="metric-card-value text-emerald-700">{readyCount}</p>
          </div>
          <div className="metric-card">
            <p className="metric-card-label">Total chunks</p>
            <p className="metric-card-value">{totalChunks.toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* Document list */}
      {loading ? (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead><tr><th>File</th><th>Status</th><th className="text-right">Chunks</th><th /></tr></thead>
            <tbody>
              {[...Array(3)].map((_, i) => (
                <tr key={i}>
                  <td><div className="flex items-center gap-3"><div className="skeleton w-8 h-8 rounded" /><div className="skeleton h-4 w-40" /></div></td>
                  <td><div className="skeleton h-5 w-16 rounded-full" /></td>
                  <td className="text-right"><div className="skeleton h-4 w-8 ml-auto" /></td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : docs.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center">
              <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
            </div>
            <p className="empty-state-title">No knowledge sources</p>
            <p className="empty-state-desc">Upload documents to build your knowledge base. Assistants will answer only from these sources.</p>
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th className="text-right">Chunks</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      <FileIcon filename={doc.filename} />
                      <div className="min-w-0">
                        <p className="font-medium text-gray-900 truncate max-w-xs">{doc.filename}</p>
                        {doc.error && (
                          <p className="text-xs text-red-600 mt-0.5 truncate max-w-xs">{doc.error}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td><StatusBadge status={doc.status} /></td>
                  <td className="text-right tabular-nums text-gray-600">
                    {doc.chunk_count > 0 ? doc.chunk_count.toLocaleString() : <span className="text-gray-400">—</span>}
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      {doc.status === "failed" && (
                        <button onClick={() => handleRetry(doc.id)} className="btn-secondary text-xs px-2.5 py-1 h-auto">
                          Retry
                        </button>
                      )}
                      <button
                        onClick={() => setDeleteTarget(doc)}
                        aria-label={`Delete ${doc.filename}`}
                        className="p-1.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Info card */}
      <div className="mt-6 rounded-xl bg-blue-50 border border-blue-100 px-5 py-4 text-sm text-blue-900">
        <p className="font-semibold mb-1">How knowledge indexing works</p>
        <p className="text-blue-800/80 text-xs leading-relaxed">
          Uploaded files are parsed, split into chunks, and embedded into a vector store.
          Indexing typically takes 30 seconds to 3 minutes depending on document size.
          Once <strong>Indexed</strong>, the document is available to all assistants that include this source.
        </p>
      </div>
    </div>
  );
}
