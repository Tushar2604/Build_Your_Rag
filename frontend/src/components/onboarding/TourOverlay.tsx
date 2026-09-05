// The guided tour, cut into per-area walkthroughs.
//
// It used to be one seven-step run of the entire product, played once, with a
// single "done" flag. Two things were wrong with that. It arrived at the worst
// possible moment — before the person had created anything, so five of its
// seven steps described pages that were still empty — and once finished or
// skipped it could never come back, which is why a workspace that later wanted
// to set up booking got no help with it at all.
//
// Now each area owns a short tour, `startTour(area)` runs it, and it is offered
// from the next-step card at the point the person is actually being asked to do
// that thing. Skipping does not mark it seen; only finishing does. Replaying is
// always allowed.
//
// Mounted once in Layout.tsx so it survives the route changes it makes itself —
// each step names the route its target lives on (or none, for a step that
// spotlights something always-mounted like a sidebar item).
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

/** Keyed by area — the same keys the backend puts on `next_step.tour` and
 * stores in `tours_completed`. Adding an area here without adding it there
 * simply means nothing ever offers it. */
const TOURS: Record<string, TourStep[]> = {
  assistants: [
    {
      key: "nav-assistants",
      title: "This is where your assistant lives",
      body: "Build, edit and publish every assistant your workspace runs from here.",
    },
    {
      key: "assistant-create-box",
      route: "/assistants",
      title: "Describe it in plain English",
      body: '"Create an AI receptionist for my eye clinic that answers patient questions and books appointments." Evara AI writes the conversation flow for you — or press the mic and just say it.',
    },
    {
      key: null,
      title: "Then talk to it",
      body: "Once it exists, open it and hit Test to try it by chat or by voice — before anyone else does.",
    },
  ],
  knowledge: [
    {
      key: "knowledge-upload",
      route: "/knowledge",
      title: "Give it something to answer from",
      body: "Upload documents, FAQs, price lists, policies. Your assistant answers from these instead of guessing.",
    },
  ],
  channels: [
    {
      key: "channels-grid",
      route: "/channels",
      adminOnly: true,
      title: "Choose where it works",
      body: "Phone, WhatsApp, or the web widget — pick the channels it should answer on, then publish it from its own page. Publishing is what takes it live.",
    },
  ],
  appointments: [
    {
      key: "appointments-setup",
      route: "/appointments/services",
      adminOnly: true,
      title: "It can manage your calendar",
      body: "No external calendar needed. Set your locations, services and opening hours here, and your assistant checks availability and books directly.",
    },
  ],
  integrations: [
    {
      key: "integrations-grid",
      route: "/integrations",
      adminOnly: true,
      title: "Connect your tools",
      body: "Link a CRM, WhatsApp, Sheets and more, so your assistant can act on a conversation rather than just have one.",
    },
  ],
};

const CARD_WIDTH = 320;
const PAD = 10;
const MAX_WAIT_FRAMES = 60;

export default function TourOverlay() {
  const { tourStatus, tourArea, tourStepIndex, advanceTour, endTour } = useOnboarding();
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [ready, setReady] = useState(false);

  const steps = (tourArea ? TOURS[tourArea] ?? [] : []).filter((s) => !s.adminOnly || isAdmin);
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
      // Deliberately stays put. The old tour ended by navigating to the
      // dashboard, which threw away the page it had just walked someone to and
      // left them to find it again.
      endTour("done");
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
            {isLast ? "Got it" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}
