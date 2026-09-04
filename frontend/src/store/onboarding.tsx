// Onboarding UI state — welcome screen, guided tour, and whether the setup
// checklist has been dismissed. Same shape as store/theme.tsx: one localStorage
// key, no backend. Deliberately per-browser (like theme/sidebarMode) rather
// than tenant-persisted — a user on a second device sees the welcome screen
// again, which is an accepted trade-off for shipping without a migration.
import { createContext, useContext, useState, ReactNode } from "react";

export type TourStatus = "idle" | "running" | "done" | "skipped";

interface OnboardingData {
  welcomeSeen: boolean;
  tourStatus: TourStatus;
  tourStepIndex: number;
  testedAssistant: boolean;
  checklistDismissed: boolean;
}

interface OnboardingState extends OnboardingData {
  markWelcomeSeen: () => void;
  startTour: () => void;
  advanceTour: () => void;
  endTour: (status: "done" | "skipped") => void;
  markAssistantTested: () => void;
  dismissChecklist: () => void;
}

const STORAGE_KEY = "onboardingState";

const DEFAULTS: OnboardingData = {
  welcomeSeen: false,
  tourStatus: "idle",
  tourStepIndex: 0,
  testedAssistant: false,
  checklistDismissed: false,
};

function load(): OnboardingData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

function save(data: OnboardingData) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

const OnboardingContext = createContext<OnboardingState | null>(null);

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<OnboardingData>(load);

  function update(patch: Partial<OnboardingData>) {
    setData((prev) => {
      // No-op guard: a flag that's already set (e.g. markAssistantTested
      // firing again from a remounted panel) must not produce a new object
      // reference, or every consumer re-renders and any effect keyed on the
      // returned callback re-fires forever.
      const changed = (Object.keys(patch) as (keyof OnboardingData)[]).some(
        (k) => prev[k] !== patch[k],
      );
      if (!changed) return prev;
      const next = { ...prev, ...patch };
      save(next);
      return next;
    });
  }

  const value: OnboardingState = {
    ...data,
    markWelcomeSeen: () => update({ welcomeSeen: true }),
    startTour: () => update({ tourStatus: "running", tourStepIndex: 0 }),
    advanceTour: () =>
      setData((prev) => {
        const next = { ...prev, tourStepIndex: prev.tourStepIndex + 1 };
        save(next);
        return next;
      }),
    endTour: (status) => update({ tourStatus: status, tourStepIndex: 0 }),
    markAssistantTested: () => update({ testedAssistant: true }),
    dismissChecklist: () => update({ checklistDismissed: true }),
  };

  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}

export function useOnboarding(): OnboardingState {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used inside <OnboardingProvider>");
  return ctx;
}
