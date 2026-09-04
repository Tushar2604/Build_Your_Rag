// The guided product tour. Mounted once in Layout.tsx so it survives route
// changes while running — each step names the route its target lives on (or
// none, for a step that spotlights something always-mounted like a sidebar
// item, or an informational step with no live target at all).
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import { useAuth } from "../../store/auth";
import { useOnboarding } from "../../store/onboarding";

interface TourStep {
  /** `data-tour` value to spotlight, or null for an informational step with
   * no live element (nothing exists yet to point at). */
  key: string | null;
  /** Route the target lives on. Omitted when the target is mounted on every
   * authenticated route (the sidebar). */
  route?: string;
  adminOnly?: boolean;
  title: string;
  body: string;
}

const STEPS: TourStep[] = [
  {
    key: "nav-assistants",
    title: "Create and manage your AI employees",
    body: "Voice AI Assistants is where you build, edit and publish every assistant your workspace runs.",
  },
  {
    key: "assistant-create-box",
    route: "/assistants",
    title: "Describe your assistant in plain English",
    body: '"Create an AI receptionist for my eye clinic that answers patient questions and books appointments." EvaraAI writes the conversation flow for you — or press the mic and just say it.',
  },
  {
    key: "knowledge-upload",
    route: "/knowledge",
    title: "Add your knowledge",
    body: "Upload documents, FAQs, policies and other information your assistant can answer from.",
  },
  {
    key: "appointments-setup",
    route: "/appointments/services",
    adminOnly: true,
    title: "Let it manage your own calendar",
    body: "No external calendar needed — set your locations, services and hours here and your assistant checks availability and books directly.",
  },
  {
    key: "integrations-grid",
    route: "/integrations",
    adminOnly: true,
    title: "Connect your tools",
    body: "Link a CRM, WhatsApp, Sheets and other tools so your assistant can act, not just answer.",
  },
  {
    key: null,
    title: "Test before anyone else does",
    body: "Once an assistant exists, open it and hit Test to talk to it — by chat or voice — before it's live.",
  },
  {
    key: "channels-grid",
    route: "/channels",
    adminOnly: true,
    title: "Choose where it works",
    body: "Phone, WhatsApp, or the web widget — pick the channels your assistant should answer on, then publish it from its own page.",
  },
];

const CARD_WIDTH = 320;
const PAD = 10;
const MAX_WAIT_FRAMES = 60;

export default function TourOverlay() {
  const { tourStatus, tourStepIndex, advanceTour, endTour } = useOnboarding();
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [ready, setReady] = useState(false);

  const steps = STEPS.filter((s) => !s.adminOnly || isAdmin);
  const step = steps[tourStepIndex];
  const running = tourStatus === "running" && !!step;

  // Navigate to the step's route first, if we're not already there.
  useEffect(() => {
    if (!running) return;
    if (step.route && location.pathname !== step.route) {
      navigate(step.route);
    }
  }, [running, step, location.pathname, navigate]);

  // Measure the target once it's on the right route and mounted — a short
  // rAF poll covers the gap between navigating and the new page rendering.
  useEffect(() => {
    if (!running) return;
    setReady(false);
    if (!step.key) {
      setRect(null);
      setReady(true);
      return;
    }
    if (step.route && location.pathname !== step.route) return;

    let frame = 0;
    let raf: number;
    const tick = () => {
      const el = document.querySelector(`[data-tour="${step.key}"]`);
      if (el) {
        setRect(el.getBoundingClientRect());
        setReady(true);
        return;
      }
      frame += 1;
      if (frame < MAX_WAIT_FRAMES) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running, step, location.pathname]);

  // Keep the spotlight glued to its target through scroll/resize.
  useEffect(() => {
    if (!running || !step?.key) return;
    const reposition = () => {
      const el = document.querySelector(`[data-tour="${step.key}"]`);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [running, step]);

  if (!running || !ready) return null;

  const isLast = tourStepIndex === steps.length - 1;

  function next() {
    if (isLast) {
      endTour("done");
      navigate("/dashboard");
    } else {
      advanceTour();
    }
  }

  function skip() {
    endTour("skipped");
  }

  // Card placement: beside/below the target when there is one, centered
  // when this is an informational step.
  let cardStyle: React.CSSProperties;
  if (rect) {
    const left = Math.min(Math.max(rect.left, 16), window.innerWidth - CARD_WIDTH - 16);
    const spaceBelow = window.innerHeight - rect.bottom;
    const placeBelow = spaceBelow > 220;
    cardStyle = {
      position: "fixed",
      left,
      width: CARD_WIDTH,
      ...(placeBelow ? { top: rect.bottom + 16 } : { bottom: window.innerHeight - rect.top + 16 }),
    };
  } else {
    cardStyle = {
      position: "fixed",
      left: "50%",
      top: "50%",
      width: CARD_WIDTH,
      transform: "translate(-50%, -50%)",
    };
  }

  return (
    <>
      {/* Scrim with a spotlight cutout around the target, or a plain dim
          backdrop for an informational step. */}
      <div className="fixed inset-0 z-[200] pointer-events-none transition-all duration-300"
           style={
             rect
               ? {
                   position: "fixed",
                   top: rect.top - PAD,
                   left: rect.left - PAD,
                   width: rect.width + PAD * 2,
                   height: rect.height + PAD * 2,
                   borderRadius: 14,
                   boxShadow: "0 0 0 9999px rgba(6,4,13,0.72)",
                 }
               : { background: "rgba(6,4,13,0.72)" }
           }
      />
      <div className="card shadow-modal z-[201] p-5 animate-scale-in" style={cardStyle}>
        <div className="flex items-start justify-between gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-brand-600">
            Step {tourStepIndex + 1} of {steps.length}
          </p>
          <button
            type="button"
            onClick={skip}
            aria-label="Skip tour"
            className="icon-btn -mt-1 -mr-1"
          >
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>
        <h3 className="mt-2 text-[15px] font-semibold text-gray-900">{step.title}</h3>
        <p className="mt-1.5 text-[13px] leading-relaxed text-gray-600">{step.body}</p>
        <div className="mt-4 flex items-center justify-between">
          <button type="button" onClick={skip} className="text-xs font-medium text-gray-400 hover:text-gray-600">
            Skip tour
          </button>
          <button type="button" onClick={next} className="btn-primary btn-sm">
            {isLast ? "Finish setup" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}
