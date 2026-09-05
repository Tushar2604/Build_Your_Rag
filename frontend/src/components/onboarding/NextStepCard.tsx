// The one thing to do next, pinned in the rail.
//
// This is what replaced the one-shot tour. The tour ran once, set a flag, and
// could never come back — so a workspace that stalled halfway had nothing left
// telling it what to do, and an established workspace that later wanted to set
// up booking got no help at all. This card is recomputed from server state on
// every load, so it is always present and always current until there is
// genuinely nothing left to configure, at which point it disappears.
//
// One action, never a list. The dashboard's checklist can show the whole
// ladder; the rail shows the next rung.
import { Link } from "react-router-dom";
import { ArrowRight, Sparkles, X } from "lucide-react";
import { useOnboarding } from "../../store/onboarding";

export default function NextStepCard({ collapsed }: { collapsed: boolean }) {
  const { nextStep, stage, isDismissed, dismiss, startTour, loaded } = useOnboarding();

  // Nothing to show: still loading, fully set up, or closed by this user.
  if (!loaded || !nextStep || isDismissed(`next-step:${nextStep.key}`)) return null;

  // Collapsed rail is icons only. A pulsing dot on the logo would be noise, so
  // the card becomes a single tappable icon that reads as "there's something
  // here" and expands the rail on hover like everything else.
  if (collapsed) {
    return (
      <Link
        to={nextStep.href}
        title={nextStep.title}
        aria-label={nextStep.title}
        className="relative mx-auto mb-2 flex h-9 w-9 items-center justify-center rounded-xl
                   bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 text-white
                   shadow-[0_6px_18px_-6px_rgba(139,92,246,0.8)]"
      >
        <Sparkles className="h-[18px] w-[18px]" strokeWidth={1.75} />
      </Link>
    );
  }

  return (
    <div
      className="relative mb-2 rounded-2xl border border-brand-400/25 bg-brand-500/10 p-3"
      data-tour="next-step"
    >
      <button
        type="button"
        onClick={() => dismiss(`next-step:${nextStep.key}`)}
        aria-label="Hide this suggestion"
        title="Hide this suggestion"
        className="absolute right-2 top-2 text-gray-400 transition-colors hover:text-gray-600"
      >
        <X className="h-3.5 w-3.5" strokeWidth={2} />
      </button>

      <p className="pr-5 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-brand-500">
        Next step
      </p>
      <p className="chrome-brand mt-1 text-[13px] font-semibold leading-snug">
        {nextStep.title}
      </p>
      <p className="mt-1 text-[11.5px] leading-relaxed text-gray-500">{nextStep.body}</p>

      <div className="mt-3 flex items-center gap-2">
        <Link
          to={nextStep.href}
          className="inline-flex items-center gap-1 rounded-full bg-brand-500 px-2.5 py-1
                     text-[11.5px] font-semibold text-white transition-colors hover:bg-brand-600"
        >
          {nextStep.cta}
          <ArrowRight className="h-3 w-3" strokeWidth={2.5} />
        </Link>
        {nextStep.tour && (
          // Deliberately replayable: skipping a tour is "not now", not
          // "never", and this is the button that makes that true.
          <button
            type="button"
            onClick={() => startTour(nextStep.tour!)}
            className="text-[11.5px] font-semibold text-gray-500 transition-colors hover:text-gray-800"
          >
            Show me
          </button>
        )}
      </div>

      {stage !== "operate" && (
        <p className="mt-2.5 text-[10.5px] text-gray-400">
          More of the product unlocks as you go.
        </p>
      )}
    </div>
  );
}
