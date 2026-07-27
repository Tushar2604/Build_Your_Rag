import { useState, useEffect, useRef, FormEvent } from "react";
import { Link } from "react-router-dom";
import { listInterviews, scheduleInterview, Interview } from "../api/interviews";
import { listDocuments, createUpload, uploadFile, completeUpload, getDocument, Document } from "../api/documents";
import { ApiError } from "../api/client";

type ResumeUploadStatus = "idle" | "uploading" | "processing" | "ready" | "failed";

function StatusBadge({ status }: { status: Interview["status"] }) {
  const map: Record<Interview["status"], string> = {
    scheduled: "badge-draft",
    in_progress: "badge-live",
    completed: "badge-live",
    cancelled: "badge-paused",
  };
  const label: Record<Interview["status"], string> = {
    scheduled: "Scheduled",
    in_progress: "In progress",
    completed: "Completed",
    cancelled: "Cancelled",
  };
  return <span className={`badge ${map[status]}`}>{label[status]}</span>;
}

function VerdictBadge({ verdict }: { verdict: Interview["overall_verdict"] }) {
  if (!verdict) return <span className="text-gray-300 text-xs">—</span>;
  const styles: Record<string, string> = {
    strong_hire: "text-emerald-700 bg-emerald-50",
    hire: "text-emerald-700 bg-emerald-50",
    maybe: "text-amber-700 bg-amber-50",
    no_hire: "text-red-700 bg-red-50",
  };
  const label: Record<string, string> = {
    strong_hire: "Strong Hire",
    hire: "Hire",
    maybe: "Maybe",
    no_hire: "No Hire",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium ${styles[verdict]}`}>
      {label[verdict]}
    </span>
  );
}

function ScheduleModal({
  documents,
  onCreate,
  onClose,
}: {
  documents: Document[];
  onCreate: (i: Interview) => void;
  onClose: () => void;
}) {
  const [candidateName, setCandidateName] = useState("");
  const [candidateEmail, setCandidateEmail] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [jobDocId, setJobDocId] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Interview | null>(null);

  // Resume: upload a PDF (or doc/txt) right here — it goes through the exact
  // same ingest-and-embed pipeline as any Knowledge document, it just doesn't
  // need to already exist there. "Choose existing" stays available for
  // reusing a resume already in the knowledge base.
  const [resumeMode, setResumeMode] = useState<"upload" | "existing">("upload");
  const [resumeDocId, setResumeDocId] = useState("");
  const [resumeFilename, setResumeFilename] = useState("");
  const [resumeStatus, setResumeStatus] = useState<ResumeUploadStatus>("idle");
  const [resumeError, setResumeError] = useState<string | null>(null);
  const resumeInputRef = useRef<HTMLInputElement>(null);
  const resumePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const readyDocs = documents.filter((d) => d.status === "ready");

  useEffect(() => () => { if (resumePollRef.current) clearInterval(resumePollRef.current); }, []);

  async function handleResumeFile(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setResumeError(null);
    setResumeDocId("");
    setResumeFilename(file.name);
    setResumeStatus("uploading");
    try {
      const { document_id, upload_url } = await createUpload(file.name, file.type || "application/octet-stream", file.size);
      await uploadFile(upload_url, file);
      await completeUpload(document_id);
      setResumeStatus("processing");

      if (resumePollRef.current) clearInterval(resumePollRef.current);
      resumePollRef.current = setInterval(async () => {
        try {
          const doc = await getDocument(document_id);
          if (doc.status === "ready") {
            setResumeStatus("ready");
            setResumeDocId(document_id);
            if (resumePollRef.current) { clearInterval(resumePollRef.current); resumePollRef.current = null; }
          } else if (doc.status === "failed") {
            setResumeStatus("failed");
            setResumeError(doc.error || "Failed to process resume.");
            if (resumePollRef.current) { clearInterval(resumePollRef.current); resumePollRef.current = null; }
          }
        } catch {
          // transient — keep polling
        }
      }, 2000);
    } catch (err) {
      setResumeStatus("failed");
      setResumeError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      if (resumeInputRef.current) resumeInputRef.current.value = "";
    }
  }

  function switchResumeMode(mode: "upload" | "existing") {
    setResumeMode(mode);
    setResumeDocId("");
    setResumeFilename("");
    setResumeStatus("idle");
    setResumeError(null);
    if (resumePollRef.current) { clearInterval(resumePollRef.current); resumePollRef.current = null; }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!jobDocId || !resumeDocId || !scheduledAt) return;
    setLoading(true);
    setError(null);
    try {
      const iv = await scheduleInterview({
        candidate_name: candidateName,
        candidate_email: candidateEmail,
        role_title: roleTitle,
        job_document_id: jobDocId,
        resume_document_id: resumeDocId,
        scheduled_at: new Date(scheduledAt).toISOString(),
      });
      setResult(iv);
      onCreate(iv);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to schedule interview.");
    } finally {
      setLoading(false);
    }
  }

  function copy(val: string) {
    navigator.clipboard.writeText(val);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 backdrop-blur-sm px-4 animate-fade-in"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">
            {result ? "Interview scheduled" : "Schedule an interview"}
          </h2>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {result ? (
          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-gray-600">
              {result.candidate_name || "The candidate"} has {result.email_sent ? "been emailed" : "not been emailed (no email provider configured)"} their interview link.
              {result.calendar_created
                ? " It's also been added to your Google Calendar."
                : " Connect Google Calendar in Settings to auto-add these to your calendar."}
            </p>
            <div>
              <label className="label">Interview link</label>
              <div className="flex items-center gap-2">
                <input readOnly value={result.join_url} className="input flex-1 text-xs font-mono" />
                <button type="button" onClick={() => copy(result.join_url)} className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap">
                  Copy
                </button>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <button type="button" onClick={onClose} className="btn-primary">Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreate}>
            <div className="px-6 py-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Candidate name</label>
                  <input className="input" value={candidateName} onChange={(e) => setCandidateName(e.target.value)}
                    placeholder="Auto-detected from resume" maxLength={200} />
                </div>
                <div>
                  <label className="label">Candidate email *</label>
                  <input type="email" required className="input" value={candidateEmail}
                    onChange={(e) => setCandidateEmail(e.target.value)} />
                </div>
              </div>
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
                {readyDocs.length === 0 && (
                  <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-2">
                    No ready documents yet. <Link to="/knowledge" className="underline">Upload a job description</Link> first.
                  </p>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="label !mb-0">Resume *</label>
                  <div className="segmented">
                    <button type="button" onClick={() => switchResumeMode("upload")}
                      className={resumeMode === "upload" ? "segmented-item-active" : "segmented-item"}>
                      Upload PDF
                    </button>
                    <button type="button" onClick={() => switchResumeMode("existing")}
                      className={resumeMode === "existing" ? "segmented-item-active" : "segmented-item"}>
                      Choose existing
                    </button>
                  </div>
                </div>

                {resumeMode === "upload" ? (
                  <div>
                    <label className={`flex items-center gap-3 rounded-lg border-2 border-dashed px-4 py-3 cursor-pointer transition-colors ${
                      resumeStatus === "failed" ? "border-red-200 bg-red-50" : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                    }`}>
                      <svg className="w-5 h-5 flex-shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                      </svg>
                      <span className="text-sm text-gray-600 flex-1 min-w-0 truncate">
                        {resumeFilename || "Click to upload the candidate's resume (PDF, DOCX, or TXT)"}
                      </span>
                      <input ref={resumeInputRef} type="file" accept=".pdf,.docx,.txt,.md" className="sr-only"
                        onChange={(e) => handleResumeFile(e.target.files)} />
                    </label>
                    {resumeStatus === "uploading" && (
                      <p className="text-xs text-gray-400 mt-1.5 flex items-center gap-1.5">
                        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" /></svg>
                        Uploading…
                      </p>
                    )}
                    {resumeStatus === "processing" && (
                      <p className="text-xs text-gray-400 mt-1.5 flex items-center gap-1.5">
                        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" /></svg>
                        Processing and embedding resume…
                      </p>
                    )}
                    {resumeStatus === "ready" && (
                      <p className="text-xs text-emerald-600 mt-1.5">✓ Resume indexed and ready</p>
                    )}
                    {resumeStatus === "failed" && (
                      <p className="text-xs text-red-600 mt-1.5">{resumeError || "Failed to process resume."}</p>
                    )}
                  </div>
                ) : (
                  <>
                    <select required className="input" value={resumeDocId} onChange={(e) => setResumeDocId(e.target.value)}>
                      <option value="">Select a document…</option>
                      {readyDocs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
                    </select>
                    {readyDocs.length === 0 && (
                      <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-2">
                        No ready documents yet — switch to "Upload PDF" instead.
                      </p>
                    )}
                  </>
                )}
              </div>
              <div>
                <label className="label">Scheduled for *</label>
                <input type="datetime-local" required className="input" value={scheduledAt}
                  onChange={(e) => setScheduledAt(e.target.value)} />
                <p className="text-xs text-gray-400 mt-1">The candidate can join once this time arrives.</p>
              </div>
              {error && (
                <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/60">
              <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={loading || !jobDocId || !resumeDocId || !scheduledAt || !candidateEmail} className="btn-primary">
                {loading ? "Scheduling…" : "Schedule interview →"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function InterviewsPage() {
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    Promise.all([listInterviews(), listDocuments()])
      .then(([i, d]) => { setInterviews(i); setDocuments(d); })
      .finally(() => setLoading(false));
  }, []);

  function handleCreated(iv: Interview) {
    setInterviews((prev) => [iv, ...prev]);
  }

  return (
    <div className="page">
      {showCreate && (
        <ScheduleModal documents={documents} onCreate={handleCreated} onClose={() => setShowCreate(false)} />
      )}

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="page-title">Interviews</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? "Loading…" : `${interviews.length} interview${interviews.length !== 1 ? "s" : ""} scheduled`}
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Schedule interview
        </button>
      </div>

      {loading ? (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead><tr><th>Candidate</th><th>Role</th><th>Status</th><th>Scheduled</th><th>Verdict</th><th /></tr></thead>
            <tbody>
              {[...Array(3)].map((_, i) => (
                <tr key={i}><td colSpan={6}><div className="skeleton h-5 w-full" /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : interviews.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="w-12 h-12 rounded-xl bg-brand-50 flex items-center justify-center">
              <svg className="w-6 h-6 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </div>
            <p className="empty-state-title">No interviews yet</p>
            <p className="empty-state-desc">
              Schedule a virtual interview: pick a job description and resume, and an AI interviewer conducts it by voice — scored and reported automatically.
            </p>
            <button onClick={() => setShowCreate(true)} className="btn-primary mt-5">
              Schedule your first interview
            </button>
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Role</th>
                <th>Status</th>
                <th>Scheduled</th>
                <th>Verdict</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {interviews.map((iv) => (
                <tr key={iv.id}>
                  <td>
                    <Link to={`/interviews/${iv.id}`} className="font-medium text-gray-900 hover:text-brand-700 transition-colors">
                      {iv.candidate_name || iv.candidate_email}
                    </Link>
                  </td>
                  <td className="text-gray-500">{iv.role_title || "—"}</td>
                  <td><StatusBadge status={iv.status} /></td>
                  <td className="text-gray-500 text-xs tabular-nums">
                    {new Date(iv.scheduled_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td><VerdictBadge verdict={iv.overall_verdict} /></td>
                  <td className="text-right">
                    <Link to={`/interviews/${iv.id}`} className="text-xs text-brand-600 hover:text-brand-700 font-medium">
                      Open →
                    </Link>
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
