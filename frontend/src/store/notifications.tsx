// The "something happened while you were elsewhere" counter behind the
// sidebar badges.
//
// Deliberately per-browser rather than per-workspace: "new to me" is a fact
// about who is looking. A server-side seen marker would mean whichever
// colleague opened Appointments first cleared the badge for the whole team,
// which is the behaviour that teaches people to ignore badges.
//
// The watermark is therefore a timestamp in localStorage, sent to the API as
// `since`. The server counts and the client decides what "seen" means, so
// neither has to model the other's idea of a session.
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";

import { appointmentsApi } from "../api/appointments";

const SEEN_KEY = "appointmentsSeenAt";

// Slow on purpose. This runs on every screen in the app, forever, and a
// booking that shows up within the minute is the same news as one that shows
// up instantly. Polling harder would keep a sleeping free-tier instance awake
// for a number nobody is watching.
const POLL_MS = 60_000;

interface Notifications {
  /** Bookings taken since this browser last opened the Appointments page. */
  newAppointments: number;
  /** Called when the user actually looks at them. */
  markAppointmentsSeen: () => void;
  /** After booking one yourself, so the badge reflects it without waiting. */
  refresh: () => void;
}

const Ctx = createContext<Notifications>({
  newAppointments: 0,
  markAppointmentsSeen: () => undefined,
  refresh: () => undefined,
});

function readSeenAt(): string | undefined {
  try {
    return localStorage.getItem(SEEN_KEY) || undefined;
  } catch {
    // Private mode, or site data blocked. An unreadable watermark is not worth
    // failing the whole shell over — the server falls back to "the last day".
    return undefined;
  }
}

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const [newAppointments, setNewAppointments] = useState(0);
  // The newest booking the last poll saw. Advancing the watermark to *this*
  // rather than to `Date.now()` is what stops a booking that lands between the
  // poll and the click from being marked as seen without ever being shown.
  const latestRef = useRef<string | null>(null);

  const refresh = useCallback(() => {
    appointmentsApi
      .newSince(readSeenAt())
      .then((r) => {
        setNewAppointments(r.count);
        latestRef.current = r.latest_at;
      })
      // A failed count is not worth an error state: the badge simply does not
      // appear, and every page it sits beside still works.
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, POLL_MS);
    // A tab coming back to the foreground is the moment someone is most likely
    // to care, and the moment the interval is least likely to have just fired.
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const markAppointmentsSeen = useCallback(() => {
    try {
      localStorage.setItem(SEEN_KEY, latestRef.current || new Date().toISOString());
    } catch {
      // Storage is unavailable, so the badge will come back on the next poll.
      // Clearing it locally is still the right immediate response to a click.
    }
    setNewAppointments(0);
  }, []);

  const value = useMemo(
    () => ({ newAppointments, markAppointmentsSeen, refresh }),
    [newAppointments, markAppointmentsSeen, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNotifications(): Notifications {
  return useContext(Ctx);
}
