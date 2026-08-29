// Public marketing site — the product's front door.
//
// Laid out to the reference: a light editorial page with one saturated accent,
// large fluid display type, hairline-bordered cards, and uppercase letterspaced
// CTAs. Section order follows the reference too — hero, proof metrics, logo
// row, why-us, capability grid, a live runtime panel, pricing, testimonial,
// product cards, resources, closing CTA, FAQ.
//
// The palette and every component class live in the `.marketing` block in
// index.css, scoped so nothing here can reach the console — that is a dark
// violet workspace which themes with `data-theme`, and this is a fixed light
// page. Swapping `--m-accent` re-skins the whole site.
//
// Nothing on this page is behind auth. The only link to the product is the
// Log in / Dashboard button in the nav.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, Bot, BookOpen, CalendarCheck, Check, Clock, CreditCard,
  Home, Kanban, LineChart, Megaphone, MessageCircle, Mic, Minus, Phone,
  Plug, Plus, ShieldCheck, Sparkles, UserSearch, Zap,
} from "lucide-react";

import { useAuth } from "../store/auth";

/* ── Hero ─────────────────────────────────────────────────────────────────
   One promise, stated concretely. The reference leads with what the thing
   does for you rather than what it is built from, so this does too. */

const HERO_HEADLINE = "AI agents that answer, book, and follow up — on every channel you run.";
const HERO_SUB =
  "Give your front desk a teammate that never misses a call. Evara agents pick up the phone, reply on WhatsApp and chat, check your real calendar, take the booking, and hand you the notes.";

/* Three numbers that answer "is this serious?" before anything else does.
   Every one of them is something the product actually does today — a metric on
   a landing page is a promise the first demo has to keep. */
const PROOF: { value: string; label: string }[] = [
  { value: "24/7", label: "Never a missed call or a missed message" },
  { value: "4 channels", label: "Phone, WhatsApp, web chat and an embeddable widget" },
  { value: "Zero", label: "Invented prices, dates or slots — every answer is grounded" },
];

/* ── Why us ──────────────────────────────────────────────────────────────
   The three objections a buyer actually has, answered in their own words. */

const WHY: { icon: typeof Zap; title: string; body: string }[] = [
  {
    icon: ShieldCheck,
    title: "It never invents an answer",
    body:
      "Every fact comes from your own documents, and every time comes from your real calendar. When an agent does not know something, it says so and tells the caller who will — it does not guess a price or a slot.",
  },
  {
    icon: Zap,
    title: "It actually completes the job",
    body:
      "Not a chatbot that takes a message. The agent checks availability, holds the slot while it takes the details, writes the booking, and sends the confirmation — end to end, while the caller is still on the line.",
  },
  {
    icon: Kanban,
    title: "You stay in the driver's seat",
    body:
      "Read every conversation, take one over mid-thread, and change what the agent says by editing plain sentences — no prompt engineering, no redeploy, no waiting on us.",
  },
];

/* ── Capabilities ────────────────────────────────────────────────────────
   Six, matching the reference's grid. Written as what the agent does on a
   given day, not as a feature list. */

const CAPABILITIES: {
  icon: typeof Bot;
  title: string;
  body: string;
  /** Shown with a "Coming soon" pill and written in future tense. Roadmap
   * items earn a place here — a buyer planning around them deserves to know
   * which ones they cannot have on Monday. */
  soon?: boolean;
}[] = [
  {
    icon: Phone,
    title: "Answers the phone",
    body:
      "A real voice on an inbound or outbound call, in your own cloned voice if you want one. It handles interruptions, waits while people think, and never talks over them.",
  },
  {
    icon: CalendarCheck,
    title: "Books the appointment",
    body:
      "Reads your services, staff and opening hours, offers only times that are genuinely free, holds the slot while it takes the details, and books it. Reschedules and cancellations too.",
  },
  {
    icon: MessageCircle,
    title: "Runs your WhatsApp",
    body:
      "Link your number by QR and the agent answers there. A shared inbox for your team on top: assign a chat, tag it, take it over, and hand it back.",
  },
  {
    icon: BookOpen,
    title: "Knows your business",
    body:
      "Upload your price list, policies and FAQs. The agent answers from those documents and cites nothing it has not read — the difference between helpful and confidently wrong.",
  },
  {
    icon: CreditCard,
    title: "Takes the payment",
    body:
      "Will send a deposit or invoice link in the same conversation and confirm the booking once it settles, so a slot is paid for rather than pencilled in.",
    soon: true,
  },
  {
    icon: Megaphone,
    title: "Follows up on its own",
    body:
      "Chases a quiet lead, reminds a patient the day before, and runs a campaign to a list — then stops the moment someone replies and picks the conversation back up.",
  },
];

/* ── Hero scenes ─────────────────────────────────────────────────────────
   The panel beside the headline cycles through five real jobs rather than
   showing one.

   One scene made the product look like a dental booking tool. Five make the
   point the headline is actually making — same agent, different role, every
   channel — and they do it without the visitor scrolling or clicking, which
   is the only interaction a hero can rely on.

   Each carries its own channel, its own timer and its own outcome line,
   because "what did it actually achieve" is the part that differs between a
   booking, a screening and a qualified lead. */

type Channel = "Live call" | "WhatsApp" | "Web chat";

interface Scene {
  key: string;
  channel: Channel;
  role: string;
  /** Elapsed time in the header. Varied per scene — a fixed one across five
   * panels reads as a static image that happens to change text. */
  clock: string;
  transcript: { who: "agent" | "caller"; line: string }[];
  outcome: { icon: typeof Bot; text: string; pill: string };
}

const HERO_SCENES: Scene[] = [
  {
    key: "dental",
    channel: "Live call",
    role: "Dental clinic receptionist",
    clock: "00:42",
    transcript: [
      { who: "caller", line: "Hi, do you have anything for a cleaning this week?" },
      { who: "agent", line: "We do — Thursday at 4:15pm or Friday at 11am with Dr Rao. Which suits?" },
      { who: "caller", line: "Thursday please." },
      { who: "agent", line: "Booked. You'll get a confirmation on WhatsApp in a moment." },
    ],
    outcome: { icon: CalendarCheck, text: "Booked · Thu 4:15pm · Dr Rao", pill: "Confirmed" },
  },
  {
    key: "hiring",
    channel: "WhatsApp",
    role: "First-round screener",
    clock: "02:18",
    transcript: [
      { who: "agent", line: "Hi Priya — quick chat about the site engineer role?" },
      { who: "caller", line: "Sure. What's the salary?" },
      { who: "agent", line: "The band is 12–18 LPA depending on experience. Does that work?" },
      { who: "caller", line: "Works for me. I have 6 years on metro projects." },
    ],
    outcome: { icon: UserSearch, text: "Screened · 6 yrs · notice 30 days", pill: "Shortlisted" },
  },
  {
    key: "salon",
    channel: "WhatsApp",
    role: "Salon booking assistant",
    clock: "01:05",
    transcript: [
      { who: "caller", line: "Can I get a cut and colour with Aisha on Saturday?" },
      { who: "agent", line: "Aisha has 10:30am — that's two hours for both. Shall I hold it?" },
      { who: "caller", line: "Yes please 🙌" },
      { who: "agent", line: "Held and booked. I'll remind you Friday evening." },
    ],
    outcome: { icon: CalendarCheck, text: "Booked · Sat 10:30am · Aisha", pill: "Reminder set" },
  },
  {
    key: "property",
    channel: "Web chat",
    role: "Property enquiry agent",
    clock: "00:57",
    transcript: [
      { who: "caller", line: "Is the 2BHK in Wakad still available?" },
      { who: "agent", line: "It is — ₹78L, east-facing, ready to move. Want to see it this weekend?" },
      { who: "caller", line: "Saturday morning works." },
      { who: "agent", line: "Viewing set for 11am. Sending you the location and the floor plan." },
    ],
    outcome: { icon: Home, text: "Viewing · Sat 11am · Wakad 2BHK", pill: "Lead qualified" },
  },
  {
    key: "lab",
    channel: "Live call",
    role: "Diagnostic lab front desk",
    clock: "01:31",
    transcript: [
      { who: "caller", line: "I need to move my blood test from tomorrow." },
      { who: "agent", line: "No problem — I have Monday 8am or Tuesday 7:30am, both fasting slots." },
      { who: "caller", line: "Monday." },
      { who: "agent", line: "Moved to Monday 8am. Remember: no food after 10pm Sunday." },
    ],
    outcome: { icon: Clock, text: "Moved · Mon 8:00am · fasting", pill: "Confirmed" },
  },
];

/** How long each scene holds. Long enough to read four short lines without
 * hurrying, short enough that a visitor who lingers sees more than two. */
const SCENE_MS = 5200;

/* ── Runtime panel ───────────────────────────────────────────────────────
   The reference's interactive configuration block. Here it shows the shape of
   a real agent, because "what do I actually configure?" is the question this
   part of the page exists to answer. */

const RUNTIME_TABS: {
  key: string;
  label: string;
  rows: { k: string; v: string }[];
  transcript: { who: "agent" | "caller"; line: string }[];
}[] = [
  {
    key: "dental",
    label: "Dental clinic",
    rows: [
      { k: "Role", v: "Front-desk receptionist" },
      { k: "Channels", v: "Phone · WhatsApp · Web chat" },
      { k: "Knows", v: "Treatment list, prices, insurers, policies" },
      { k: "Can do", v: "Book · Reschedule · Cancel · Send reminders" },
      { k: "Escalates", v: "Clinical questions → the practice manager" },
    ],
    transcript: [
      { who: "caller", line: "Hi, do you have anything for a cleaning this week?" },
      { who: "agent", line: "We do — Thursday at 4:15pm or Friday at 11am with Dr Rao. Which suits?" },
      { who: "caller", line: "Thursday please." },
      { who: "agent", line: "Booked. You'll get a confirmation on WhatsApp in a moment." },
    ],
  },
  {
    key: "clinic",
    label: "Recruitment",
    rows: [
      { k: "Role", v: "First-round screener" },
      { k: "Channels", v: "Phone · WhatsApp" },
      { k: "Knows", v: "Open roles, salary bands, visa terms" },
      { k: "Can do", v: "Screen · Score · Book the hiring manager" },
      { k: "Escalates", v: "Offer negotiation → the recruiter" },
    ],
    transcript: [
      { who: "agent", line: "Hi Priya — is now still a good time for a quick chat about the site engineer role?" },
      { who: "caller", line: "Yes. What's the salary?" },
      { who: "agent", line: "The band is 12–18 LPA depending on experience. Does that work for you?" },
      { who: "caller", line: "That works." },
    ],
  },
  {
    key: "salon",
    label: "Salon & spa",
    rows: [
      { k: "Role", v: "Booking assistant" },
      { k: "Channels", v: "WhatsApp · Web chat" },
      { k: "Knows", v: "Service menu, durations, stylist skills" },
      { k: "Can do", v: "Book by stylist · Upsell · Send reminders" },
      { k: "Escalates", v: "Complaints → the owner" },
    ],
    transcript: [
      { who: "caller", line: "Can I get a cut and colour with Aisha on Saturday?" },
      { who: "agent", line: "Aisha has 10:30am — that's two hours for both. Shall I hold it?" },
      { who: "caller", line: "Yes please" },
      { who: "agent", line: "Held and booked. Reminder the day before." },
    ],
  },
];

/* ── Products ────────────────────────────────────────────────────────────*/

const PRODUCTS: { icon: typeof Bot; title: string; body: string; to: string }[] = [
  {
    icon: Bot,
    title: "Voice AI Assistants",
    body: "Build the agent, give it your documents, test it on a call, put it on a number.",
    to: "/assistants",
  },
  {
    icon: MessageCircle,
    title: "WhatsApp Agent",
    body: "Link a number by QR, answer automatically, and work the inbox as a team.",
    to: "/channels",
  },
  {
    icon: UserSearch,
    title: "Hiring Agent",
    body: "Screens candidates end to end and writes up every interview for you.",
    to: "/hiring-agent",
  },
  {
    icon: Mic,
    title: "Voice Cloning",
    body: "Put your own voice on every outbound call your agents make.",
    to: "/clone-voice",
  },
];

const RESOURCES: { icon: typeof Bot; title: string; body: string; to: string }[] = [
  { icon: BookOpen, title: "Knowledge base", body: "Everything your agents can read, in one library.", to: "/knowledge" },
  { icon: CalendarCheck, title: "Scheduling", body: "Services, staff, locations and opening hours.", to: "/appointments" },
  { icon: LineChart, title: "Analytics", body: "Every call, every answer, and what it cost.", to: "/analytics" },
  { icon: Plug, title: "Integrations", body: "Your calendar, your CRM, your webhook.", to: "/integrations" },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "How long does it take to get an agent answering?",
    a: "An afternoon. Create the assistant, upload the documents it should answer from, add your services and opening hours, and test it on a web call. Putting it on a real phone number or a WhatsApp number is the last step, not the first.",
  },
  {
    q: "Will it make things up?",
    a: "It is built not to. Answers about your business come only from the documents you upload, and appointment times come only from your live calendar — the agent cannot offer a slot it has not checked. When something is missing it says so and tells the caller who can confirm, rather than guessing.",
  },
  {
    q: "What happens when it cannot help?",
    a: "It hands over. You set what counts as out of scope, and the agent redirects to a person instead of improvising. In the shared inbox you can also take any conversation over mid-thread and hand it back when you are done.",
  },
  {
    q: "Can it use my own voice?",
    a: "Yes. Clone your voice once and every outbound call your agents make can use it. If you would rather not, there is a library of voices in a range of languages and accents.",
  },
  {
    q: "Which channels does it work on?",
    a: "Phone calls in and out, WhatsApp, web chat on your own site, and an embeddable widget. The same agent, the same knowledge, and one conversation history per person across all of them.",
  },
  {
    q: "Does it connect to the calendar we already use?",
    a: "Yes — the agent reads and writes real availability rather than keeping its own copy, so a slot someone books by phone is gone from your calendar immediately and vice versa.",
  },
  {
    q: "Who can see the conversations?",
    a: "Your workspace, and nobody else's. Every record is scoped to your tenant in the database itself, not just in the application, and your documents are never used to train a shared model.",
  },
  {
    q: "What does it cost?",
    a: "A flat monthly platform fee plus usage — you are billed for the minutes and messages your agents actually handle, with a per-workspace daily cap you set so a runaway campaign cannot surprise you.",
  },
];

/* ────────────────────────────────────────────────────────────────────────── */

/** Whether this visitor has asked for less movement.
 *
 * Read live rather than once: the setting can change while the page is open
 * (it follows the OS on every platform that offers it), and a hero that keeps
 * animating after someone turns it off is worse than one that never moved. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

function Nav() {
  const { isAuthenticated } = useAuth();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-colors duration-200 ${
        scrolled ? "mk-rule bg-white/90 backdrop-blur-md" : "border-transparent bg-white"
      }`}
    >
      <div className="mk-section flex h-[72px] items-center gap-8">
        <Link to="/" className="flex flex-shrink-0 items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[rgb(var(--m-ink))]">
            <Bot className="h-[18px] w-[18px] text-white" strokeWidth={2} />
          </span>
          <span className="font-display text-[17px] font-bold tracking-tight">Evara AI</span>
        </Link>

        <nav className="hidden items-center gap-7 lg:flex">
          {[
            ["Product", "#capabilities"],
            ["How it works", "#runtime"],
            ["Pricing", "#pricing"],
            ["FAQ", "#faq"],
          ].map(([label, href]) => (
            <a
              key={label}
              href={href}
              className="text-[14px] font-medium text-[rgb(var(--m-ink-2))] transition-colors hover:text-[rgb(var(--m-ink))]"
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          <Link
            to={isAuthenticated ? "/dashboard" : "/login"}
            className="hidden text-[13px] font-semibold text-[rgb(var(--m-ink))] hover:underline sm:block"
          >
            {isAuthenticated ? "Dashboard" : "Log in"}
          </Link>
          <Link to="/register" className="mk-btn mk-btn-primary !px-5 !py-2.5">
            Start building
          </Link>
        </div>
      </div>
    </header>
  );
}

/**
 * The hero's product visual: a conversation completing, in the product's own
 * chrome, cycling through five roles.
 *
 * Built rather than screenshotted. Five screenshots would be five files to
 * re-cut on every UI change, they would go stale silently, and they could not
 * animate — where this is the same tokens as the console and stays true by
 * construction.
 *
 * Rotation is paused on hover and on focus: someone who has stopped to read is
 * the one visitor this must not interrupt. It also holds still entirely for
 * `prefers-reduced-motion`, where a panel that rewrites itself every five
 * seconds is the exact thing that setting is asking us not to do.
 */
function HeroPanel() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduceMotion = usePrefersReducedMotion();
  const scene = HERO_SCENES[index];
  const Outcome = scene.outcome.icon;

  useEffect(() => {
    if (paused || reduceMotion) return;
    const timer = setInterval(
      () => setIndex((i) => (i + 1) % HERO_SCENES.length),
      SCENE_MS,
    );
    return () => clearInterval(timer);
  }, [paused, reduceMotion]);

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
    >
      <div className="mk-card overflow-hidden !p-0 shadow-[0_24px_60px_-24px_rgba(11,11,12,0.28)]">
        <div className="flex items-center gap-2.5 border-b mk-rule px-5 py-3.5">
          <span className="relative flex h-2 w-2 flex-shrink-0">
            {!reduceMotion && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[rgb(var(--m-accent))] opacity-70" />
            )}
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[rgb(var(--m-accent))]" />
          </span>
          <span key={`${scene.key}-head`} className="animate-fade-in text-[13px] font-semibold">
            {scene.channel} · {scene.role}
          </span>
          <span className="ml-auto font-mono text-[12px] tabular-nums text-[rgb(var(--m-ink-3))]">
            {scene.clock}
          </span>
        </div>

        {/* A floor under the transcript, so a three-line scene followed by a
            four-line one does not make the whole hero jump. */}
        <div className="min-h-[300px] space-y-3.5 p-5">
          {scene.transcript.map((t, i) => (
            <div
              // Keyed on the scene as well as the position: without the scene
              // in the key React reuses the node and the entrance never
              // replays, so every scene after the first would appear at once.
              key={`${scene.key}-${i}`}
              className={`flex ${t.who === "caller" ? "justify-start" : "justify-end"} ${
                reduceMotion ? "" : "animate-slide-up"
              }`}
              // Staggered so it reads as a conversation arriving rather than a
              // block of text being swapped in.
              style={reduceMotion ? undefined : { animationDelay: `${i * 90}ms`, animationFillMode: "backwards" }}
            >
              <div
                className={`max-w-[86%] rounded-2xl px-4 py-2.5 text-[14.5px] leading-relaxed ${
                  t.who === "caller"
                    ? "rounded-bl-sm bg-[rgb(var(--m-bg-alt))] text-[rgb(var(--m-ink))]"
                    : "rounded-br-sm bg-[rgb(var(--m-ink))] text-white"
                }`}
              >
                {t.line}
              </div>
            </div>
          ))}
        </div>

        <div
          key={`${scene.key}-foot`}
          className="flex items-center gap-2.5 border-t mk-rule bg-[rgb(var(--m-bg-alt))] px-5 py-4 animate-fade-in"
        >
          <Outcome className="h-[18px] w-[18px] flex-shrink-0 text-[rgb(var(--m-accent-ink))]" strokeWidth={2.25} />
          <span className="truncate text-[13.5px] font-semibold">{scene.outcome.text}</span>
          <span className="mk-pill ml-auto flex-shrink-0">{scene.outcome.pill}</span>
        </div>
      </div>

      {/* Jump straight to a scene. Real buttons rather than dots-as-decoration:
          a visitor in the recruitment business should be able to go and look at
          the recruitment one instead of waiting twenty seconds for it. */}
      <div className="mt-4 flex items-center justify-center gap-2">
        {HERO_SCENES.map((sc, i) => (
          <button
            key={sc.key}
            type="button"
            onClick={() => setIndex(i)}
            aria-label={`Show the ${sc.role} example`}
            aria-current={i === index}
            className={`h-1.5 rounded-full transition-all duration-300 ${
              i === index
                ? "w-7 bg-[rgb(var(--m-ink))]"
                : "w-1.5 bg-[rgb(var(--m-ink))]/20 hover:bg-[rgb(var(--m-ink))]/40"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

function RuntimePanel() {
  const [active, setActive] = useState(0);
  const tab = RUNTIME_TABS[active];

  return (
    <div className="mk-card !p-0">
      <div className="flex flex-wrap gap-1 border-b mk-rule p-2">
        {RUNTIME_TABS.map((t, i) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActive(i)}
            aria-pressed={i === active}
            className={`rounded-lg px-3.5 py-2 text-[13px] font-semibold transition-colors ${
              i === active
                ? "bg-[rgb(var(--m-ink))] text-white"
                : "text-[rgb(var(--m-ink-2))] hover:bg-[rgb(var(--m-bg-alt))]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="grid gap-0 md:grid-cols-2">
        <dl className="divide-y divide-[rgb(var(--m-rule))] p-2">
          {tab.rows.map((r) => (
            <div key={r.k} className="flex items-baseline gap-4 px-3 py-3">
              <dt className="w-[92px] flex-shrink-0 text-[12px] font-semibold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
                {r.k}
              </dt>
              <dd className="text-[13.5px] font-medium text-[rgb(var(--m-ink))]">{r.v}</dd>
            </div>
          ))}
        </dl>

        <div className="space-y-2.5 border-t mk-rule bg-[rgb(var(--m-bg-alt))] p-5 md:border-l md:border-t-0">
          {tab.transcript.map((t, i) => (
            <div key={i} className={`flex ${t.who === "caller" ? "justify-start" : "justify-end"}`}>
              <div
                className={`max-w-[88%] rounded-2xl px-3.5 py-2 text-[13px] leading-snug ${
                  t.who === "caller"
                    ? "rounded-bl-sm bg-white text-[rgb(var(--m-ink))]"
                    : "rounded-br-sm bg-[rgb(var(--m-ink))] text-white"
                }`}
              >
                {t.line}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b mk-rule">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-4 py-5 text-left"
      >
        <span className="mk-h3 flex-1 !text-[17px]">{q}</span>
        {open ? (
          <Minus className="h-4 w-4 flex-shrink-0 text-[rgb(var(--m-ink-3))]" strokeWidth={2.5} />
        ) : (
          <Plus className="h-4 w-4 flex-shrink-0 text-[rgb(var(--m-ink-3))]" strokeWidth={2.5} />
        )}
      </button>
      {open && <p className="mk-body max-w-[70ch] pb-5 pr-8">{a}</p>}
    </div>
  );
}

export default function LandingPage() {
  return (
    // The console themes with `data-theme`; the marketing site does not.
    // Scoping the palette to this wrapper is what keeps a visitor in dark mode
    // from getting a half-inverted landing page.
    <div className="marketing min-h-screen">
      <Nav />

      {/* ── Hero ──
          Wider than the rest of the page and top-aligned, both for the same
          reason: the headline is six lines of 4.5rem type, and a panel centred
          against a column that tall floats in the middle looking like an
          afterthought. Aligning the tops makes the pairing deliberate, and the
          extra width buys the headline shorter lines and the panel a bigger
          frame at the same time. */}
      <section className="mx-auto grid w-full max-w-[1340px] items-center gap-12 px-6 py-16 lg:grid-cols-[1.06fr_1fr] lg:items-start lg:gap-16 lg:py-20">
        <div>
          <span className="mk-pill">
            <Sparkles className="h-3.5 w-3.5" strokeWidth={2.5} />
            Voice · WhatsApp · Chat
          </span>
          <h1 className="mk-display mt-5">{HERO_HEADLINE}</h1>
          <p className="mk-lead mt-6 max-w-[54ch]">{HERO_SUB}</p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link to="/register" className="mk-btn mk-btn-primary">
              Start building for free
              <ArrowRight className="h-4 w-4" strokeWidth={2.5} />
            </Link>
            <a href="#runtime" className="mk-btn mk-btn-secondary">
              See it work
            </a>
          </div>
          <p className="mt-4 text-[13px] text-[rgb(var(--m-ink-3))]">
            No card required · Your first agent answering the same day
          </p>
        </div>
        <div className="lg:pt-1">
          <HeroPanel />
        </div>
      </section>

      {/* ── Proof metrics ── */}
      <section className="border-y mk-rule mk-band">
        <div className="mk-section grid gap-8 py-10 sm:grid-cols-3">
          {PROOF.map((p) => (
            <div key={p.label}>
              <p className="font-display text-[2rem] font-bold leading-none tracking-tight">
                {p.value}
              </p>
              <p className="mk-body mt-2 !text-[13.5px]">{p.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Who it is for ── */}
      <section className="mk-section py-14">
        <p className="text-center text-[12.5px] font-semibold uppercase tracking-[0.14em] text-[rgb(var(--m-ink-3))]">
          Running the front desk for
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-4">
          {[
            "Dental clinics", "Salons & spas", "Diagnostic labs", "Recruitment",
            "Real estate", "Home services",
          ].map((s) => (
            <span key={s} className="font-display text-[17px] font-semibold text-[rgb(var(--m-ink-3))]">
              {s}
            </span>
          ))}
        </div>
      </section>

      {/* ── Why us ── */}
      <section className="mk-section py-16">
        <p className="mk-eyebrow">Why Evara</p>
        <h2 className="mk-h2 mt-3 max-w-[20ch]">Built to finish the job, not to sound like it did.</h2>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {WHY.map((w) => {
            const Icon = w.icon;
            return (
              <div key={w.title} className="mk-card mk-card-hover">
                <span className="mk-chip">
                  <Icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="mk-h3 mt-4">{w.title}</h3>
                <p className="mk-body mt-2">{w.body}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Capabilities ── */}
      <section id="capabilities" className="border-y mk-rule mk-band">
        <div className="mk-section py-16">
          <p className="mk-eyebrow">What the agent does</p>
          <h2 className="mk-h2 mt-3 max-w-[22ch]">One teammate, on every channel you already run.</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {CAPABILITIES.map((c) => {
              const Icon = c.icon;
              return (
                <div key={c.title} className="mk-card mk-card-hover">
                  <div className="flex items-start justify-between gap-3">
                    <span className="mk-chip">
                      <Icon className="h-5 w-5" strokeWidth={2} />
                    </span>
                    {c.soon && (
                      <span className="rounded-full border mk-rule px-2 py-0.5 text-[10.5px]
                                       font-bold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
                        Coming soon
                      </span>
                    )}
                  </div>
                  <h3 className="mk-h3 mt-4">{c.title}</h3>
                  <p className="mk-body mt-2">{c.body}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Runtime ── */}
      <section id="runtime" className="mk-section py-16">
        <p className="mk-eyebrow">How it works</p>
        <h2 className="mk-h2 mt-3 max-w-[24ch]">You describe the role. It shows up for the shift.</h2>
        <p className="mk-lead mt-4 max-w-[62ch]">
          An agent is a role description, a set of documents, and the things it is allowed
          to do. Pick a starting point and change it in plain sentences — there is no prompt
          to engineer and nothing to redeploy.
        </p>
        <div className="mt-10">
          <RuntimePanel />
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="border-y mk-rule mk-band">
        <div className="mk-section grid gap-10 py-16 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="mk-eyebrow">Pricing</p>
            <h2 className="mk-h2 mt-3">Pay for the conversations you actually handle.</h2>
            <p className="mk-lead mt-4 max-w-[46ch]">
              A flat platform fee, then usage. Set a daily cap per workspace so a campaign
              that runs away cannot surprise you at the end of the month.
            </p>
            <Link to="/register" className="mk-btn mk-btn-primary mt-7">
              Start free
              <ArrowRight className="h-4 w-4" strokeWidth={2.5} />
            </Link>
          </div>
          <div className="mk-card">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-display text-[2.6rem] font-bold leading-none tracking-tight">
                Usage-based
              </span>
              <span className="mk-pill">Free while you build</span>
            </div>
            <p className="mk-body mt-3">
              Build, test and tune as many agents as you like before a single one goes live.
              Billing starts when real calls and messages do.
            </p>
            <ul className="mt-6 space-y-2.5">
              {[
                "Unlimited agents and knowledge documents",
                "Voice, WhatsApp, web chat and the embeddable widget",
                "Real-calendar booking, rescheduling and reminders",
                "Shared team inbox with takeover and assignment",
                "Your own cloned voice on outbound calls",
                "A daily spend cap you control",
              ].map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-[14px]">
                  <Check
                    className="mt-0.5 h-4 w-4 flex-shrink-0 text-[rgb(var(--m-accent-ink))]"
                    strokeWidth={2.75}
                  />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ── Testimonial ── */}
      <section className="mk-section py-16">
        <figure className="mx-auto max-w-[52rem] text-center">
          <blockquote className="mk-h2 !font-medium">
            “We were losing bookings every evening because nobody was there to pick up.
            The agent answers, checks the diary, and books them in. Our
            <span className="text-[rgb(var(--m-accent-ink))]"> after-hours bookings went from zero</span>
            {" "}to a third of the week.”
          </blockquote>
          <figcaption className="mk-body mt-6 !text-[13.5px]">
            Practice manager · multi-site dental group
          </figcaption>
        </figure>
      </section>

      {/* ── Products ── */}
      <section className="border-y mk-rule mk-band">
        <div className="mk-section py-16">
          <p className="mk-eyebrow">The platform</p>
          <h2 className="mk-h2 mt-3">Everything you need to run agents in production.</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {PRODUCTS.map((p) => {
              const Icon = p.icon;
              return (
                <Link key={p.title} to={p.to} className="mk-card mk-card-hover group block">
                  <span className="mk-chip">
                    <Icon className="h-5 w-5" strokeWidth={2} />
                  </span>
                  <h3 className="mk-h3 mt-4 !text-[16px]">{p.title}</h3>
                  <p className="mk-body mt-2 !text-[13.5px]">{p.body}</p>
                  <span className="mt-4 inline-flex items-center gap-1.5 text-[12.5px] font-bold uppercase tracking-wider text-[rgb(var(--m-accent-ink))]">
                    Explore
                    <ArrowRight
                      className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
                      strokeWidth={2.75}
                    />
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Resources ── */}
      <section className="mk-section py-16">
        <p className="mk-eyebrow">Also in the box</p>
        <h2 className="mk-h2 mt-3">The unglamorous parts, already built.</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {RESOURCES.map((r) => {
            const Icon = r.icon;
            return (
              <Link key={r.title} to={r.to} className="mk-card mk-card-hover block">
                <span className="mk-chip">
                  <Icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="mk-h3 mt-4 !text-[16px]">{r.title}</h3>
                <p className="mk-body mt-2 !text-[13.5px]">{r.body}</p>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ── Closing CTA ── */}
      <section className="mk-invert">
        <div className="mk-section grid items-center gap-10 py-20 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <h2 className="mk-h2">Put an agent on your front desk this week.</h2>
            <p className="mk-lead mt-4 max-w-[46ch]">
              Build it, give it your documents and your calendar, and hear it answer — before
              you decide whether to point a real number at it.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/register" className="mk-btn mk-btn-primary">
                Start building for free
                <ArrowRight className="h-4 w-4" strokeWidth={2.5} />
              </Link>
              <Link to="/report-issue" className="mk-btn mk-btn-secondary">
                Talk to us
              </Link>
            </div>
          </div>
          <div className="mk-card">
            <p className="mk-eyebrow">What day one looks like</p>
            <ol className="mt-4 space-y-4">
              {[
                ["Describe the role", "In plain sentences. “You are the receptionist for a dental clinic.”"],
                ["Upload what it should know", "Price list, policies, treatment menu, FAQs."],
                ["Add services and opening hours", "So the times it offers are times you can honour."],
                ["Test it on a call", "Then point a phone or WhatsApp number at it."],
              ].map(([title, body], i) => (
                <li key={title} className="flex gap-3.5">
                  <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-[rgb(var(--m-accent))] text-[12px] font-bold text-[rgb(11,11,12)]">
                    {i + 1}
                  </span>
                  <span>
                    <span className="block text-[14px] font-semibold">{title}</span>
                    <span className="mk-body !text-[13px]">{body}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section id="faq" className="mk-section py-16">
        <p className="mk-eyebrow">FAQ</p>
        <h2 className="mk-h2 mt-3">Questions people ask before they start.</h2>
        <div className="mt-8 border-t mk-rule">
          {FAQ.map((f) => (
            <FaqItem key={f.q} q={f.q} a={f.a} />
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t mk-rule">
        <div className="mk-section flex flex-wrap items-center gap-4 py-8">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[rgb(var(--m-ink))]">
              <Bot className="h-4 w-4 text-white" strokeWidth={2} />
            </span>
            <span className="font-display text-[15px] font-bold tracking-tight">Evara AI</span>
          </Link>
          <p className="mk-body !text-[13px]">
            © {new Date().getFullYear()} Evara AI. Agents that answer, book and follow up.
          </p>
          <div className="ml-auto flex items-center gap-5 text-[13px] font-medium text-[rgb(var(--m-ink-2))]">
            <a href="#capabilities" className="hover:text-[rgb(var(--m-ink))]">Product</a>
            <a href="#pricing" className="hover:text-[rgb(var(--m-ink))]">Pricing</a>
            <Link to="/report-issue" className="hover:text-[rgb(var(--m-ink))]">Support</Link>
            <Link to="/login" className="hover:text-[rgb(var(--m-ink))]">Log in</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
