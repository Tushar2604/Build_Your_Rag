// Public marketing landing page — the product's front door.
//
// Structurally this is the reference design one-for-one: a vivid coral →
// magenta → violet frame, a near-black rounded panel inset into it, a capsule
// nav, a mixed-weight headline, a haloed CTA, and two glass feature cards
// ("Secure Data" / "Custom Voice Agents") carrying inline UI mockups.
//
// Nothing here is behind auth and nothing here touches the console. The signed
// -in product still lives at /home and its flows are untouched — the only link
// between the two is the Login / Dashboard button in the nav.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Bot, Mic, MessageCircle, Radio, BookOpen, LineChart, Megaphone, Plug,
  PhoneOutgoing, Users2, ChevronDown, Check, ArrowRight, Sparkles,
  FileText, LifeBuoy, Code2, User,
} from "lucide-react";
import { useAuth } from "../store/auth";

/* ────────────────────────────────────────────────────────────────────────────
   Nav menus. These describe what the platform actually provides — "Product"
   lists the agents you can build, "Features" the platform capabilities behind
   them, "Resources" the supporting material.
   ──────────────────────────────────────────────────────────────────────── */

interface MenuEntry {
  label: string;
  desc: string;
  icon: typeof Bot;
  to: string;
}

const PRODUCT_MENU: MenuEntry[] = [
  { label: "Voice AI Assistants", desc: "RAG-grounded agents that answer from your data, on the phone or the web.", icon: Bot,           to: "/assistants" },
  { label: "Hiring Agent",        desc: "Screens candidates end to end and writes up every interview.",              icon: Radio,         to: "/hiring-agent" },
  { label: "WhatsApp Agent",      desc: "Read, reply and run campaigns from a linked WhatsApp number.",              icon: MessageCircle, to: "/channels" },
  { label: "Voice Cloning",       desc: "Put your own voice on every outbound call your agents make.",               icon: Mic,           to: "/clone-voice" },
];

const FEATURES_MENU: MenuEntry[] = [
  { label: "Knowledge Base",     desc: "Connect documents — indexed, chunked and cited automatically.", icon: BookOpen,      to: "/knowledge" },
  { label: "Live Analytics",     desc: "Knowledge gaps, retrieval scores and latency in real time.",    icon: LineChart,     to: "/analytics" },
  { label: "Broadcast Campaigns",desc: "Run voice and WhatsApp outreach at volume, on a schedule.",     icon: Megaphone,     to: "/broadcasts" },
  { label: "Call Logs",          desc: "Every conversation transcribed, scored and searchable.",        icon: PhoneOutgoing, to: "/interviews" },
  { label: "Integrations",       desc: "Plug the platform into the stack you already run.",             icon: Plug,          to: "/integrations" },
  { label: "Team & Roles",       desc: "Owner, admin and member access across one workspace.",          icon: Users2,        to: "/team" },
];

const RESOURCES_MENU: MenuEntry[] = [
  { label: "Documentation", desc: "Guides for building, deploying and tuning your agents.", icon: FileText,  to: "/knowledge" },
  { label: "API Reference", desc: "REST endpoints, webhooks and the embeddable widget.",    icon: Code2,     to: "/integrations" },
  { label: "Support",       desc: "Report an issue and track it through to resolution.",    icon: LifeBuoy,  to: "/report-issue" },
];

const MENUS: Record<string, MenuEntry[]> = {
  Product: PRODUCT_MENU,
  Features: FEATURES_MENU,
  Resources: RESOURCES_MENU,
};

/* ────────────────────────────────────────────────────────────────────────────
   Decorative glow torus — the rendered 3D rings bleeding in from either edge.
   Built from concentric skewed ellipses with a blur filter rather than a
   bitmap, so it stays sharp at any size and ships no assets.
   ──────────────────────────────────────────────────────────────────────── */
function TorusGlow({ tone, className }: { tone: "coral" | "violet"; className?: string }) {
  const id = `torus-${tone}`;
  const stops =
    tone === "coral"
      ? ["#ff8a3c", "#ff5722", "#7a1f00"]
      : ["#c4a2ff", "#8b5cf6", "#2a1060"];

  return (
    <svg
      viewBox="0 0 400 400"
      aria-hidden="true"
      className={`pointer-events-none absolute select-none ${className ?? ""}`}
    >
      <defs>
        <radialGradient id={`${id}-g`} cx="50%" cy="50%" r="50%">
          <stop offset="55%" stopColor={stops[0]} stopOpacity="0" />
          <stop offset="82%" stopColor={stops[1]} stopOpacity="0.95" />
          <stop offset="100%" stopColor={stops[2]} stopOpacity="0" />
        </radialGradient>
        <filter id={`${id}-b`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>
      <g filter={`url(#${id}-b)`} transform="rotate(-28 200 200)">
        {[0, 1, 2, 3, 4].map((i) => (
          <ellipse
            key={i}
            cx="200"
            cy="200"
            rx={168 - i * 22}
            ry={104 - i * 14}
            fill="none"
            stroke={`url(#${id}-g)`}
            strokeWidth={2.5 - i * 0.25}
            opacity={0.9 - i * 0.13}
          />
        ))}
      </g>
    </svg>
  );
}

/** The small "+" sparkles scattered across the panel in the reference. */
function Plus({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`pointer-events-none absolute text-white/25 text-sm font-light select-none ${className ?? ""}`}
    >
      +
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Nav
   ──────────────────────────────────────────────────────────────────────── */
function NavBar() {
  const { isAuthenticated } = useAuth();
  const [open, setOpen] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(null);
    }
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(null);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  const items = ["Home", "Product", "Features", "Resources", "Customers"];

  return (
    <div className="relative z-30 flex items-center justify-between px-5 sm:px-8 lg:px-10 pt-6 lg:pt-7">
      {/* Logotype */}
      <Link to="/" className="flex items-center gap-2.5 flex-shrink-0">
        <span className="w-8 h-8 rounded-xl bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700
                         flex items-center justify-center shadow-[0_6px_18px_-6px_rgba(139,92,246,0.9)]">
          <Bot className="w-[17px] h-[17px] text-white" strokeWidth={2} />
        </span>
        <span className="font-display font-bold text-[19px] tracking-tight text-white">
          Evara<span className="text-aurora">AI</span>
        </span>
      </Link>

      {/* Capsule nav */}
      <div
        ref={wrapRef}
        onMouseLeave={() => setOpen(null)}
        className="hidden lg:flex absolute left-1/2 -translate-x-1/2"
      >
        <nav
          aria-label="Main"
          className="flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.05] p-1 backdrop-blur-xl"
        >
          {items.map((label) => {
            const menu = MENUS[label];
            const isOpen = open === label;
            const active = label === "Home";

            if (!menu) {
              return (
                <Link
                  key={label}
                  to={label === "Home" ? "/" : "/register"}
                  onMouseEnter={() => setOpen(null)}
                  className={`rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors ${
                    active
                      ? "bg-ink-950 text-white shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]"
                      : "text-gray-400 hover:text-white"
                  }`}
                >
                  {label}
                </Link>
              );
            }

            return (
              <div key={label} onMouseEnter={() => setOpen(label)} className="relative">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  aria-haspopup="true"
                  onClick={() => setOpen(isOpen ? null : label)}
                  className={`flex items-center gap-1 rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors ${
                    isOpen ? "text-white" : "text-gray-400 hover:text-white"
                  }`}
                >
                  {label}
                  <ChevronDown
                    className={`w-3.5 h-3.5 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                    strokeWidth={2}
                  />
                </button>

                {isOpen && (
                  <div
                    className={`absolute left-1/2 top-full z-50 mt-3 -translate-x-1/2 animate-scale-in
                                rounded-3xl border border-white/10 bg-ink-900/95 p-2.5 shadow-modal backdrop-blur-2xl
                                ${menu.length > 4 ? "w-[620px] grid grid-cols-2 gap-1" : "w-[360px]"}`}
                  >
                    {menu.map((entry) => {
                      const Icon = entry.icon;
                      return (
                        <Link
                          key={entry.label}
                          to={isAuthenticated ? entry.to : "/register"}
                          onClick={() => setOpen(null)}
                          className="group flex gap-3 rounded-2xl p-3 transition-colors hover:bg-white/[0.07]"
                        >
                          <span className="mt-0.5 flex-shrink-0 w-9 h-9 rounded-xl border border-brand-400/25
                                           bg-brand-500/15 flex items-center justify-center
                                           transition-colors group-hover:border-brand-400/50">
                            <Icon className="w-[17px] h-[17px] text-brand-400" strokeWidth={1.75} />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[13.5px] font-semibold text-white">{entry.label}</span>
                            <span className="block text-[12px] leading-snug text-gray-500 mt-0.5">{entry.desc}</span>
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2.5 flex-shrink-0">
        <Link
          to={isAuthenticated ? "/home" : "/login"}
          className="rounded-full border border-white/[0.12] bg-ink-950/80 px-5 py-2 text-[13px] font-semibold
                     text-white backdrop-blur-md transition-colors hover:bg-ink-800"
        >
          {isAuthenticated ? "Dashboard" : "Login"}
        </Link>
        <Link
          to="/register"
          className="rounded-full bg-white px-5 py-2 text-[13px] font-semibold text-ink-950
                     transition-transform hover:-translate-y-px"
        >
          Book a Demo
        </Link>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Feature card 1 — Secure Data
   The mockup is a credential form: avatar, a masked field, and a connector
   running out to a confirmation tick.
   ──────────────────────────────────────────────────────────────────────── */
function SecureDataMock() {
  return (
    <div className="relative h-[190px] sm:h-[210px] rounded-2xl overflow-hidden
                    bg-[radial-gradient(ellipse_at_50%_120%,rgba(249,115,22,0.18),transparent_65%)]">
      <Plus className="top-4 right-5" />
      <Plus className="bottom-5 left-6" />

      <div className="absolute left-1/2 top-1/2 -translate-x-[58%] -translate-y-1/2 w-[190px]
                      rounded-2xl border border-cta-500/30 bg-gradient-to-b from-cta-500/20 to-cta-700/10
                      p-4 backdrop-blur-sm">
        {/* Avatar */}
        <div className="mx-auto -mt-9 w-12 h-12 rounded-full border-[3px] border-white/15
                        bg-gradient-to-br from-cta-400 to-brand-600 flex items-center justify-center">
          <User className="w-5 h-5 text-white" strokeWidth={2} />
        </div>
        {/* Name field */}
        <div className="mt-4 h-7 rounded-lg bg-white/[0.09] border border-white/10" />
        {/* Masked password field */}
        <div className="mt-2.5 h-9 rounded-lg bg-gradient-to-r from-cta-500/45 to-cta-600/30
                        border border-cta-400/40 flex items-center justify-center gap-1.5">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="text-white/90 text-lg leading-none">✱</span>
          ))}
        </div>
      </div>

      {/* Connector + tick */}
      <div className="absolute right-[19%] top-1/2 -translate-y-1/2 flex items-center">
        <span className="block w-10 h-px bg-gradient-to-r from-cta-500/70 to-cta-400" />
        <span className="w-8 h-8 rounded-full bg-gradient-to-br from-cta-400 to-cta-600
                         flex items-center justify-center shadow-[0_0_18px_-2px_rgba(249,115,22,0.9)]">
          <Check className="w-4 h-4 text-white" strokeWidth={3} />
        </span>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Feature card 2 — Custom Voice Agents
   A roster of agents with one selected, and the confirmation pill floating
   over it.
   ──────────────────────────────────────────────────────────────────────── */
function VoiceAgentsMock() {
  return (
    <div className="relative h-[190px] sm:h-[210px] rounded-2xl overflow-hidden
                    bg-[radial-gradient(ellipse_at_50%_120%,rgba(139,92,246,0.22),transparent_65%)]">
      <Plus className="top-4 left-5" />
      <Plus className="bottom-6 right-6" />

      <div className="absolute inset-x-6 top-1/2 -translate-y-1/2 space-y-2.5">
        {/* Idle row */}
        <div className="ml-8 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.05] p-2.5">
          <span className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-300 to-gray-500 flex items-center justify-center flex-shrink-0">
            <User className="w-4 h-4 text-ink-950" strokeWidth={2} />
          </span>
          <span className="h-2.5 flex-1 rounded-full bg-white/[0.12]" />
        </div>

        {/* Selected row — lifted, violet, glowing */}
        <div className="relative z-10 flex items-center gap-3 rounded-xl border border-brand-400/40
                        bg-gradient-to-r from-brand-500/35 to-brand-700/20 p-2.5
                        shadow-[0_8px_28px_-8px_rgba(139,92,246,0.9)]">
          <span className="w-9 h-9 rounded-full bg-gradient-to-br from-cta-400 to-brand-600 flex items-center justify-center flex-shrink-0">
            <User className="w-4 h-4 text-white" strokeWidth={2} />
          </span>
          <span className="h-2.5 flex-1 rounded-full bg-white/35" />
        </div>

        {/* Idle row */}
        <div className="ml-8 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.05] p-2.5">
          <span className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-400 to-gray-600 flex items-center justify-center flex-shrink-0">
            <User className="w-4 h-4 text-ink-950" strokeWidth={2} />
          </span>
          <span className="h-2.5 flex-1 rounded-full bg-white/[0.12]" />
        </div>
      </div>

      {/* Floating confirmation pill */}
      <div className="absolute right-3 bottom-7 z-20 flex items-center gap-2 rounded-full
                      border border-white/15 bg-gradient-to-r from-cta-500/90 to-brand-600/90
                      px-3.5 py-2 backdrop-blur-md shadow-[0_10px_28px_-8px_rgba(0,0,0,0.8)]">
        <span className="text-[12px] font-semibold text-white whitespace-nowrap">Agent Selected</span>
        <span className="w-4 h-4 rounded-full bg-white/95 flex items-center justify-center">
          <Check className="w-2.5 h-2.5 text-brand-700" strokeWidth={4} />
        </span>
      </div>
    </div>
  );
}

function FeatureCard({
  title, desc, children, delay,
}: { title: string; desc: string; children: React.ReactNode; delay: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.16, 1, 0.3, 1] }}
      className="group relative rounded-3xl border border-white/[0.09] bg-white/[0.03] p-4 sm:p-5
                 backdrop-blur-xl transition-all duration-300
                 hover:border-brand-400/30 hover:-translate-y-1
                 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06),0_20px_50px_-24px_rgba(0,0,0,0.9)]"
    >
      {children}
      <h3 className="font-display text-[17px] font-semibold text-white mt-5">{title}</h3>
      <p className="text-[13px] leading-relaxed text-gray-500 mt-2">{desc}</p>
    </motion.div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Page
   ──────────────────────────────────────────────────────────────────────── */
export default function LandingPage() {
  return (
    // Outer frame: the saturated aurora. The dark panel is inset into it, which
    // is what gives the reference its "screenshot floating on light" quality.
    <div
      className="min-h-screen w-full p-3 sm:p-5 lg:p-8"
      style={{
        backgroundColor: "#c2409a",
        backgroundImage: [
          "radial-gradient(ellipse 65% 75% at 0% 0%, #ff8a3c 0%, transparent 58%)",
          "radial-gradient(ellipse 55% 60% at 72% 0%, #e0409a 0%, transparent 60%)",
          "radial-gradient(ellipse 75% 95% at 100% 40%, #a855f7 0%, transparent 62%)",
          "radial-gradient(ellipse 70% 60% at 12% 100%, #f97316 0%, transparent 60%)",
          "radial-gradient(ellipse 80% 70% at 90% 100%, #8b5cf6 0%, transparent 62%)",
          "linear-gradient(135deg, #f4784a 0%, #c2409a 48%, #8b5cf6 100%)",
        ].join(","),
      }}
    >
      <main
        className="relative isolate overflow-hidden rounded-[24px] lg:rounded-[34px] bg-[#0a0613]
                   min-h-[calc(100vh-1.5rem)] sm:min-h-[calc(100vh-2.5rem)] lg:min-h-[calc(100vh-4rem)]
                   shadow-[0_40px_120px_-30px_rgba(0,0,0,0.9)]"
      >
        {/* Interior wash + perforated corners */}
        <div className="pointer-events-none absolute inset-0 -z-10 bg-aurora-soft opacity-70" />
        <div
          className="pointer-events-none absolute inset-0 -z-10 bg-dot-grid bg-dot-sm opacity-[0.45]"
          style={{
            WebkitMaskImage: "radial-gradient(ellipse 55% 50% at 50% 42%, transparent 30%, black 100%)",
            maskImage: "radial-gradient(ellipse 55% 50% at 50% 42%, transparent 30%, black 100%)",
          }}
        />

        {/* Rendered rings bleeding in from either edge */}
        <TorusGlow tone="coral"  className="-left-32 top-[26%] w-[440px] h-[440px] opacity-80" />
        <TorusGlow tone="violet" className="-right-32 top-[22%] w-[460px] h-[460px] opacity-80" />

        <NavBar />

        {/* Dotted arc under the nav, as in the reference */}
        <div
          className="pointer-events-none absolute left-1/2 top-[76px] -translate-x-1/2 w-[420px] h-[90px]
                     bg-dot-grid bg-dot-sm opacity-40"
          style={{
            WebkitMaskImage: "radial-gradient(ellipse 50% 100% at 50% 0%, black 0%, transparent 72%)",
            maskImage: "radial-gradient(ellipse 50% 100% at 50% 0%, black 0%, transparent 72%)",
          }}
        />

        {/* ── Hero ── */}
        <section className="relative z-10 px-5 sm:px-8 pt-16 sm:pt-20 lg:pt-24 text-center">
          <motion.span
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
            className="pill-glow"
          >
            Industry&apos;s Best Software
          </motion.span>

          {/* Weight, not size, carries the emphasis — the light surrounding
              words are what make the bold span land. */}
          <motion.h1
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
            className="font-display font-light tracking-[-0.035em] leading-[1.08] mt-7
                       text-[34px] sm:text-[48px] lg:text-[60px]"
          >
            <span className="text-gray-500">Smart </span>
            <span className="font-semibold text-white">Voice Agent</span>
            <span className="text-white"> Powered By AI</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.16, ease: "easeOut" }}
            className="mx-auto mt-6 max-w-xl text-[13.5px] sm:text-sm leading-relaxed text-gray-500"
          >
            Deploy production-ready voice and chat agents grounded in your own knowledge.
            Connect your documents, configure behaviour, and ship to phone, WhatsApp and
            the web in minutes.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.45, delay: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className="mt-9 flex justify-center"
          >
            <span className="glow-ring inline-flex rounded-full">
              <Link
                to="/register"
                className="inline-flex items-center gap-2 rounded-full border border-white/15
                           bg-ink-950 px-7 py-3 text-[14px] font-semibold text-white
                           transition-colors hover:bg-ink-800"
              >
                Get Started
                <Sparkles className="w-4 h-4 text-brand-400" strokeWidth={2} />
              </Link>
            </span>
          </motion.div>
        </section>

        {/* ── Two feature cards ── */}
        <section className="relative z-10 mx-auto mt-14 lg:mt-16 grid max-w-4xl grid-cols-1 gap-5 px-5 pb-16 sm:px-8 md:grid-cols-2">
          <FeatureCard
            delay={0.3}
            title="Secure Data"
            desc="Your documents stay yours. Every workspace is tenant-isolated, credentials are encrypted at rest, and each answer cites the source it came from — so you can always audit what the agent said and why."
          >
            <SecureDataMock />
          </FeatureCard>

          <FeatureCard
            delay={0.38}
            title="Custom Voice Agents"
            desc="Build an agent per job — support, screening, outreach — each with its own knowledge, persona and cloned voice. Pick one, point it at a number, and it is live on the next call."
          >
            <VoiceAgentsMock />
          </FeatureCard>
        </section>

        {/* Quiet footer strip */}
        <footer className="relative z-10 border-t border-white/[0.06] px-5 sm:px-8 lg:px-10 py-6
                           flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-[11px] text-gray-600">
            &copy; {new Date().getFullYear()} Evara AI · All rights reserved
          </p>
          <Link
            to="/register"
            className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-gray-500
                       transition-colors hover:text-white group"
          >
            Start building
            <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </footer>
      </main>
    </div>
  );
}
