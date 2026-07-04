import { useCallback, useEffect, useMemo, useState } from "react";
import {
  hiringApi,
  type ExecutionPlan,
  type ExecutionState,
  type HiringMemory,
  type RankedCandidate,
  type RunSummary,
  type ToolOutput,
} from "../api/hiring";
import { ApiError } from "../api/client";

// ── Small presentational helpers ──

function runStatusClass(status?: string | null): string {
  switch (status) {
    case "completed": return "badge-live";
    case "waiting_approval": return "badge-paused";
    case "failed": return "badge-error";
    case "rejected": return "badge-draft";
    case "running": return "badge-neutral";
    default: return "badge-neutral";
  }
}

function taskStatusClass(status: string): string {
  switch (status) {
    case "ok": return "badge-live";
    case "simulated": return "badge bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200";
    case "skipped": return "badge-neutral";
    case "failed": return "badge-error";
    case "rejected": return "badge-draft";
    default: return "badge-neutral";
  }
}

// Derive a task status from a tool output (mirrors the backend's `_status_of`).
function deriveTaskStatus(o: ToolOutput): string {
  const d = o.data ?? {};
  if (d["simulated"]) return "simulated";
  if (d["skipped"]) return "skipped";
  const obs = o.observation ?? "";
  if (obs.startsWith("[") && obs.slice(0, 20).toLowerCase().includes("error")) return "failed";
  return "ok";
}

function humanStatus(status?: string | null): string {
  if (!status) return "—";
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}

// ── Page ──

export default function HiringAgentPage() {
  const [goal, setGoal] = useState("Hire a Backend Intern");
  const [jobText, setJobText] = useState("");
  const [jobFileName, setJobFileName] = useState("");

  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [state, setState] = useState<ExecutionState | null>(null);
  const [memory, setMemory] = useState<HiringMemory | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentRunId = state?.run_id ?? memory?.run_id ?? null;

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await hiringApi.listRuns());
    } catch {
      /* history is non-critical; ignore */
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  const loadMemory = useCallback(async (runId: string) => {
    try {
      setMemory(await hiringApi.getRun(runId));
    } catch {
      /* detail is best-effort */
    }
  }, []);

  async function run<T>(fn: () => Promise<T>, after?: (r: T) => void) {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      after?.(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const previewPlan = () =>
    run(() => hiringApi.plan(goal), (p) => setPlan(p));

  const startExecution = () =>
    run(
      () => hiringApi.execute(goal),
      async (s) => {
        setState(s);
        setPlan(null);
        await loadMemory(s.run_id);
        await refreshRuns();
      },
    );

  const approve = () => {
    if (!currentRunId) return;
    return run(
      () => hiringApi.approve(currentRunId),
      async (s) => {
        setState(s);
        await loadMemory(s.run_id);
        await refreshRuns();
      },
    );
  };

  const reject = () => {
    if (!currentRunId) return;
    return run(
      () => hiringApi.reject(currentRunId),
      async (s) => {
        setState(s);
        await loadMemory(s.run_id);
        await refreshRuns();
      },
    );
  };

  const openRun = (runId: string) =>
    run(
      () => hiringApi.getRun(runId),
      (m) => {
        setMemory(m);
        setState(null);
        setPlan(null);
      },
    );

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setJobFileName(file.name);
    const isText =
      file.type.startsWith("text/") ||
      /\.(txt|md|markdown)$/i.test(file.name);
    if (isText) {
      const reader = new FileReader();
      reader.onload = () => setJobText(String(reader.result ?? ""));
      reader.readAsText(file);
    }
  }

  // ── Derived view state (works for both a live run and a loaded-from-history run) ──

  const status = state?.status ?? memory?.status ?? null;
  const pending = state?.pending_approval ?? memory?.execution?.pending_approval ?? null;
  const cursor = state?.cursor ?? memory?.execution?.cursor ?? 0;
  const totalSteps = state?.total_steps ?? memory?.execution?.plan.length ?? 0;
  const activeGoal = state?.goal ?? memory?.execution?.goal ?? "";
  const progressPct = totalSteps ? Math.min(100, Math.round((cursor / totalSteps) * 100)) : 0;
  const isWaiting = status === "waiting_approval" && !!pending;

  const timeline = useMemo(() => {
    if (memory?.completed_steps.length) {
      return memory.completed_steps.map((c) => ({
        step: c.step,
        label: c.from_state,
        tool: c.tool,
        time: c.timestamp,
      }));
    }
    return (state?.executed ?? []).map((e) => ({
      step: e.step,
      label: e.tool ?? `step ${e.step}`,
      tool: e.tool,
      time: undefined as string | undefined,
    }));
  }, [memory, state]);

  const toolLogs = memory?.tool_outputs ?? [];
  const ranked = useMemo<RankedCandidate[]>(() => {
    const out = memory?.tool_outputs.find((o) => o.tool === "rank_candidates");
    const list = out?.data?.["ranked"] as RankedCandidate[] | undefined;
    return Array.isArray(list) ? list : [];
  }, [memory]);

  return (
    <div className="page">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="page-title">Hiring Agent</h1>
          <p className="page-subtitle">
            Plan and run an autonomous hiring workflow — with human approval on sensitive steps.
          </p>
        </div>
        {status && <span className={runStatusClass(status)}>{humanStatus(status)}</span>}
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Main column ── */}
        <div className="lg:col-span-2 space-y-6">
          {/* Job upload / start */}
          <section className="card p-5">
            <h2 className="section-title mb-4">Job &amp; Goal</h2>
            <label className="label" htmlFor="goal">Hiring goal</label>
            <input
              id="goal"
              className="input"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="e.g. Hire a Backend Intern"
            />
            <label className="label mt-4" htmlFor="jd">Job description (optional)</label>
            <textarea
              id="jd"
              className="input"
              rows={4}
              value={jobText}
              onChange={(e) => setJobText(e.target.value)}
              placeholder="Paste the JD, or upload a file below…"
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label className="btn-secondary btn-sm cursor-pointer">
                <input type="file" accept=".txt,.md,.markdown,.pdf" className="hidden" onChange={onFile} />
                Upload file
              </label>
              {jobFileName && <span className="text-xs text-gray-500 truncate">{jobFileName}</span>}
              <div className="flex-1" />
              <button className="btn-secondary btn-sm" disabled={busy || !goal.trim()} onClick={previewPlan}>
                Preview plan
              </button>
              <button className="btn-accent btn-sm" disabled={busy || !goal.trim()} onClick={startExecution}>
                {busy ? "Working…" : "Start execution"}
              </button>
            </div>
            <p className="hint">The goal drives the generated plan; sensitive steps pause for approval.</p>
          </section>

          {/* Plan preview */}
          {plan && (
            <section className="card p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="section-title">Planned steps</h2>
                <span className="badge-neutral">{plan.steps.length} steps</span>
              </div>
              <p className="text-xs text-gray-500 mb-3 break-words">{plan.summary}</p>
              <ol className="space-y-2">
                {plan.steps.map((s) => (
                  <li key={s.id} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 text-[11px] font-semibold text-gray-600">
                      {s.id + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-900">{s.name}</div>
                      <div className="text-xs text-gray-500">{s.description}</div>
                    </div>
                    {s.tool && <span className="code-inline ml-auto flex-shrink-0">{s.tool}</span>}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {/* Current state + approval */}
          {status && (
            <section className="card p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="section-title">Current state</h2>
                <span className={runStatusClass(status)}>{humanStatus(status)}</span>
              </div>
              {activeGoal && <p className="text-sm text-gray-600 mb-3">{activeGoal}</p>}
              <div className="flex items-center gap-3 mb-1">
                <div className="h-2 flex-1 rounded-full bg-gray-100 overflow-hidden">
                  <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${progressPct}%` }} />
                </div>
                <span className="text-xs text-gray-500 tabular-nums">{cursor}/{totalSteps}</span>
              </div>

              {isWaiting && pending && (
                <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <div className="flex items-center gap-2">
                    <span className="badge-paused">Approval required</span>
                    <span className="text-sm font-medium text-amber-900">{pending.step_name}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-amber-800">{pending.reason}</p>
                  <div className="mt-3 flex gap-2">
                    <button className="btn-accent btn-sm" disabled={busy} onClick={approve}>Approve</button>
                    <button className="btn-secondary btn-sm" disabled={busy} onClick={reject}>Reject</button>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Execution timeline */}
          {timeline.length > 0 && (
            <section className="card p-5">
              <h2 className="section-title mb-4">Execution timeline</h2>
              <ol className="relative border-l border-gray-200 ml-2 space-y-4">
                {timeline.map((t, i) => (
                  <li key={i} className="ml-4">
                    <span className="absolute -left-[5px] mt-1 h-2.5 w-2.5 rounded-full bg-brand-500" />
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-gray-900">{t.label}</span>
                      {t.tool && <span className="code-inline">{t.tool}</span>}
                      {t.time && <span className="text-xs text-gray-400">{fmtTime(t.time)}</span>}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {/* Candidate rankings */}
          {ranked.length > 0 && (
            <section className="card p-5 overflow-x-auto">
              <h2 className="section-title mb-4">Candidate rankings</h2>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>#</th><th>Candidate</th><th>Score</th><th>Matching</th><th>Missing</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((c) => (
                    <tr key={c.candidate_id}>
                      <td className="tabular-nums">{c.rank}</td>
                      <td className="font-medium text-gray-900">{c.candidate_id}</td>
                      <td className="tabular-nums">{c.overall_score}</td>
                      <td className="text-emerald-700">{(c.matching_skills ?? []).join(", ") || "—"}</td>
                      <td className="text-red-600">{(c.missing_skills ?? []).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* Tool logs */}
          {toolLogs.length > 0 && (
            <section className="card p-5">
              <h2 className="section-title mb-4">Tool logs</h2>
              <ul className="space-y-2">
                {toolLogs.map((o, i) => (
                  <li key={i} className="rounded-lg border border-gray-100 bg-gray-50/60 px-3 py-2">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold text-gray-500">#{o.step}</span>
                      <span className="code-inline">{o.tool ?? "—"}</span>
                      <span className={`${taskStatusClass(deriveTaskStatus(o))} ml-auto`}>{deriveTaskStatus(o)}</span>
                    </div>
                    <p className="text-[13px] text-gray-700 break-words">{o.observation}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Agent memory */}
          {memory && (
            <section className="card p-5">
              <h2 className="section-title mb-4">Agent memory</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <MemoryStat label="Steps" value={memory.completed_steps.length} />
                <MemoryStat label="Tool outputs" value={memory.tool_outputs.length} />
                <MemoryStat label="Reasoning" value={memory.llm_reasoning.length} />
                <MemoryStat label="Decisions" value={memory.candidate_decisions.length} />
              </div>
              {memory.llm_reasoning.length > 0 && (
                <MemoryBlock title="LLM reasoning" items={memory.llm_reasoning.map((r) => String(r["reasoning"] ?? JSON.stringify(r)))} />
              )}
              {memory.candidate_decisions.length > 0 && (
                <MemoryBlock title="Candidate decisions" items={memory.candidate_decisions.map((d) => JSON.stringify(d))} />
              )}
              {memory.conversation.length > 0 && (
                <MemoryBlock title="Conversation" items={memory.conversation.map((m) => String(m["content"] ?? JSON.stringify(m)))} />
              )}
            </section>
          )}
        </div>

        {/* ── Sidebar: execution history ── */}
        <aside className="lg:col-span-1">
          <section className="card p-5 lg:sticky lg:top-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="section-title">Execution history</h2>
              <button className="icon-btn w-7 h-7" aria-label="Refresh" onClick={() => void refreshRuns()}>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            {runs.length === 0 ? (
              <p className="text-sm text-gray-400">No runs yet. Start one to see it here.</p>
            ) : (
              <ul className="space-y-1.5">
                {runs.map((r) => (
                  <li key={r.run_id}>
                    <button
                      onClick={() => openRun(r.run_id)}
                      className={`w-full text-left rounded-lg border px-3 py-2.5 transition-colors ${
                        r.run_id === currentRunId
                          ? "border-brand-300 bg-brand-50/50"
                          : "border-gray-200/70 hover:bg-gray-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-medium text-gray-900 truncate">{r.goal || "Untitled run"}</span>
                        <span className={runStatusClass(r.status)}>{humanStatus(r.status)}</span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-400">
                        <span className="tabular-nums">{r.cursor}/{r.total_steps} steps</span>
                        <span>·</span>
                        <span>{fmtTime(r.updated_at)}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

function MemoryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50/60 px-3 py-2.5">
      <div className="text-[22px] font-semibold text-gray-900 tabular-nums leading-none">{value}</div>
      <div className="mt-1 text-[11px] font-medium uppercase tracking-wider text-gray-400">{label}</div>
    </div>
  );
}

function MemoryBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-4">
      <p className="eyebrow mb-2">{title}</p>
      <ul className="space-y-1.5">
        {items.map((t, i) => (
          <li key={i} className="text-[13px] text-gray-700 rounded-md bg-gray-50/70 px-3 py-2 break-words">
            {t}
          </li>
        ))}
      </ul>
    </div>
  );
}
