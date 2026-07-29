import { useEffect, useRef, useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listDocuments, Document, createUpload, uploadFile, completeUpload } from "../api/documents";
import {
  createInterviewBatch,
  getInterviewBatch,
  attachBatchResume,
  extractBatchCandidates,
  updateBatchCandidate,
  sendInterviewBatch,
  InterviewBatch,
  BatchCandidate,
} from "../api/interviewBatches";
import { ApiError } from "../api/client";

type Step = "setup" | "upload" | "review" | "send";

interface ResumeRow {
  filename: string;
  status: "queued" | "uploading" | "attaching" | "done" | "failed";
  error?: string;
}

const UPLOAD_CONCURRENCY = 4;
const POLL_INTERVAL_MS = 2000;

function looksLikeEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim());
}

const CANDIDATE_STATUS_BADGE: Record<BatchCandidate["status"], string> = {
  ingesting: "badge-draft",
  needs_review: "badge-draft",
  excluded: "badge-paused",
  scheduled: "badge-live",
  failed: "badge-error",
};

const CANDIDATE_STATUS_LABEL: Record<BatchCandidate["status"], string> = {
  ingesting: "Processing…",
  needs_review: "Ready to review",
  excluded: "Excluded",
  scheduled: "Scheduled",
  failed: "Failed",
};

export default function BulkInterviewPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("setup");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);

  // Setup
  const [roleTitle, setRoleTitle] = useState("");
  const [jobDocId, setJobDocId] = useState("");
  const [opensAt, setOpensAt] = useState("");
  const [hasDeadline, setHasDeadline] = useState(false);
  const [closesAt, setClosesAt] = useState("");
  const [customQuestions, setCustomQuestions] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [batch, setBatch] = useState<InterviewBatch | null>(null);

  // Upload
  const [rows, setRows] = useState<ResumeRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Extract/review
  const [extracting, setExtracting] = useState(false);
  const [candidates, setCandidates] = useState<BatchCandidate[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listDocuments().then(setDocuments).finally(() => setLoadingDocs(false));
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const readyDocs = documents.filter((d) => d.status === "ready");

  async function handleCreateBatch(e: FormEvent) {
    e.preventDefault();
    if (!jobDocId || !opensAt) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createInterviewBatch({
        role_title: roleTitle,
        job_document_id: jobDocId,
        window_opens_at: new Date(opensAt).toISOString(),
        window_closes_at: hasDeadline && closesAt ? new Date(closesAt).toISOString() : null,
        custom_questions: customQuestions.split("\n").map((q) => q.trim()).filter(Boolean),
      });
      setBatch(created);
      setStep("upload");
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to create batch.");
    } finally {
      setCreating(false);
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files || !files.length || !batch) return;
    const batchId = batch.id;
    const fileList = Array.from(files);
    setRows(fileList.map((f) => ({ filename: f.name, status: "queued" })));
    setUploading(true);

    let cursor = 0;
    function updateRow(i: number, patch: Partial<ResumeRow>) {
      setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
    }
    async function worker() {
      while (true) {
        const i = cursor++;
        if (i >= fileList.length) return;
        const file = fileList[i];
        updateRow(i, { status: "uploading" });
        try {
          const { document_id, upload_url } = await createUpload(
            file.name, file.type || "application/octet-stream", file.size,
          );
          await uploadFile(upload_url, file);
          await completeUpload(document_id);
          updateRow(i, { status: "attaching" });
          await attachBatchResume(batchId, document_id, file.name);
          updateRow(i, { status: "done" });
        } catch (err) {
          updateRow(i, {
            status: "failed",
            error: err instanceof ApiError ? err.message : "Upload failed.",
          });
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, fileList.length) }, worker));
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const attachedCount = rows.filter((r) => r.status === "done").length;
  const failedUploadCount = rows.filter((r) => r.status === "failed").length;
  const uploadQueueSettled = rows.length > 0 && !uploading;

  async function handleProcessResumes() {
    if (!batch) return;
    setExtracting(true);
    await extractBatchCandidates(batch.id);
    pollRef.current = setInterval(async () => {
      const fresh = await getInterviewBatch(batch.id);
      setCandidates(fresh.candidates);
      const stillIngesting = fresh.candidates.some((c) => c.status === "ingesting");
      if (!stillIngesting) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        setExtracting(false);
        setStep("review");
      }
    }, POLL_INTERVAL_MS);
  }

  function patchCandidateLocal(id: string, patch: Partial<BatchCandidate>) {
    setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  async function commitCandidateField(id: string, field: "candidate_name" | "candidate_email", value: string) {
    if (!batch) return;
    try {
      await updateBatchCandidate(batch.id, id, { [field]: value });
    } catch {
      // best-effort — the row stays editable, admin can retry the edit
    }
  }

  async function toggleExclude(id: string, excluded: boolean) {
    if (!batch) return;
    patchCandidateLocal(id, { status: excluded ? "excluded" : "needs_review" });
    try {
      await updateBatchCandidate(batch.id, id, { excluded });
    } catch {
      // best-effort
    }
  }

  const sendableCandidates = candidates.filter(
    (c) => c.status === "needs_review" && looksLikeEmail(c.candidate_email),
  );
  const missingEmailCount = candidates.filter(
    (c) => c.status === "needs_review" && !looksLikeEmail(c.candidate_email),
  ).length;

  async function handleSend() {
    if (!batch) return;
    const batchId = batch.id;
    setStep("send");
    await sendInterviewBatch(batchId);
    pollRef.current = setInterval(async () => {
      const fresh = await getInterviewBatch(batchId);
      setBatch(fresh);
      setCandidates(fresh.candidates);
      if (fresh.status === "completed" && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, POLL_INTERVAL_MS);
  }

  const progressTotal = batch ? batch.sent_count + batch.failed_count : 0;
  const progressPct = batch && sendableCandidates.length > 0
    ? Math.min(100, Math.round((progressTotal / sendableCandidates.length) * 100))
    : 0;

  return (
    <div className="page max-w-3xl">
      <div className="flex items-center gap-2 mb-1">
        <Link to="/interviews" className="text-xs text-gray-400 hover:text-gray-600">Interviews</Link>
        <span className="text-xs text-gray-300">/</span>
        <span className="text-xs text-gray-600 font-medium">Bulk invite</span>
      </div>
      <h1 className="page-title mb-6">Bulk interview invites</h1>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-6 text-xs text-gray-400">
        {(["setup", "upload", "review", "send"] as Step[]).map((s, i) => (
          <span key={s} className={`flex items-center gap-2 ${step === s ? "text-brand-700 font-semibold" : ""}`}>
            {i > 0 && <span className="text-gray-300">→</span>}
            {i + 1}. {s === "setup" ? "Setup" : s === "upload" ? "Upload resumes" : s === "review" ? "Review" : "Send"}
          </span>
        ))}
      </div>

      {step === "setup" && (
        <form onSubmit={handleCreateBatch} className="card p-6 space-y-4">
          <div>
            <label className="label">Role title</label>
            <input className="input" value={roleTitle} onChange={(e) => setRoleTitle(e.target.value)}
              placeholder="Backend Engineer" maxLength={200} />
          </div>
          <div>
            <label className="label">Job description *</label>
            <select required className="input" value={jobDocId} onChange={(e) => setJobDocId(e.target.value)}>
              <option value="">Select a document…</option>
              {readyDocs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
            {!loadingDocs && readyDocs.length === 0 && (
              <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-2">
                No ready documents yet. <Link to="/knowledge" className="underline">Upload a job description</Link> first.
              </p>
            )}
          </div>
          <div>
            <label className="label">Custom questions (optional, one per line)</label>
            <textarea
              className="input resize-none text-xs leading-relaxed"
              rows={3}
              placeholder={"e.g. What's your experience with distributed systems?\nWalk me through a time you disagreed with a teammate."}
              value={customQuestions}
              onChange={(e) => setCustomQuestions(e.target.value)}
            />
            <p className="text-xs text-gray-400 mt-1">
              Asked first for every candidate in this batch. We'll add a few more from the job description
              and each resume if you give us fewer than 4.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Opens at *</label>
              <input type="datetime-local" required className="input" value={opensAt}
                onChange={(e) => setOpensAt(e.target.value)} />
            </div>
            <div>
              <label className="flex items-center gap-2 label !mb-1.5">
                <input type="checkbox" checked={hasDeadline}
                  onChange={(e) => setHasDeadline(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                Add a deadline
              </label>
              <input type="datetime-local" disabled={!hasDeadline} className="input" value={closesAt}
                onChange={(e) => setClosesAt(e.target.value)} />
            </div>
          </div>
          <p className="text-xs text-gray-400">
            Each candidate gets a self-service link — no fixed meeting slot. It opens at the time above
            {hasDeadline ? " and stays valid until the deadline." : " and stays open indefinitely once it does."}
          </p>
          {createError && (
            <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{createError}</div>
          )}
          <div className="flex justify-end pt-2">
            <button type="submit" disabled={creating || !jobDocId || !opensAt} className="btn-primary">
              {creating ? "Creating…" : "Continue →"}
            </button>
          </div>
        </form>
      )}

      {step === "upload" && batch && (
        <div className="card p-6 space-y-4">
          <div>
            <label className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 cursor-pointer transition-colors ${
              uploading ? "border-gray-200 bg-gray-50" : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
            }`}>
              <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <span className="text-sm text-gray-600">
                {rows.length > 0 ? "Add more resumes" : "Click to select resume files (PDF, DOCX, TXT) — select as many as you like"}
              </span>
              <input ref={fileInputRef} type="file" multiple accept=".pdf,.docx,.txt,.md" className="sr-only"
                disabled={uploading} onChange={(e) => handleFiles(e.target.files)} />
            </label>
          </div>

          {rows.length > 0 && (
            <div className="max-h-64 overflow-y-auto border border-gray-100 rounded-lg divide-y divide-gray-50">
              {rows.map((r, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 text-xs">
                  <span className="text-gray-700 truncate flex-1 min-w-0">{r.filename}</span>
                  <span className={
                    r.status === "done" ? "text-emerald-600"
                    : r.status === "failed" ? "text-red-600"
                    : "text-gray-400"
                  }>
                    {r.status === "queued" && "Queued…"}
                    {r.status === "uploading" && "Uploading…"}
                    {r.status === "attaching" && "Attaching…"}
                    {r.status === "done" && "✓ Ready"}
                    {r.status === "failed" && (r.error || "Failed")}
                  </span>
                </div>
              ))}
            </div>
          )}

          <p className="text-xs text-gray-400">
            {attachedCount} attached{failedUploadCount > 0 ? `, ${failedUploadCount} failed` : ""} of {rows.length}
          </p>

          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={handleProcessResumes}
              disabled={!uploadQueueSettled || attachedCount === 0 || extracting}
              className="btn-primary"
            >
              {extracting ? "Processing…" : `Process ${attachedCount || ""} resume${attachedCount === 1 ? "" : "s"} →`}
            </button>
          </div>
        </div>
      )}

      {step === "review" && batch && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-900">Review candidates</p>
            <p className="text-xs text-gray-500">
              {sendableCandidates.length} ready to send
              {missingEmailCount > 0 && <span className="text-amber-700"> · {missingEmailCount} need an email</span>}
            </p>
          </div>
          <div className="max-h-[28rem] overflow-y-auto">
            <table className="data-table">
              <thead>
                <tr><th>Resume</th><th>Name</th><th>Email</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <tr key={c.id} className={c.status === "excluded" ? "opacity-50" : ""}>
                    <td className="text-gray-500 text-xs max-w-[10rem] truncate" title={c.resume_filename}>
                      {c.resume_filename}
                    </td>
                    <td>
                      <input
                        className="input text-xs py-1"
                        defaultValue={c.candidate_name}
                        disabled={c.status === "excluded"}
                        onBlur={(e) => commitCandidateField(c.id, "candidate_name", e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        className={`input text-xs py-1 ${!looksLikeEmail(c.candidate_email) && c.status !== "excluded" ? "border-amber-300" : ""}`}
                        defaultValue={c.candidate_email}
                        disabled={c.status === "excluded"}
                        placeholder="candidate@email.com"
                        onBlur={(e) => commitCandidateField(c.id, "candidate_email", e.target.value)}
                      />
                    </td>
                    <td>
                      <span className={`badge ${CANDIDATE_STATUS_BADGE[c.status]}`} title={c.error || undefined}>
                        {CANDIDATE_STATUS_LABEL[c.status]}
                      </span>
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        onClick={() => toggleExclude(c.id, c.status !== "excluded")}
                        className="text-xs text-gray-400 hover:text-red-600"
                      >
                        {c.status === "excluded" ? "Include" : "Exclude"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-100 bg-gray-50/60">
            <button type="button" onClick={handleSend} disabled={sendableCandidates.length === 0} className="btn-primary">
              Invite {sendableCandidates.length} candidate{sendableCandidates.length === 1 ? "" : "s"} →
            </button>
          </div>
        </div>
      )}

      {step === "send" && batch && (
        <div className="card p-6 space-y-4">
          <p className="text-sm text-gray-700">
            {batch.status === "completed" ? "Done." : "Sending invites…"} {progressTotal} of {sendableCandidates.length} processed
            {batch.failed_count > 0 && <span className="text-amber-700"> ({batch.failed_count} failed)</span>}.
          </p>
          <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden">
            <div className="h-full bg-brand-500 transition-all" style={{ width: `${progressPct}%` }} />
          </div>
          {batch.status === "completed" && (
            <div className="flex justify-end pt-2">
              <button type="button" onClick={() => navigate("/interviews")} className="btn-primary">
                View interviews →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
