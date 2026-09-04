// Dashboard — the first screen after sign-in.
//
// Deliberately not a second Overview. `/home` is the operational read-out
// (tables of assistants, recent queries, scores) and stays exactly that; this
// page answers the question someone actually has the moment they land: "what
// is this workspace, and what do I do next?". So it leads with the same hero
// the sign-in screen uses — the aurora panel, the eyebrow pill, the light
// display headline with one solid accent span — and puts the single action
// that matters, creating a voice AI assistant, under the halo CTA.
//
// The stat strip and the shortcut grid sit *below* the hero rather than above
// it: a brand-new workspace has nothing to report, and opening on a row of
// dashes reads as a broken product rather than an empty one.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight, Bot, BookOpen, Check, Database, LineChart, ListChecks,
  Megaphone, MessagesSquare, Mic, Sparkles, UserSearch,
} from "lucide-react";

import { listChatbots, Chatbot } from "../api/chatbots";
import { listDocuments } from "../api/documents";
import { getChatbotAnalytics } from "../api/analytics";
import { listCandidates } from "../api/candidates";
import { getIntegrationCatalogue } from "../api/integrationsCatalogue";
import { listWhatsAppChannels } from "../api/whatsapp";
import { appointmentsApi } from "../api/appointments";
import { useAuth } from "../store/auth";
import { useOnboarding } from "../store/onboarding";
import WelcomeScreen from "../components/onboarding/WelcomeScreen";
import SetupChecklist, { getSetupSteps } from "../components/onboarding/SetupChecklist";

/** The same four promises the sign-in screen makes, kept verbatim so the
 * product does not change its pitch the second you get inside it. */
const CAPABILITIES = [
  "RAG-powered assistants grounded in your data",
  "Real-time streaming with citation transparency",
  "Knowledge gaps analytics — know what to add next",
  "Web widget, public link, and REST API deployment",
];

interface Shortcut {
  to: string;
  label: string;
  hint: string;
  icon: typeof Bot;
  adminOnly?: boolean;
}

const SHORTCUTS: Shortcut[] = [
  { to: "/clone-voice", label: "Clone a voice", hint: "Give an assistant your own voice", icon: Mic },
  { to: "/knowledge", label: "Add knowledge", hint: "Upload the docs it answers from", icon: BookOpen },
  { to: "/candidates", label: "Candidates", hint: "Everyone who has messaged you", icon: UserSearch, adminOnly: true },
  { to: "/interviews/bulk", label: "Bulk call", hint: "Run one script across a list", icon: ListChecks, adminOnly: true },
  { to: "/broadcasts", label: "Broadcast", hint: "Message a list, then auto-reply", icon: Megaphone, adminOnly: true },
  { to: "/analytics", label: "Analytics", hint: "What it answered, and how well", icon: LineChart },
];

interface Stats {
  assistants: number;
  live: number;
  queries: number;
  docsReady: number;
  docsTotal: number;
  candidates: number;
  integrationsConnected: boolean;
  whatsappConnected: boolean;
  appointmentsReady: boolean;
}

function StatTile({
  label, value, sub, icon: Icon, index,
}: { label: string; value: string; sub: string; icon: typeof Bot; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.06, ease: "easeOut" }}
      className="metric-card"
    >
      <div className="metric-card-icon">
        <Icon className="w-4 h-4" strokeWidth={1.75} />
      </div>
      <p className="metric-card-label">{label}</p>
      <p className="metric-card-value">{value}</p>
      <p className="metric-card-hint">{sub}</p>
    </motion.div>
  );
}

export default function DashboardPage() {
  const { isAdmin, email } = useAuth();
  const [bots, setBots] = useState<Chatbot[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Every read is independent and every one of them is allowed to fail:
      // a workspace with no WhatsApp number 403s on candidates, and that must
      // not blank the whole dashboard.
      const [botList, docs, candidatePage, integrations, whatsapp, readiness] = await Promise.all([
        listChatbots().catch(() => [] as Chatbot[]),
        listDocuments().catch(() => []),
        isAdmin
          ? listCandidates({ pageSize: 1 }).catch(() => null)
          : Promise.resolve(null),
        isAdmin
          ? getIntegrationCatalogue().catch(() => null)
          : Promise.resolve(null),
        isAdmin
          ? listWhatsAppChannels().catch(() => [])
          : Promise.resolve([]),
        isAdmin
          ? appointmentsApi.readiness().catch(() => null)
          : Promise.resolve(null),
      ]);

      const analytics = await Promise.allSettled(
        botList.map((b) => getChatbotAnalytics(b.id, 7)),
      );
      const queries = analytics.reduce(
        (total, res) =>
          res.status === "fulfilled"
            ? total + res.value.daily.reduce((a, d) => a + d.answers, 0)
            : total,
        0,
      );

      if (cancelled) return;
      setBots(botList);
      setStats({
        assistants: botList.length,
        live: botList.filter((b) => b.is_public).length,
        queries,
        docsReady: docs.filter((d) => d.status === "ready").length,
        docsTotal: docs.length,
        candidates: candidatePage?.total ?? 0,
        integrationsConnected: (integrations?.connected_count ?? 0) > 0,
        whatsappConnected: whatsapp.length > 0,
        appointmentsReady: readiness?.ready ?? false,
      });
      setLoading(false);
    }

    void load();
    return () => { cancelled = true; };
  }, [isAdmin]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const firstName = (email || "").split("@")[0];
  const shortcuts = SHORTCUTS.filter((s) => !s.adminOnly || isAdmin);

  const { welcomeSeen, testedAssistant, checklistDismissed } = useOnboarding();
  const setupSteps = stats
    ? getSetupSteps({
        bots,
        hasReadyDocument: stats.docsReady > 0,
        appointmentsReady: stats.appointmentsReady,
        integrationsConnected: stats.integrationsConnected,
        whatsappConnected: stats.whatsappConnected,
        testedAssistant,
        isAdmin,
      })
    : [];
  const setupDone = setupSteps.filter((s) => s.done).length;
  // Every tenant is auto-provisioned with a draft "Default Assistant" at
  // signup, so `bots.length > 0` is true from the very first load — it can't
  // be used to detect "brand new" the way a true zero-assistants state could.
  // The welcome screen is gated on the localStorage flag alone, same as
  // theme/sidebarMode elsewhere in the app (see store/onboarding.tsx) — the
  // accepted trade-off being a new browser/device sees it again.
  const showWelcome = !loading && !welcomeSeen;
  const showChecklist =
    !loading && !showWelcome && !checklistDismissed && setupDone < setupSteps.length;

  return (
    <div className="page">
      {showWelcome ? (
        <WelcomeScreen doneCount={setupDone} totalCount={setupSteps.length} />
      ) : showChecklist ? (
        <SetupChecklist steps={setupSteps} />
      ) : (
      <>
      {/* ── Hero ──────────────────────────────────────────────────────────
          `aurora-shell` pins the dark palette regardless of the theme toggle,
          which is what lets the coral→violet gradient and the light display
          type land the same way they do on the sign-in screen. */}
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="aurora-shell relative overflow-hidden rounded-3xl border border-white/[0.08]
                   px-8 py-10 sm:px-12 sm:py-14"
      >
        {/* Two blooms rather than a flat fill — the panel reads as lit from
            behind, the way the sign-in frame does. */}
        <div className="pointer-events-none absolute -top-24 -right-16 h-72 w-72 rounded-full bg-brand-500/25 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 -left-20 h-72 w-72 rounded-full bg-cta-500/15 blur-3xl" />

        <div className="relative grid gap-10 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div className="min-w-0">
            <span className="pill-glow mb-6">Enterprise-grade RAG</span>

            <h1 className="font-display text-[34px] sm:text-[44px] font-light leading-[1.08]
                           tracking-[-0.03em] text-gray-500">
              Deploy <span className="font-semibold text-gray-950">AI assistants</span>
              <br className="hidden sm:block" />{" "}
              powered by <span className="text-aurora font-semibold">your knowledge</span>.
            </h1>

            <p className="mt-5 max-w-xl text-sm leading-relaxed text-gray-400">
              {greeting}
              {firstName ? `, ${firstName}` : ""}. Production-ready AI for enterprise teams —
              connect your docs, configure behaviour, and ship a voice assistant in minutes.
            </p>

            <ul className="mt-8 grid gap-3 sm:grid-cols-2">
              {CAPABILITIES.map((capability, i) => (
                <motion.li
                  key={capability}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: 0.15 + i * 0.06, ease: "easeOut" }}
                  className="flex items-start gap-3 text-[13px] leading-snug text-gray-400"
                >
                  <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center
                                   rounded-full border border-brand-400/30 bg-brand-500/15">
                    <Check className="h-3 w-3 text-brand-400" strokeWidth={3} />
                  </span>
                  {capability}
                </motion.li>
              ))}
            </ul>

            <div className="mt-10 flex flex-wrap items-center gap-3">
              {/* The halo is reserved for the one action this page exists to
                  offer. Everything else on the screen is a quiet link. */}
              <div className="glow-ring">
                <Link to="/assistants" className="btn-cta btn-lg">
                  <Sparkles className="h-4 w-4" strokeWidth={2.25} />
                  Create your own Voice AI assistant
                </Link>
              </div>
              <Link to="/knowledge" className="btn-secondary btn-lg">
                Connect knowledge
              </Link>
            </div>
          </div>

          {/* The orb: a decorative anchor for the right-hand column at desktop
              width, so the hero is not one very wide ragged text block. */}
          <div className="hidden lg:flex lg:w-[220px] lg:justify-center" aria-hidden="true">
            <div className="relative flex h-40 w-40 items-center justify-center">
              <div className="absolute inset-0 animate-glow-pulse rounded-full bg-gradient-to-br
                              from-cta-400 via-brand-500 to-brand-700 opacity-30 blur-2xl" />
              <div className="relative flex h-28 w-28 animate-float items-center justify-center rounded-[2rem]
                              bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700
                              shadow-[0_18px_48px_-12px_rgba(139,92,246,0.9)]">
                <Bot className="h-12 w-12 text-white" strokeWidth={1.5} />
              </div>
            </div>
          </div>
        </div>
      </motion.section>

      {/* ── Workspace at a glance ── */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          index={0}
          icon={Bot}
          label="Assistants"
          value={loading || !stats ? "—" : `${stats.live} / ${stats.assistants}`}
          sub="live / created"
        />
        <StatTile
          index={1}
          icon={MessagesSquare}
          label="Queries (7 days)"
          value={loading || !stats ? "—" : stats.queries.toLocaleString()}
          sub="answered across all assistants"
        />
        <StatTile
          index={2}
          icon={Database}
          label="Knowledge"
          value={loading || !stats ? "—" : `${stats.docsReady} / ${stats.docsTotal}`}
          sub="indexed / uploaded"
        />
        <StatTile
          index={3}
          icon={UserSearch}
          label="Candidates"
          value={loading || !stats ? "—" : stats.candidates.toLocaleString()}
          sub={isAdmin ? "conversations on record" : "admins only"}
        />
      </div>

      {/* ── Shortcuts ── */}
      <section className="mt-8">
        <h2 className="section-title mb-3">Jump straight in</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shortcuts.map(({ to, label, hint, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="card card-hover group flex items-start gap-3.5 p-4"
            >
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl
                               border border-brand-400/25 bg-brand-500/15 text-brand-600">
                <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold text-gray-900">{label}</span>
                <span className="mt-0.5 block text-xs leading-snug text-gray-500">{hint}</span>
              </span>
              <ArrowRight
                className="mt-1 h-4 w-4 flex-shrink-0 text-gray-400 transition-transform
                           group-hover:translate-x-0.5 group-hover:text-brand-600"
                strokeWidth={2}
              />
            </Link>
          ))}
        </div>
      </section>
      </>
      )}

      {/* ── Your assistants ──
          Shown only once there is something to show. The hero already carries
          the "create one" call, so an empty version of this block would be the
          third invitation on one screen. */}
      {!loading && bots.length > 0 && (
        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="section-title">Your voice AI assistants</h2>
            <Link
              to="/assistants"
              className="group inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              View all
              <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {bots.slice(0, 6).map((bot) => (
              <Link
                key={bot.id}
                to={`/assistants/${bot.id}`}
                className="card card-hover flex items-center gap-3 p-4"
              >
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl
                                 bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 text-white">
                  <Bot className="h-4 w-4" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-semibold text-gray-900">
                    {bot.name}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-gray-500">
                    <span className={bot.is_public ? "dot-live" : "dot-draft"} />
                    {bot.is_public ? "Live" : "Draft"}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
