import { api } from "./client";

/** Ascending. Index into this array is the ordering the whole shell uses, and
 * it must stay in step with `STAGE_ORDER` in `domain/onboarding/entities.py`. */
export const STAGE_ORDER = ["build", "teach", "test", "launch", "operate"] as const;

export type Stage = (typeof STAGE_ORDER)[number];
export type NavMode = "guided" | "full";

export interface Milestones {
  assistant_configured: boolean;
  knowledge_ready: boolean;
  assistant_tested: boolean;
  channel_connected: boolean;
  assistant_live: boolean;
  appointments_ready: boolean;
  integrations_connected: boolean;
}

export interface NextStep {
  key: string;
  title: string;
  body: string;
  href: string;
  cta: string;
  /** Which per-area tour "Show me" replays, if this step has one. */
  tour: string | null;
}

export interface OnboardingState {
  stage: Stage;
  milestones: Milestones;
  next_step: NextStep | null;
  nav_mode: NavMode;
  tours_completed: string[];
  dismissed: string[];
  celebrated_stages: string[];
}

export interface OnboardingUpdate {
  nav_mode?: NavMode;
  complete_tour?: string;
  dismiss?: string;
  celebrate_stage?: string;
  reset?: boolean;
}

export const getOnboardingState = () => api.get<OnboardingState>("/onboarding/state");

/** Every write returns the full recomputed state, so a caller never has to
 * follow a dismissal with a second request to find out what to render. */
export const updateOnboarding = (patch: OnboardingUpdate) =>
  api.patch<OnboardingState>("/onboarding/state", patch);

export function stageIndex(stage: Stage): number {
  return STAGE_ORDER.indexOf(stage);
}

export function atLeast(stage: Stage, required: Stage): boolean {
  return stageIndex(stage) >= stageIndex(required);
}
