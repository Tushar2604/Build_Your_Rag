// What each stage is called, and what crossing into it just gave you.
//
// The nav itself carries `unlockedAt` per item (see Layout.tsx) — this is the
// human-readable half: the label on the collapsed "More" row, and the wording
// of the toast that fires the first time a workspace crosses a boundary.
import { Stage } from "../api/onboarding";

interface StageCopy {
  /** Shown on the progress pip in the rail. */
  label: string;
  /** The toast headline when this stage is first reached. `build` has none —
   * nobody should be congratulated for signing up. */
  unlockedTitle?: string;
  unlockedBody?: string;
}

export const STAGE_COPY: Record<Stage, StageCopy> = {
  build: {
    label: "Getting started",
  },
  teach: {
    label: "Teaching it",
    unlockedTitle: "Your assistant exists 🎉",
    unlockedBody:
      "Next: give it something to answer from. Files and Integrations are now in your sidebar.",
  },
  test: {
    label: "Testing",
    unlockedTitle: "It has knowledge now",
    unlockedBody: "Open your assistant and hit Test — talk to it before a real caller does.",
  },
  launch: {
    label: "Going live",
    unlockedTitle: "Ready to go live",
    unlockedBody:
      "Phone Numbers and WhatsApp Numbers just appeared in your sidebar — pick where it should answer.",
  },
  operate: {
    label: "Running",
    unlockedTitle: "You're live — everything's unlocked",
    unlockedBody:
      "Appointments, Call Logs, Analytics and Campaigns are all in your sidebar now.",
  },
};

/** The word on the disclosure row that holds everything not yet unlocked. */
export function lockedRowLabel(count: number): string {
  return count === 1 ? "1 more feature" : `${count} more features`;
}
