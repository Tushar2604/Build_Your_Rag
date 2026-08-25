import { useState, useEffect, useRef, useCallback } from "react";
import {
  listDocuments,
  createUpload,
  uploadFile,
  completeUpload,
  retryDocument,
  deleteDocument,
  getDocument,
  Document,
} from "../api/documents";
import { ApiError } from "../api/client";

const STATUS_COLORS: Record<string, string> = {
  pending:   "bg-gray-100 text-gray-600",
  uploading: "bg-blue-100 text-blue-700",
  uploaded:  "bg-blue-100 text-blue-700",
  parsing:   "bg-yellow-100 text-yellow-700",
  chunking:  "bg-yellow-100 text-yellow-700",
  embedding: "bg-purple-100 text-purple-700",
  ready:     "bg-green-100 text-green-700",
  failed:    "bg-red-100 text-red-700",
};

const PROCESSING_STATUSES = new Set(["pending", "uploading", "uploaded", "parsing", "chunking", "embedding"]);

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${STATUS_COLORS[status] ?? "bg-gray-100 text-gray-600"}`}>
      {status}
    </span>
  );
}

function ConfirmModal({
  filename,
  onConfirm,
  onCancel,
}: {
  filename: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      className="modal-overlay"
    >
      <div className="card w-full max-w-sm p-6">
        <h2 id="confirm-title" className="text-base font-semibold text-gray-900">
          Delete document?
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          <span className="font-medium">{filename}</span> and all its chunks will be permanently removed.
        </p>
        <div className="mt-5 flex gap-3 justify-end">
          <button onClick={onCancel} className="btn-secondary">Cancel</button>
          <button onClick={onConfirm} className="btn-danger">Delete</button>
        </div>
      </div>
    </div>
  );
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDocs = useCallback(async () => {
    try {
      const data = await listDocuments();
      setDocs(data);
    } catch {
      // silently fail on background polls
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  // Poll processing documents every 3 s
  useEffect(() => {
    const hasProcessing = docs.some((d) => PROCESSING_STATUSES.has(d.status));
    if (hasProcessing && !pollingRef.current) {
      pollingRef.current = setInterval(async () => {
        const processing = docs.filter((d) => PROCESSING_STATUSES.has(d.status));
        const updates = await Promise.allSettled(processing.map((d) => getDocument(d.id)));
        setDocs((prev) => {
          const map = new Map(prev.map((d) => [d.id, d]));
          updates.forEach((r, i) => {
            if (r.status === "fulfilled") map.set(processing[i].id, r.value);
          });
          return Array.from(map.values());
        });
      }, 3000);
    } else if (!hasProcessing && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [docs]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const { document_id, upload_url } = await createUpload(
          file.name,
          file.type || "application/octet-stream",
          file.size,
        );
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
    try {
      await retryDocument(id);
      await fetchDocs();
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Retry failed.");
    }
  }

  async function handleDelete(doc: Document) {
    try {
      await deleteDocument(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 sm:px-6">
      {deleteTarget && (
        <ConfirmModal
          filename={deleteTarget.filename}
          onConfirm={() => handleDelete(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Upload files to build your knowledge base
          </p>
        </div>
        <label
          htmlFor="file-upload"
          className={`btn-primary cursor-pointer ${uploading ? "opacity-60 pointer-events-none" : ""}`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          {uploading ? "Uploading…" : "Upload files"}
        </label>
        <input
          ref={fileInputRef}
          id="file-upload"
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.html"
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {uploadError && (
        <div role="alert" aria-live="polite" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {uploadError}
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
        className="mb-6 rounded-xl border-2 border-dashed border-gray-200 bg-surface px-6 py-10 text-center hover:border-brand-400 hover:bg-brand-50/30 transition-colors"
        aria-label="Drop files here to upload"
      >
        <svg className="mx-auto w-10 h-10 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>
        <p className="text-sm text-gray-500">
          Drop PDF, DOCX, TXT, MD, or HTML files here, or{" "}
          <label htmlFor="file-upload" className="font-medium text-brand-600 hover:text-brand-700 cursor-pointer">
            browse
          </label>
        </p>
      </div>

      {loading ? (
        <div aria-live="polite" className="text-center py-16 text-sm text-gray-400">
          Loading documents…
        </div>
      ) : docs.length === 0 ? (
        <div className="text-center py-16 text-sm text-gray-400">
          No documents yet — upload one to get started.
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60">
                <th scope="col" className="text-left font-medium text-gray-500 px-4 py-3">File</th>
                <th scope="col" className="text-left font-medium text-gray-500 px-4 py-3">Status</th>
                <th scope="col" className="text-right font-medium text-gray-500 px-4 py-3 font-variant-numeric tabular-nums">Chunks</th>
                <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {docs.map((doc) => (
                <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-medium text-gray-800 truncate max-w-xs block">{doc.filename}</span>
                    {doc.error && (
                      <span className="text-xs text-red-600 mt-0.5 block truncate max-w-xs">{doc.error}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={doc.status} />
                      {PROCESSING_STATUSES.has(doc.status) && (
                        <svg aria-label="Processing" className="w-3.5 h-3.5 text-gray-400 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                    {doc.chunk_count > 0 ? doc.chunk_count.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      {doc.status === "failed" && (
                        <button
                          onClick={() => handleRetry(doc.id)}
                          className="btn-secondary text-xs px-2.5 py-1"
                        >
                          Retry
                        </button>
                      )}
                      <button
                        onClick={() => setDeleteTarget(doc)}
                        aria-label={`Delete ${doc.filename}`}
                        className="p-1.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
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
    </div>
  );
}
