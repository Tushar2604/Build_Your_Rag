import { api } from "./client";

// ── Types (mirror the backend hiring-agent schemas) ──

export interface PlanStep {
  id: number;
  key: string;
  name: string;
  tool: string | null;
  description: string;
  depends_on: number[];
  args: Record<string, unknown>;
}

export interface ExecutionPlan {
  goal: string;
  role: string;
  seniority: string;
  steps: PlanStep[];
  summary: string;
}

export interface PendingApproval {
  step_id: number;
  step_key: string;
  step_name: string;
  tool: string | null;
  kind: "sensitive" | "failure" | string;
  reason: string;
}

export interface ExecutedTask {
  step: number;
  tool: string | null;
  status: string; // ok | skipped | simulated | failed | rejected
  observation: string;
}

export interface ExecutionState {
  run_id: string;
  goal: string;
  status: string;
  cursor: number;
  total_steps: number;
  pending_approval: PendingApproval | null;
  executed: ExecutedTask[];
  summary: string;
}

export interface RunSummary {
  run_id: string;
  goal: string;
  status: string;
  cursor: number;
  total_steps: number;
  created_at: string;
  updated_at: string;
}

export interface ToolOutput {
  step: number;
  tool: string | null;
  observation: string;
  data: Record<string, unknown>;
}

export interface CompletedStep {
  step: number;
  from_state: string;
  to_state: string;
  tool: string | null;
  timestamp: string;
}

export interface HiringMemory {
  run_id: string;
  tenant_id: string;
  status: string;
  current_state: string;
  completed_steps: CompletedStep[];
  tool_outputs: ToolOutput[];
  llm_reasoning: Array<Record<string, unknown>>;
  conversation: Array<Record<string, unknown>>;
  candidate_decisions: Array<Record<string, unknown>>;
  execution: {
    goal: string;
    plan: PlanStep[];
    cursor: number;
    pending_approval: PendingApproval | null;
  } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

// Ranking output shape (as stored in a rank_candidates tool output's `data`).
export interface RankedCandidate {
  candidate_id: string;
  rank: number;
  overall_score: number;
  explanation: string;
  matching_skills: string[];
  missing_skills: string[];
}

// ── API ──

export const hiringApi = {
  plan: (goal: string) => api.post<ExecutionPlan>("/hiring-agent/plan", { goal }),
  execute: (goal: string) => api.post<ExecutionState>("/hiring-agent/execute", { goal }),
  approve: (run_id: string) => api.post<ExecutionState>("/hiring-agent/approve", { run_id }),
  reject: (run_id: string) => api.post<ExecutionState>("/hiring-agent/reject", { run_id }),
  listRuns: () => api.get<RunSummary[]>("/hiring-agent/runs"),
  getRun: (run_id: string) => api.get<HiringMemory>(`/hiring-agent/runs/${run_id}`),
};
