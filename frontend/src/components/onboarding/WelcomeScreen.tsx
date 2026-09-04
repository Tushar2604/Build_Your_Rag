// First-run welcome panel. Shown at the top of DashboardPage in place of the
// hero when a tenant has zero assistants and hasn't dismissed it yet — see
// the gating logic in DashboardPage.tsx (real zero-assistants state, not just
// the localStorage flag, so an established tenant never sees this again).
import { Link } from "react-router-dom";
import { Compass, PlayCircle, Sparkles } from "lucide-react";
import { useOnboarding } from "../../store/onboarding";

export default function WelcomeScreen({
  doneCount,
  totalCount,
}: {
  doneCount: number;
  totalCount: number;
}) {
  const { markWelcomeSeen, startTour } = useOnboarding();

  return (
    <div className="card relative overflow-hidden p-8 sm:p-10 text-center">
      <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl
                       bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700
                       shadow-[0_10px_28px_-8px_rgba(139,92,246,0.7)]">
        <Sparkles className="h-7 w-7 text-white" strokeWidth={1.75} />
      </span>
      <h1 className="mt-5 font-display text-2xl sm:text-[28px] font-semibold text-gray-900 tracking-tight">
        Welcome to Evara AI 👋
      </h1>
      <p className="mt-2 text-sm text-gray-500 max-w-md mx-auto">
        Let's get your first AI assistant up and running.
      </p>

      <div className="mt-8 grid gap-3 sm:grid-cols-3 max-w-2xl mx-auto text-left">
        <Link
          to="/assistants"
          onClick={markWelcomeSeen}
          className="card card-hover flex flex-col gap-2 p-4"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl
                           border border-brand-400/25 bg-brand-500/15 text-brand-600">
            <Sparkles className="h-[18px] w-[18px]" strokeWidth={1.75} />
          </span>
          <span className="text-[13.5px] font-semibold text-gray-900">Create my first assistant</span>
          <span className="text-xs text-gray-500">Recommended · ~5 minutes</span>
        </Link>

        <button
          type="button"
          onClick={() => {
            markWelcomeSeen();
            startTour();
          }}
          className="card card-hover flex flex-col gap-2 p-4 text-left"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl
                           border border-brand-400/25 bg-brand-500/15 text-brand-600">
            <PlayCircle className="h-[18px] w-[18px]" strokeWidth={1.75} />
          </span>
          <span className="text-[13.5px] font-semibold text-gray-900">Watch how Evara AI works</span>
          <span className="text-xs text-gray-500">2 min product tour</span>
        </button>

        <button
          type="button"
          onClick={markWelcomeSeen}
          className="card card-hover flex flex-col gap-2 p-4 text-left"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl
                           border border-gray-200 bg-gray-100 text-gray-500">
            <Compass className="h-[18px] w-[18px]" strokeWidth={1.75} />
          </span>
          <span className="text-[13.5px] font-semibold text-gray-900">I'll explore myself</span>
          <span className="text-xs text-gray-500">Skip straight to the dashboard</span>
        </button>
      </div>

      <p className="mt-7 text-xs font-medium text-gray-400">
        {doneCount} / {totalCount} steps completed
      </p>
    </div>
  );
}
