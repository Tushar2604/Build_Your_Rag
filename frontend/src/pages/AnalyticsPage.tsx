import { useState, useEffect } from "react";
import { listChatbots, Chatbot } from "../api/chatbots";
import {
  getChatbotAnalytics,
  getChatbotRequests,
  ChatbotAnalytics,
  AnalyticsDay,
  RequestLog,
} from "../api/analytics";
import { ApiError } from "../api/client";

const RANGES = [7, 30, 90];

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

function score(x: number | null): string {
  return x === null ? "—" : x.toFixed(3);
}

/** Inline bar chart (no chart lib). values are 0..1; color keyed per bar. */
function MiniBars({
  days,
  value,
  color,
  title,
}: {
  days: AnalyticsDay[];
  value: (d: AnalyticsDay) => number | null;
  color: (v: number) => string;
  title: string;
}) {
  if (days.length === 0) {
    return <p className="text-xs text-gray-400">No data in range.</p>;
  }
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 mb-2">{title}</p>
      <div className="flex items-end gap-0.5 h-24" role="img" aria-label={title}>
        {days.map((d) => {
          const v = value(d);
          const h = v === null ? 0 : Math.max(2, Math.round(v * 100));
          return (
            <div
              key={d.day}
              className="flex-1 rounded-t-sm transition-all"
              style={{ height: `${h}%`, backgroundColor: v === null ? "#e5e7eb" : color(v) }}
              title={`${d.day}: ${v === null ? "no data" : v.toFixed(3)} (${d.answers} answers)`}
            />
          );
        })}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "good" | "warn";
}) {
  const toneClass =
    tone === "good" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : "text-gray-900";
  return (
    <div className="metric-card">
      <p className="metric-card-label">{label}</p>
      <p className={`metric-card-value ${toneClass}`}>{value}</p>
      {hint && <p className="metric-card-hint">{hint}</p>}
    </div>
  );
}

export default function AnalyticsPage() {
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [days, setDays] = useState(30);
  const [data, setData] = useState<ChatbotAnalytics | null>(null);
  const [requests, setRequests] = useState<RequestLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listChatbots()
      .then((bots) => {
        setChatbots(bots);
        if (bots.length > 0) setSelected(bots[0].id);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load chatbots."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    setError(null);
    getChatbotAnalytics(selected, days)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load analytics."));
  }, [selected, days]);

  useEffect(() => {
    if (!selected) return;
    setRequests([]);
    getChatbotRequests(selected, 50)
      .then(setRequests)
      .catch(() => setRequests([]));
  }, [selected]);

  // Window-level aggregates from the daily rows.
  const totalAnswers = data?.daily.reduce((a, d) => a + d.answers, 0) ?? 0;
  // Average top score, weighted by answers — but only over days that actually
  // retrieved something (avg_top_score !== null), so empty days don't drag it down.
  const scoredAnswers =
    data?.daily.reduce((a, d) => a + (d.avg_top_score === null ? 0 : d.answers), 0) ?? 0;
  const weightedScore =
    data && scoredAnswers > 0
      ? data.daily.reduce((a, d) => a + (d.avg_top_score ?? 0) * d.answers, 0) / scoredAnswers
      : null;
  const noContext =
    data && totalAnswers > 0
      ? data.daily.reduce((a, d) => a + d.no_context_rate * d.answers, 0) / totalAnswers
      : 0;
  const refusal =
    data && totalAnswers > 0
      ? data.daily.reduce((a, d) => a + d.refusal_rate * d.answers, 0) / totalAnswers
      : 0;

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 sm:px-6 animate-fade-in">
      <div className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h1 className="page-title">Analytics</h1>
          <p className="page-subtitle">
            Answer quality per chatbot over time — spot a bad day, then see if it's retrieval or generation
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Chatbot"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="input py-1.5 w-auto"
          >
            {chatbots.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <div className="segmented">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                className={days === r ? "segmented-item-active" : "segmented-item"}
              >
                {r} days
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-16 text-sm text-gray-400">Loading…</div>
      ) : chatbots.length === 0 ? (
        <div className="text-center py-16 text-sm text-gray-500">
          No chatbots yet — create one and ask it some questions to see analytics.
        </div>
      ) : error ? (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : !data ? (
        <div className="text-center py-16 text-sm text-gray-400">Loading analytics…</div>
      ) : (
        <div className="space-y-6">
          {totalAnswers === 0 ? (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
              No successful answers in the last {days} days.{" "}
              {requests.length > 0
                ? "Failing/empty requests are listed below — check their status and error."
                : "Ask this chatbot a question to populate analytics."}
            </div>
          ) : (
          <>
          {/* Summary */}
          <div className="grid gap-4 grid-cols-2 sm:grid-cols-4">
            <StatCard label="Answers" value={String(totalAnswers)} hint={`last ${days} days`} />
            <StatCard
              label="Avg top score"
              value={score(weightedScore)}
              hint="retrieval strength"
              tone={weightedScore !== null && weightedScore >= 0.7 ? "good" : "warn"}
            />
            <StatCard
              label="No-context rate"
              value={pct(noContext)}
              hint="retrieval misses"
              tone={noContext > 0.2 ? "warn" : "neutral"}
            />
            <StatCard
              label="Refusal rate"
              value={pct(refusal)}
              hint="answered 'not in docs'"
              tone={refusal > 0.3 ? "warn" : "neutral"}
            />
          </div>

          {/* Trends */}
          <div className="card p-5 grid gap-6 sm:grid-cols-2">
            <MiniBars
              days={data.daily}
              title="Avg top citation score per day (higher = better retrieval)"
              value={(d) => d.avg_top_score}
              color={(v) => (v >= 0.7 ? "#16a34a" : v >= 0.55 ? "#d97706" : "#dc2626")}
            />
            <MiniBars
              days={data.daily}
              title="No-context rate per day (higher = more retrieval misses)"
              value={(d) => d.no_context_rate}
              color={(v) => (v > 0.2 ? "#dc2626" : v > 0.1 ? "#d97706" : "#9ca3af")}
            />
          </div>

          {/* Provider mix */}
          <div className="card p-5">
            <p className="text-sm font-medium text-gray-700 mb-3">
              Provider mix
              <span className="font-normal text-gray-400"> — a spike in the fallback often explains a bad day</span>
            </p>
            <div className="flex flex-wrap gap-3">
              {data.providers.map((p) => (
                <div key={p.provider ?? "unknown"} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2">
                  <span className="badge bg-gray-100 text-gray-700">{p.provider ?? "unknown"}</span>
                  <span className="text-sm text-gray-600">{p.answers} answers</span>
                  <span className="text-xs text-gray-400">top score {score(p.avg_top_score)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Daily table */}
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left font-medium px-4 py-2.5">Day</th>
                  <th className="text-right font-medium px-4 py-2.5">Answers</th>
                  <th className="text-right font-medium px-4 py-2.5">Top score</th>
                  <th className="text-right font-medium px-4 py-2.5">Citations</th>
                  <th className="text-right font-medium px-4 py-2.5">No-context</th>
                  <th className="text-right font-medium px-4 py-2.5">Refusal</th>
                  <th className="text-right font-medium px-4 py-2.5">Avg tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {[...data.daily].reverse().map((d) => (
                  <tr key={d.day} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5 text-gray-700">{d.day}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{d.answers}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{score(d.avg_top_score)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{d.avg_citations.toFixed(1)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{pct(d.no_context_rate)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{pct(d.refusal_rate)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-700">{Math.round(d.avg_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
          )}

          {/* Recent requests — one row per ask, success OR failure */}
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <p className="text-sm font-medium text-gray-700">Recent requests</p>
              <span className="text-xs text-gray-400">{requests.length} logged</span>
            </div>
            {requests.length === 0 ? (
              <p className="px-4 py-6 text-sm text-gray-400 text-center">No requests logged yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                    <tr>
                      <th className="text-left font-medium px-3 py-2.5">When</th>
                      <th className="text-left font-medium px-3 py-2.5">Status</th>
                      <th className="text-left font-medium px-3 py-2.5">Question</th>
                      <th className="text-right font-medium px-3 py-2.5">Top score</th>
                      <th className="text-left font-medium px-3 py-2.5">Verdict</th>
                      <th className="text-left font-medium px-3 py-2.5">Provider</th>
                      <th className="text-right font-medium px-3 py-2.5">Latency</th>
                      <th className="text-right font-medium px-3 py-2.5">Tokens</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {requests.map((r) => (
                      <tr key={r.id} className="hover:bg-gray-50">
                        <td className="px-3 py-2.5 text-gray-500 whitespace-nowrap">
                          {new Date(r.created_at).toLocaleString()}
                        </td>
                        <td className="px-3 py-2.5">
                          <span className={r.status === "ok" ? "badge-live" : "badge-error"}>
                            {r.status}
                          </span>
                        </td>
                        <td
                          className="px-3 py-2.5 text-gray-700 max-w-xs truncate"
                          title={r.error ?? r.answer ?? r.query}
                        >
                          {r.query}
                        </td>
                        <td className="px-3 py-2.5 text-right text-gray-700">{score(r.max_score)}</td>
                        <td className="px-3 py-2.5">
                          {r.status === "error" ? (
                            <span className="badge-error">error</span>
                          ) : r.no_context ? (
                            <span className="badge-paused">no context</span>
                          ) : r.refused ? (
                            <span className="badge-paused">refused</span>
                          ) : (
                            <span className="badge-live">answered</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-gray-600">{r.provider ?? "—"}</td>
                        <td className="px-3 py-2.5 text-right text-gray-600 whitespace-nowrap">{r.latency_ms} ms</td>
                        <td className="px-3 py-2.5 text-right text-gray-600">{r.tokens_used}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* How to read it */}
          <div className="rounded-lg bg-blue-50 border border-blue-100 px-4 py-3 text-sm text-blue-900">
            <p className="font-medium mb-1">Reading a bad day</p>
            <p className="text-blue-800/90">
              Top score down or no-context/refusal up &rarr; <strong>retrieval</strong> problem (a deleted
              doc, too-strict score floor, or new questions the corpus doesn't cover). Scores healthy but
              answers still poor &rarr; <strong>generation</strong> problem — check the provider mix for a
              silent failover, or a prompt/model change.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
