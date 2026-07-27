import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { getInterview, interviewReportUrl, Interview } from "../api/interviews";

const VERDICT_LABEL: Record<string, string> = {
  strong_hire: "Strong Hire",
  hire: "Hire",
  maybe: "Maybe",
  no_hire: "No Hire",
};

function ScoreBar({ score }: { score: number }) {
  const color = score >= 4 ? "bg-emerald-500" : score >= 3 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${(score / 5) * 100}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums">{score}/5</span>
    </div>
  );
}

export default function InterviewDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    getInterview(id)
      .then(setInterview)
      .catch((e) => setError(e.message ?? "Failed to load interview."))
      .finally(() => setLoading(false));
  }, [id]);

  async function downloadReport() {
    setDownloading(true);
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(interviewReportUrl(id), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Failed to download report");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `interview-${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="skeleton h-6 w-48 mb-2" />
        <div className="skeleton h-4 w-32" />
      </div>
    );
  }

  if (error || !interview) {
    return (
      <div className="page">
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error ?? "Interview not found."}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link to="/interviews" className="text-xs text-gray-400 hover:text-gray-600">Interviews</Link>
            <span className="text-xs text-gray-300">/</span>
            <span className="text-xs text-gray-600 font-medium">{interview.candidate_name || interview.candidate_email}</span>
          </div>
          <h1 className="page-title">{interview.candidate_name || interview.candidate_email}</h1>
          <p className="text-xs text-gray-500 mt-1">
            {interview.role_title || "Unspecified role"} · Scheduled{" "}
            {new Date(interview.scheduled_at).toLocaleString()}
          </p>
        </div>
        {interview.has_report && (
          <button onClick={downloadReport} disabled={downloading} className="btn-primary">
            {downloading ? "Downloading…" : "Download PDF report"}
          </button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="metric-card">
          <p className="metric-card-label">Status</p>
          <p className="metric-card-value capitalize">{interview.status.replace("_", " ")}</p>
        </div>
        <div className="metric-card">
          <p className="metric-card-label">Overall score</p>
          <p className="metric-card-value">{interview.overall_score !== null ? `${interview.overall_score.toFixed(1)}/5` : "—"}</p>
        </div>
        <div className="metric-card">
          <p className="metric-card-label">Verdict</p>
          <p className="metric-card-value">
            {interview.overall_verdict ? VERDICT_LABEL[interview.overall_verdict] : "Not scored yet"}
          </p>
        </div>
      </div>

      {interview.calendar_link && (
        <div className="card p-4 mb-6 flex items-center justify-between">
          <span className="text-sm text-gray-600">This interview was added to Google Calendar.</span>
          <a href={interview.calendar_link} target="_blank" rel="noreferrer" className="text-xs text-brand-600 hover:underline">
            View event →
          </a>
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        {/* Scores */}
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100">
            <p className="section-title">Question-by-question</p>
          </div>
          <div className="divide-y divide-gray-50 max-h-[600px] overflow-y-auto">
            {interview.scores.length === 0 ? (
              <p className="px-5 py-8 text-sm text-gray-400 text-center">
                {interview.status === "completed" ? "Not scored." : "Scoring happens once the interview is complete."}
              </p>
            ) : (
              interview.scores.map((s, i) => (
                <div key={i} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3 mb-1.5">
                    <p className="text-sm font-medium text-gray-800 flex-1">{s.question}</p>
                    <ScoreBar score={s.score} />
                  </div>
                  <p className="text-xs text-gray-500 mb-1">{s.answer}</p>
                  {s.justification && <p className="text-xs text-gray-400 italic">{s.justification}</p>}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Transcript */}
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100">
            <p className="section-title">Transcript</p>
          </div>
          <div className="px-5 py-4 space-y-3 max-h-[600px] overflow-y-auto">
            {interview.transcript.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">The interview hasn't started yet.</p>
            ) : (
              interview.transcript.map((t, i) => (
                <div key={i} className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-xs leading-relaxed whitespace-pre-wrap ${
                      t.role === "user"
                        ? "bg-ink-900 text-white rounded-br-sm"
                        : "bg-gray-50 border border-gray-100 text-gray-700 rounded-bl-sm"
                    }`}
                  >
                    {t.content}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
