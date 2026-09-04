// The dashboard's setup checklist — replaces the hero/stats/shortcuts for a
// tenant that hasn't finished setting up its first assistant yet. Step
// completion is computed from real data (never a fake progress bar); only
// "tested" has no backend signal and falls back to a client-side flag set the
// first time TestModePanel opens (see store/onboarding.tsx).
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { Chatbot } from "../../api/chatbots";
import { useOnboarding } from "../../store/onboarding";

export interface SetupStep {
  title: string;
  hint: string;
  href: string;
  done: boolean;
}

export interface SetupInputs {
  bots: Chatbot[];
  hasReadyDocument: boolean;
  appointmentsReady: boolean;
  integrationsConnected: boolean;
  whatsappConnected: boolean;
  testedAssistant: boolean;
  isAdmin: boolean;
}

/** Shared by SetupChecklist (the rows) and WelcomeScreen (the "N / total"
 * count), so the two can never disagree. */
export function getSetupSteps(input: SetupInputs): SetupStep[] {
  const firstBotId = input.bots[0]?.id;
  const isLive = input.bots.some((b) => b.is_public);

  const steps: SetupStep[] = [
    {
      title: "Create your assistant",
      hint: "Tell Evara AI what you want your assistant to do.",
      href: "/assistants",
      done: input.bots.length > 0,
    },
    {
      title: "Give it knowledge",
      hint: "Add your FAQs, documents and business information.",
      href: "/knowledge",
      done: input.hasReadyDocument,
    },
  ];

  if (input.isAdmin) {
    steps.push({
      title: "Let it manage appointments",
      hint: "Set your locations, services and hours — no external calendar needed.",
      href: "/appointments/services",
      done: input.appointmentsReady,
    });
    steps.push({
      title: "Connect your tools",
      hint: "Link a CRM, WhatsApp, Sheets and other tools.",
      href: "/integrations",
      done: input.integrationsConnected,
    });
    steps.push({
      title: "Choose where it works",
      hint: "Phone, WhatsApp, website and more.",
      href: "/channels",
      done: input.whatsappConnected || isLive,
    });
  }

  steps.push({
    title: "Test your assistant",
    hint: "Make sure everything works before going live.",
    href: firstBotId ? `/assistants/${firstBotId}` : "/assistants",
    done: input.testedAssistant,
  });

  steps.push({
    title: "Go live",
    hint: "Publish your assistant so it can start answering.",
    href: firstBotId ? `/assistants/${firstBotId}?tab=config` : "/assistants",
    done: isLive,
  });

  return steps;
}

export default function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const { dismissChecklist } = useOnboarding();
  const done = steps.filter((s) => s.done).length;
  const pct = Math.round((done / steps.length) * 100);

  return (
    <div className="card p-6 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-semibold text-gray-900 tracking-tight">
            Let's build your first AI assistant
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            You're {pct}% complete — {done} of {steps.length} steps done.
          </p>
        </div>
        <button
          type="button"
          onClick={dismissChecklist}
          className="text-xs font-medium text-gray-400 hover:text-gray-600"
        >
          Skip for now
        </button>
      </div>

      <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="mt-6 divide-y divide-gray-100">
        {steps.map((step, i) => (
          <li key={step.title} className="flex items-center gap-4 py-3.5">
            <span
              className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                step.done
                  ? "bg-emerald-50 text-emerald-700"
                  : "border border-gray-200 text-gray-400"
              }`}
            >
              {step.done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-semibold text-gray-900">{step.title}</span>
              <span className="mt-0.5 block text-xs text-gray-500">{step.hint}</span>
            </span>
            {!step.done && (
              <Link to={step.href} className="btn-secondary btn-sm flex-shrink-0">
                {step.title === "Go live" ? "Deploy assistant" : "Continue"}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
