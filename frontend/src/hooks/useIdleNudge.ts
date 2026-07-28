// Text-chat "are you still there?" follow-up. Purely client-side timer
// bookkeeping — callers own what a nudge actually looks like (appending a
// canned message has a different shape per surface's message type), this
// hook just decides *when* to fire and caps how many times in a row.

import { useEffect, useRef } from "react";

// Typing takes longer than speaking, so this is much more generous than the
// voice check-in delay — confirmed with the user as the preferred value.
const DEFAULT_DELAY_MS = 22000;
const DEFAULT_MAX_NUDGES = 2;

export function useIdleNudge(
  isIdle: boolean,
  onNudge: () => void,
  delayMs = DEFAULT_DELAY_MS,
  maxNudges = DEFAULT_MAX_NUDGES,
) {
  const countRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onNudgeRef = useRef(onNudge);
  onNudgeRef.current = onNudge;

  useEffect(() => {
    function clear() {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }
    function arm() {
      clear();
      if (countRef.current >= maxNudges) return;
      timerRef.current = setTimeout(() => {
        countRef.current += 1;
        onNudgeRef.current();
        arm(); // allow another nudge if still idle, up to maxNudges
      }, delayMs);
    }

    if (isIdle) {
      arm();
    } else {
      // Any new activity (user sent a message, bot started replying) resets
      // the budget for the next idle stretch.
      countRef.current = 0;
      clear();
    }
    return clear;
  }, [isIdle, delayMs, maxNudges]);
}
