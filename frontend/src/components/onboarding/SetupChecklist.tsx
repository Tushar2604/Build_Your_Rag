// The dashboard's setup checklist — the whole ladder, where the rail's
// next-step card shows only the current rung.
//
// Every step's completion comes from `milestones`, computed server-side from
// the tenant's own rows (see `src/domain/onboarding/entities.py`). Nothing here
// is a client-side flag any more: "tested" used to be one, which meant it reset
// every time someone opened the app in a different browser.
//
// Steps below the current stage collapse to a checked line, the current one is
// the only one with an action, and the rest are visibly ahead. Showing seven
// equally-weighted "Continue" buttons — which is what this did before — is the
// same failure the sidebar had: everything shouting, nothing prioritised.
import { Link } from "react-router-dom";
import { Check, Lock } from "lucide-react";
import { Milestones, Stage, STAGE_ORDER, stageIndex } from "../../api/onboarding";
import { useOnboarding } from "../../store/onboarding";

export interface SetupStep {
  title: string;
  hint: string;
  href: string;
  done: boolean;
  /** The stage this step belongs to — what decides whether it reads as past,
   * current or still ahead. */
  stage: Stage;
}

export function getSetupSteps(
  m: Milestones,
  isAdmin: boolean,
  firstBotId?: string,
): SetupStep[] {
  const steps: SetupStep[] = [
    {
      title: "Create your assistant",
      hint: "Tell Evara AI what you want your assistant to do.",
      href: "/assistants",
      done: m.assistant_configured,
      stage: "build",
    },
    {
      title: "Give it knowledge",
      hint: "Add your FAQs, documents and business information.",
      href: "/knowledge",
      done: m.knowledge_ready,
      stage: "teach",
    },
    {
      title: "Test your assistant",
      hint: "Talk to it by chat or voice before anyone else does.",
      href: firstBotId ? `/assistants/${firstBotId}` : "/assistants",
      done: m.assistant_tested,
      stage: "test",
    },
  ];

  if (isAdmin) {
    steps.push({
      title: "Choose where it works",
      hint: "Phone, WhatsApp, website and more.",
      href: "/channels",
      done: m.channel_connected,
      stage: "launch",
    });
  }

  steps.push({
    title: "Go live",
    hint: "Publish your assistant so it can start answering.",
    href: firstBotId ? `/assistants/${firstBotId}?tab=config` : "/assistants",
    done: m.assistant_live,
    stage: "launch",
  });

  if (isAdmin) {
    // Both sit at `operate`: they make a working assistant do more, and
    // neither is on the path to getting one working.
    steps.push({
      title: "Let it manage appointments",
      hint: "Set your locations, services and hours — no external calendar needed.",
      href: "/appointments/services",
      done: m.appointments_ready,
      stage: "operate",
    });
    steps.push({
      title: "Connect your tools",
      hint: "Link a CRM, WhatsApp, Sheets and other tools.",
      href: "/integrations",
      done: m.integrations_connected,
      stage: "operate",
    });
  }

  return steps;
}

export default function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const { dismiss, stage, nextStep, startTour } = useOnboarding();
  const done = steps.filter((s) => s.done).length;
  const pct = Math.round((done / steps.length) * 100);
  const here = stageIndex(stage);

  return (
    <div className="card p-6 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-semibold text-gray-900 tracking-tight">
            {done === 0 ? "Let's build your first AI assistant" : "Finish setting up"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            You're {pct}% complete — {done} of {steps.length} steps done.
            {stage !== "operate" && " More of the product unlocks as you go."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => dismiss("checklist")}
          className="text-xs font-medium text-gray-400 hover:text-gray-600"
        >
          Hide this
        </button>
      </div>

      <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Stage pips: what the ladder actually is, at a glance. */}
      <ol className="mt-5 flex items-center gap-1.5" aria-label="Setup progress">
        {STAGE_ORDER.map((s, i) => (
          <li
            key={s}
            title={s}
            className={`h-1 flex-1 rounded-full transition-colors ${
              i < here ? "bg-brand-500" : i === here ? "bg-brand-400/60" : "bg-gray-100"
            }`}
          />
        ))}
      </ol>

      <ol className="mt-5 divide-y divide-gray-100">
        {steps.map((step, i) => {
          const ahead = !step.done && stageIndex(step.stage) > here;
          // Exactly one step gets an action: the first unfinished one at or
          // below the current stage. Anything else is either history or a
          // preview, and neither needs a button.
          const isCurrent =
            !step.done && !ahead && steps.findIndex((s) => !s.done && stageIndex(s.stage) <= here) === i;

          return (
            <li
              key={step.title}
              className={`flex items-center gap-4 py-3.5 ${ahead ? "opacity-45" : ""}`}
            >
              <span
                className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  step.done
                    ? "bg-emerald-50 text-emerald-700"
                    : isCurrent
                      ? "bg-brand-500 text-white"
                      : "border border-gray-200 text-gray-400"
                }`}
              >
                {step.done ? (
                  <Check className="h-3.5 w-3.5" strokeWidth={3} />
                ) : ahead ? (
                  <Lock className="h-3 w-3" strokeWidth={2.5} />
                ) : (
                  i + 1
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold text-gray-900">
                  {step.title}
                </span>
                <span className="mt-0.5 block text-xs text-gray-500">{step.hint}</span>
              </span>
              {isCurrent && (
                <span className="flex flex-shrink-0 items-center gap-2">
                  {nextStep?.tour && (
                    <button
                      type="button"
                      onClick={() => startTour(nextStep.tour!)}
                      className="text-xs font-semibold text-gray-500 hover:text-gray-800"
                    >
                      Show me
                    </button>
                  )}
                  <Link to={step.href} className="btn-primary btn-sm">
                    {step.title === "Go live" ? "Deploy assistant" : "Continue"}
                  </Link>
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
