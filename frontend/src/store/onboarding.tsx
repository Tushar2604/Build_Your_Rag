// How far this workspace has got, and what the shell may therefore show.
//
// This used to be one localStorage key. That made "have you finished setting
// up" a fact about the browser you happened to be sitting at: a second machine
// replayed the welcome screen at someone who had been live for months, and a
// workspace older than the onboarding feature had no state at all, so it could
// never be shown the parts of the product it hadn't touched.
//
// It is now `GET /onboarding/state` — the stage is computed from the tenant's
// own rows, the per-person preferences come from `onboarding_prefs`. See
// `src/domain/onboarding/entities.py` for why the stage is "furthest reached"
// rather than "first step not done".
//
// localStorage survives as a *cache only*, so a reload paints the right rail
// immediately instead of flashing the beginner's nav at an established user
// while the request is in flight. It is never the source of truth.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  ReactNode,
} from "react";
import {
  getOnboardingState,
  updateOnboarding,
  Milestones,
  NavMode,
  NextStep,
  OnboardingState as ServerState,
  Stage,
} from "../api/onboarding";

export type TourStatus = "idle" | "running" | "done" | "skipped";

interface OnboardingValue {
  /** False only on the very first load of a session with an empty cache. */
  loaded: boolean;
  stage: Stage;
  milestones: Milestones;
  nextStep: NextStep | null;
  navMode: NavMode;
  toursCompleted: string[];
  dismissed: string[];
  celebratedStages: string[];

  /** Which stage unlock hasn't been announced yet, or null. Read by the shell
   * to decide whether to raise the "just unlocked" toast. */
  pendingCelebration: Stage | null;

  isDismissed: (key: string) => boolean;
  dismiss: (key: string) => void;
  setNavMode: (mode: NavMode) => void;
  markCelebrated: (stage: Stage) => void;
  /** Puts the guidance back: clears dismissals and tour history, leaving the
   * nav mode alone. Wired to "Restart the walkthrough" in Settings. */
  resetGuidance: () => Promise<void>;
  /** Re-reads from the server. Called after an action that could move the
   * stage — creating an assistant, publishing one, finishing booking setup. */
  refresh: () => Promise<void>;

  // --- Guided tour ---------------------------------------------------------
  tourStatus: TourStatus;
  tourArea: string | null;
  tourStepIndex: number;
  startTour: (area: string) => void;
  advanceTour: () => void;
  endTour: (status: "done" | "skipped") => void;
  hasCompletedTour: (area: string) => boolean;
}

const CACHE_KEY = "onboardingCache";

const EMPTY_MILESTONES: Milestones = {
  assistant_configured: false,
  knowledge_ready: false,
  assistant_tested: false,
  channel_connected: false,
  assistant_live: false,
  appointments_ready: false,
  integrations_connected: false,
};

function readCache(): ServerState | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as ServerState) : null;
  } catch {
    return null;
  }
}

function writeCache(state: ServerState) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(state));
  } catch {
    // A full or disabled localStorage costs us the paint optimisation and
    // nothing else — the server still has the answer.
  }
}

const OnboardingContext = createContext<OnboardingValue | null>(null);

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const cached = useRef(readCache()).current;
  const [state, setState] = useState<ServerState | null>(cached);
  const [loaded, setLoaded] = useState(cached !== null);
  const [tourStatus, setTourStatus] = useState<TourStatus>("idle");
  const [tourArea, setTourArea] = useState<string | null>(null);
  const [tourStepIndex, setTourStepIndex] = useState(0);

  const apply = useCallback((next: ServerState) => {
    setState(next);
    writeCache(next);
    setLoaded(true);
  }, []);

  const refresh = useCallback(async () => {
    try {
      apply(await getOnboardingState());
    } catch {
      // Offline, or a 403 for a role this endpoint doesn't serve. Whatever is
      // cached stays on screen; the shell must not blank out because a
      // progress indicator failed to load.
      setLoaded(true);
    }
  }, [apply]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Writes go out optimistically and are reconciled with whatever comes back.
  // Dismissing a card has to feel instantaneous, and the server appends rather
  // than replaces, so a lost race can only ever re-show a card — never lose a
  // dismissal.
  const patch = useCallback(
    async (
      body: Parameters<typeof updateOnboarding>[0],
      optimistic?: (prev: ServerState) => ServerState,
    ) => {
      if (optimistic) {
        setState((prev) => {
          if (!prev) return prev;
          const next = optimistic(prev);
          writeCache(next);
          return next;
        });
      }
      try {
        apply(await updateOnboarding(body));
      } catch {
        // Keep the optimistic view. The next refresh corrects it.
      }
    },
    [apply],
  );

  const dismissed = state?.dismissed ?? [];
  const stage = state?.stage ?? "build";

  const value: OnboardingValue = {
    loaded,
    stage,
    milestones: state?.milestones ?? EMPTY_MILESTONES,
    nextStep: state?.next_step ?? null,
    navMode: state?.nav_mode ?? "guided",
    toursCompleted: state?.tours_completed ?? [],
    dismissed,
    celebratedStages: state?.celebrated_stages ?? [],

    // `build` is where everyone starts, so announcing it would fire a
    // "you've unlocked..." toast at someone who has done nothing yet.
    pendingCelebration:
      state && stage !== "build" && !state.celebrated_stages.includes(stage) ? stage : null,

    isDismissed: (key) => dismissed.includes(key),
    dismiss: (key) =>
      void patch({ dismiss: key }, (prev) => ({
        ...prev,
        dismissed: prev.dismissed.includes(key) ? prev.dismissed : [...prev.dismissed, key],
      })),
    setNavMode: (mode) =>
      void patch({ nav_mode: mode }, (prev) => ({ ...prev, nav_mode: mode })),
    markCelebrated: (s) =>
      void patch({ celebrate_stage: s }, (prev) => ({
        ...prev,
        celebrated_stages: prev.celebrated_stages.includes(s)
          ? prev.celebrated_stages
          : [...prev.celebrated_stages, s],
      })),
    resetGuidance: () => patch({ reset: true }),
    refresh,

    tourStatus,
    tourArea,
    tourStepIndex,
    startTour: (area) => {
      setTourArea(area);
      setTourStepIndex(0);
      setTourStatus("running");
    },
    advanceTour: () => setTourStepIndex((i) => i + 1),
    endTour: (status) => {
      setTourStatus(status);
      setTourStepIndex(0);
      // Only a tour played to the end counts as seen. Skipping leaves it
      // offerable, because "not now" is not "never" — that conflation is
      // exactly what made the old one-shot tour unrepeatable.
      if (status === "done" && tourArea) {
        void patch({ complete_tour: tourArea }, (prev) => ({
          ...prev,
          tours_completed: prev.tours_completed.includes(tourArea)
            ? prev.tours_completed
            : [...prev.tours_completed, tourArea],
        }));
      }
      setTourArea(null);
    },
    hasCompletedTour: (area) => (state?.tours_completed ?? []).includes(area),
  };

  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}

export function useOnboarding(): OnboardingValue {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used inside <OnboardingProvider>");
  return ctx;
}
