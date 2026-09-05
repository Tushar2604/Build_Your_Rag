// "Appointments just unlocked."
//
// The moment that makes staged navigation feel like a reward rather than a
// restriction. Without it, a menu quietly grows a row and nobody notices; with
// it, finishing a step visibly hands you something.
//
// Fires once per person per stage — `celebrated_stages` is server-side, so it
// does not fire again on another device, and it cannot fire for a stage the
// workspace reached before this feature existed... except the first one after
// upgrade, which is deliberate: an established workspace gets exactly one
// "everything is unlocked" note and then never sees this again.
import { useEffect, useState } from "react";
import { PartyPopper, X } from "lucide-react";
import { useOnboarding } from "../../store/onboarding";
import { STAGE_COPY } from "../../onboarding/stages";

const AUTO_DISMISS_MS = 9000;

export default function UnlockToast() {
  const { pendingCelebration, markCelebrated } = useOnboarding();
  const [closing, setClosing] = useState(false);

  const copy = pendingCelebration ? STAGE_COPY[pendingCelebration] : null;
  const show = !!pendingCelebration && !!copy?.unlockedTitle;

  useEffect(() => {
    if (!show) return;
    const t = window.setTimeout(() => {
      setClosing(true);
      // Marking it celebrated is what stops it coming back, so it happens on
      // auto-dismiss too — a toast someone ignored has still been seen.
      window.setTimeout(() => {
        markCelebrated(pendingCelebration!);
        setClosing(false);
      }, 200);
    }, AUTO_DISMISS_MS);
    return () => window.clearTimeout(t);
  }, [show, pendingCelebration, markCelebrated]);

  if (!show) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`card fixed bottom-5 right-5 z-[60] w-[330px] border-brand-400/30 p-4
                  shadow-[0_18px_50px_-12px_rgba(0,0,0,0.45)]
                  ${closing ? "opacity-0" : "animate-scale-in"} transition-opacity duration-200`}
    >
      <button
        type="button"
        onClick={() => markCelebrated(pendingCelebration!)}
        aria-label="Dismiss"
        className="absolute right-2.5 top-2.5 text-gray-400 transition-colors hover:text-gray-600"
      >
        <X className="h-3.5 w-3.5" strokeWidth={2} />
      </button>

      <div className="flex items-start gap-3">
        <span
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl
                     bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 text-white"
        >
          <PartyPopper className="h-[18px] w-[18px]" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 pr-4">
          <p className="text-[13.5px] font-semibold text-gray-900">{copy!.unlockedTitle}</p>
          <p className="mt-1 text-[12px] leading-relaxed text-gray-500">{copy!.unlockedBody}</p>
        </div>
      </div>
    </div>
  );
}
