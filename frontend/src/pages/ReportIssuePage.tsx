// Report Issue — send a bug report or feature request to the team.
//
// The form stays filled after a failed submit and only clears on success: a
// long description is expensive to retype, and a validation error should never
// cost the user their words.
import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import DictateButton from "../components/DictateButton";
import {
  IssueOptions,
  IssueReport,
  Priority,
  ReportType,
  createIssue,
  getIssueOptions,
  listIssues,
} from "../api/support";

const PRIORITY_STYLES: Record<Priority, string> = {
  low: "text-gray-600",
  medium: "text-blue-700",
  high: "text-amber-700",
  critical: "text-red-700",
};

const STATUS_STYLES: Record<IssueReport["status"], string> = {
  open: "bg-blue-100 text-blue-700",
  in_progress: "bg-amber-100 text-amber-700",
  resolved: "bg-emerald-100 text-emerald-700",
  closed: "bg-gray-100 text-gray-600",
};

const MAX_DESCRIPTION = 5000;

export default function ReportIssuePage() {
  const [options, setOptions] = useState<IssueOptions | null>(null);
  const [past, setPast] = useState<IssueReport[]>([]);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [reportType, setReportType] = useState<ReportType | "">("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<IssueReport | null>(null);

  useEffect(() => {
    getIssueOptions().then(setOptions).catch(() => setOptions(null));
    // A 403 here just means this account isn't an admin — the form still works,
    // so the history section is simply omitted rather than surfacing an error.
    listIssues().then(setPast).catch(() => setPast([]));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!reportType) {
      setError("Choose what kind of report this is.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const report = await createIssue({
        name,
        email,
        phone,
        report_type: reportType,
        priority,
        subject,
        description,
        page_url: window.location.href,
      });
      setSent(report);
      setSubject("");
      setDescription("");
      setPast((p) => [report, ...p]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send your report.");
    } finally {
      setSaving(false);
    }
  }

  if (sent) {
    return (
      <div className="page-sm">
        <div className="card p-8 text-center">
          <div className="text-3xl mb-3">✅</div>
          <h1 className="page-title">Thanks — we've got it.</h1>
          <p className="text-sm text-gray-500 mt-2">
            Your report was recorded
            {sent.email_sent
              ? " and emailed to the team."
              : ". Email delivery isn't configured on this server, so the team will pick it up from the list below."}
          </p>
          <p className="text-xs text-gray-400 mt-3 font-mono">
            Reference: {sent.id.slice(0, 8)}
          </p>
          <button
            type="button"
            onClick={() => setSent(null)}
            className="btn-secondary text-sm mt-6"
          >
            Report something else
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page-sm">
      <div className="page-header">
        <div>
          <h1 className="page-title">Report Issue</h1>
          <p className="text-sm text-gray-500 mt-1">
            Help us improve by reporting bugs or requesting new features. Your
            feedback is valuable to us.
          </p>
        </div>
      </div>

      {options && !options.support_email_configured && (
        <div className="mb-4 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800">
          Email delivery isn't configured on this server (needs SUPPORT_EMAIL and
          RESEND_API_KEY). Reports are still saved and listed below.
        </div>
      )}

      <form onSubmit={submit} className="space-y-6">
        <div className="card p-5">
          <h2 className="section-title mb-4">Contact Information</h2>
          <div className="space-y-4">
            <div>
              <label className="label">Name *</label>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                maxLength={160}
                required
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Email *</label>
                <input
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  required
                />
              </div>
              <div>
                <label className="label">Phone number</label>
                <input
                  className="input"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+1 555 123 4567"
                  maxLength={32}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="card p-5">
          <h2 className="section-title mb-4">Issue Type</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">What type of report is this? *</label>
              <select
                className="input"
                value={reportType}
                onChange={(e) => setReportType(e.target.value as ReportType)}
                required
              >
                <option value="">Select report type</option>
                {(options?.report_types ?? []).map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Priority *</label>
              <select
                className="input"
                value={priority}
                onChange={(e) => setPriority(e.target.value as Priority)}
              >
                {(options?.priorities ?? []).map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="card p-5">
          <h2 className="section-title mb-4">Details</h2>
          <div className="space-y-4">
            <div>
              <label className="label">Summary *</label>
              <input
                className="input"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Broadcast campaign stops at 20 contacts"
                maxLength={200}
                required
              />
            </div>
            <div>
              <label className="label">Description *</label>
              <div className="relative">
                <textarea
                  className="input resize-y pb-12"
                  rows={7}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={MAX_DESCRIPTION}
                  placeholder="What did you expect to happen, and what happened instead? Steps to reproduce help a lot."
                  required
                />
                {/* Describing a bug out loud is faster than typing it, and the
                    people filing these are usually mid-interruption. */}
                <DictateButton
                  value={description}
                  onChange={setDescription}
                  className="absolute bottom-3 right-3"
                />
              </div>
              <p className="text-xs text-gray-400 text-right mt-1 tabular-nums">
                {description.length}/{MAX_DESCRIPTION}
                {description.length > 0 && description.length < 20 && (
                  <span className="text-amber-600"> · at least 20 characters</span>
                )}
              </p>
            </div>
          </div>
        </div>

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <button type="submit" disabled={saving} className="btn-primary w-full">
          {saving ? "Sending…" : "Submit report"}
        </button>
      </form>

      {past.length > 0 && (
        <div className="card p-5 mt-8">
          <h2 className="section-title mb-4">Your team's recent reports</h2>
          <ul className="space-y-3">
            {past.slice(0, 10).map((r) => (
              <li key={r.id} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-gray-900 truncate">{r.subject}</p>
                  <p className="text-xs text-gray-400">
                    <span className={PRIORITY_STYLES[r.priority]}>{r.priority}</span>
                    {" · "}
                    {new Date(r.created_at).toLocaleDateString()}
                    {!r.email_sent && " · not emailed"}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${STATUS_STYLES[r.status]}`}
                >
                  {r.status.replace("_", " ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
