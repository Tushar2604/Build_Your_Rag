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
  Plug, Plus, ShieldCheck, Sparkles, UserSearch, Zap, Globe, Check as CheckIcon,
} from "lucide-react";

import { useAuth } from "../store/auth";
import { useLocale } from "../store/locale";
import { LOCALES } from "../i18n";

/* ── Icons ───────────────────────────────────────────────────────────────
   All the copy now lives in `src/i18n`, keyed by locale. What stays here is
   the icon each card wears, because an icon is layout rather than language —
   a phone means the same thing in Hindi. Each list is index-aligned with the
   matching array in `LandingCopy`, which the tuple types there keep honest. */

const WHY_ICONS = [ShieldCheck, Zap, Kanban];
const CAPABILITY_ICONS = [Phone, CalendarCheck, MessageCircle, BookOpen, CreditCard, Megaphone];
/** Only the payment card is unbuilt. Kept as an index rather than a flag in
    the copy so a translator cannot accidentally promote a roadmap item to
    shipped by dropping a field. */
const CAPABILITY_SOON = new Set([4]);
const PRODUCT_ICONS = [Bot, MessageCircle, UserSearch, Mic];
const PRODUCT_LINKS = ["/assistants", "/channels", "/hiring-agent", "/clone-voice"];
const RESOURCE_ICONS = [BookOpen, CalendarCheck, LineChart, Plug];
const RESOURCE_LINKS = ["/knowledge", "/appointments", "/analytics", "/integrations"];
const SCENE_OUTCOME_ICONS = [CalendarCheck, UserSearch, CalendarCheck, Home, Clock];

/** How long each hero scene holds. Long enough to read four short lines
    without hurrying, short enough that a visitor who lingers sees more than
    two. */
const SCENE_MS = 5200;

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

/**
 * The language picker.
 *
 * Every option is written in its own language — someone who cannot read the
 * page as it stands cannot read "Spanish" written in English either, and that
 * is exactly the visitor this control exists for.
 */
function LanguagePicker() {
  const { locale, setLocale, t } = useLocale();
  const [open, setOpen] = useState(false);
  const current = LOCALES.find((l) => l.code === locale) ?? LOCALES[0];

  useEffect(() => {
    if (!open) return;
    // Deferred a tick so the click that opened the menu does not close it.
    const id = window.setTimeout(() => document.addEventListener("click", () => setOpen(false), { once: true }), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t.nav.language}
        className="flex items-center gap-1.5 rounded-[6px] px-2.5 py-2 text-[13px] font-semibold
                   text-[rgb(var(--m-ink-2))] transition-colors hover:text-[rgb(var(--m-ink))]"
      >
        <Globe className="h-4 w-4" strokeWidth={2} />
        <span className="hidden sm:inline">{current.label}</span>
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label={t.nav.language}
          onClick={(e) => e.stopPropagation()}
          className="absolute end-0 top-full z-50 mt-1.5 min-w-[172px] overflow-hidden rounded-xl
                     border bg-[rgb(var(--m-bg))] p-1.5 shadow-[0_16px_40px_-16px_rgba(11,11,12,0.3)] mk-rule"
        >
          {LOCALES.map((l) => (
            <li key={l.code}>
              <button
                type="button"
                role="option"
                aria-selected={l.code === locale}
                lang={l.htmlLang}
                onClick={() => {
                  setLocale(l.code);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-[13.5px]
                            transition-colors hover:bg-[rgb(var(--m-bg-alt))] ${
                              l.code === locale ? "font-semibold" : ""
                            }`}
              >
                <span className="flex-1">{l.label}</span>
                {l.code === locale && (
                  <CheckIcon className="h-3.5 w-3.5 text-[rgb(var(--m-accent-ink))]" strokeWidth={3} />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Nav() {
  const { isAuthenticated } = useAuth();
  const { t } = useLocale();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const links: [string, string][] = [
    [t.nav.product, "#capabilities"],
    [t.nav.howItWorks, "#runtime"],
    [t.nav.pricing, "#pricing"],
    [t.nav.faq, "#faq"],
  ];

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-colors duration-200 ${
        scrolled ? "mk-rule bg-white/90 backdrop-blur-md" : "border-transparent bg-white"
      }`}
    >
      <div className="mx-auto flex h-[72px] w-full max-w-[1340px] items-center gap-8 px-6">
        <Link to="/" className="flex flex-shrink-0 items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[rgb(var(--m-ink))]">
            <Bot className="h-[18px] w-[18px] text-white" strokeWidth={2} />
          </span>
          <span className="font-display text-[17px] font-bold tracking-tight">Evara AI</span>
        </Link>

        <nav className="hidden items-center gap-7 lg:flex">
          {links.map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="text-[14px] font-medium text-[rgb(var(--m-ink-2))] transition-colors hover:text-[rgb(var(--m-ink))]"
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="ms-auto flex items-center gap-1.5">
          <LanguagePicker />
          <Link
            to={isAuthenticated ? "/dashboard" : "/login"}
            className="hidden px-2 text-[13px] font-semibold text-[rgb(var(--m-ink))] hover:underline sm:block"
          >
            {isAuthenticated ? t.nav.dashboard : t.nav.login}
          </Link>
          <Link to="/register" className="mk-btn mk-btn-primary !px-5 !py-2.5">
            {t.nav.startBuilding}
          </Link>
        </div>
      </div>
    </header>
  );
}

/**
 * The hero's product visual: a conversation completing, in the product's own
 * chrome, cycling through five roles — and, now, five languages' worth of
 * transcript.
 *
 * Built rather than screenshotted. Five screenshots would be five files to
 * re-cut on every UI change, they would go stale silently, they could not
 * animate, and they certainly could not be translated.
 *
 * Rotation pauses on hover and on focus: someone who has stopped to read is
 * the one visitor this must not interrupt. It also holds still entirely for
 * `prefers-reduced-motion`.
 */
function HeroPanel() {
  const { t, locale } = useLocale();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduceMotion = usePrefersReducedMotion();
  const scene = t.scenes[index];
  const Outcome = SCENE_OUTCOME_ICONS[index];

  // Switching language re-reads the transcripts underneath us. Restarting at
  // the first scene keeps the entrance animation honest and avoids a frame
  // where half the panel is still in the previous language.
  useEffect(() => setIndex(0), [locale]);

  useEffect(() => {
    if (paused || reduceMotion) return;
    const timer = setInterval(() => setIndex((i) => (i + 1) % t.scenes.length), SCENE_MS);
    return () => clearInterval(timer);
  }, [paused, reduceMotion, t.scenes.length]);

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
          <span key={`${locale}-${index}-head`} className="animate-fade-in text-[13px] font-semibold">
            {scene.channel} · {scene.role}
          </span>
          <span className="ms-auto font-mono text-[12px] tabular-nums text-[rgb(var(--m-ink-3))]">
            {["00:42", "02:18", "01:05", "00:57", "01:31"][index]}
          </span>
        </div>

        {/* A floor under the transcript, so a scene whose lines wrap differently
            in another language does not make the whole hero jump. Generous
            because translations run longer than English — German and Hindi
            both add roughly a third. */}
        <div className="min-h-[320px] space-y-3.5 p-5">
          {scene.transcript.map((line, i) => (
            <div
              // Keyed on the locale and the scene as well as the position:
              // without them React reuses the node and the entrance never
              // replays, so a switch would appear all at once.
              key={`${locale}-${index}-${i}`}
              className={`flex ${line.who === "caller" ? "justify-start" : "justify-end"} ${
                reduceMotion ? "" : "animate-slide-up"
              }`}
              style={
                reduceMotion
                  ? undefined
                  : { animationDelay: `${i * 90}ms`, animationFillMode: "backwards" }
              }
            >
              <div
                className={`max-w-[86%] rounded-2xl px-4 py-2.5 text-[14.5px] leading-relaxed ${
                  line.who === "caller"
                    ? "rounded-es-sm bg-[rgb(var(--m-bg-alt))] text-[rgb(var(--m-ink))]"
                    : "rounded-ee-sm bg-[rgb(var(--m-ink))] text-white"
                }`}
              >
                {line.line}
              </div>
            </div>
          ))}
        </div>

        <div
          key={`${locale}-${index}-foot`}
          className="flex animate-fade-in items-center gap-2.5 border-t mk-rule bg-[rgb(var(--m-bg-alt))] px-5 py-4"
        >
          <Outcome className="h-[18px] w-[18px] flex-shrink-0 text-[rgb(var(--m-accent-ink))]" strokeWidth={2.25} />
          <span className="truncate text-[13.5px] font-semibold">{scene.outcome.text}</span>
          <span className="mk-pill ms-auto flex-shrink-0">{scene.outcome.pill}</span>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-center gap-2">
        {t.scenes.map((sc, i) => (
          <button
            key={sc.role}
            type="button"
            onClick={() => setIndex(i)}
            aria-label={sc.role}
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

/** The "how it works" panel: an agent's configuration beside a real exchange.
 * Reuses the hero's scenes rather than carrying its own, so a translator has
 * one set of transcripts to get right instead of two. */
function RuntimePanel() {
  const { t, locale } = useLocale();
  const [active, setActive] = useState(0);
  useEffect(() => setActive(0), [locale]);
  const scene = t.scenes[active];

  return (
    <div className="mk-card !p-0">
      <div className="flex flex-wrap gap-1 border-b mk-rule p-2">
        {t.scenes.map((sc, i) => (
          <button
            key={sc.role}
            type="button"
            onClick={() => setActive(i)}
            aria-pressed={i === active}
            className={`rounded-lg px-3.5 py-2 text-[13px] font-semibold transition-colors ${
              i === active
                ? "bg-[rgb(var(--m-ink))] text-white"
                : "text-[rgb(var(--m-ink-2))] hover:bg-[rgb(var(--m-bg-alt))]"
            }`}
          >
            {sc.role}
          </button>
        ))}
      </div>

      <div className="grid gap-0 md:grid-cols-2">
        <dl className="divide-y divide-[rgb(var(--m-rule))] p-2">
          <div className="flex items-baseline gap-4 px-3 py-3">
            <dt className="w-[92px] flex-shrink-0 text-[12px] font-semibold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
              {t.nav.product}
            </dt>
            <dd className="text-[13.5px] font-medium">{scene.role}</dd>
          </div>
          <div className="flex items-baseline gap-4 px-3 py-3">
            <dt className="w-[92px] flex-shrink-0 text-[12px] font-semibold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
              {t.hero.badge.split("·")[0].trim()}
            </dt>
            <dd className="text-[13.5px] font-medium">{scene.channel}</dd>
          </div>
          <div className="flex items-baseline gap-4 px-3 py-3">
            <dt className="w-[92px] flex-shrink-0 text-[12px] font-semibold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
              {scene.outcome.pill}
            </dt>
            <dd className="text-[13.5px] font-medium">{scene.outcome.text}</dd>
          </div>
        </dl>

        <div className="space-y-2.5 border-t mk-rule bg-[rgb(var(--m-bg-alt))] p-5 md:border-s md:border-t-0">
          {scene.transcript.map((line, i) => (
            <div
              key={`${locale}-${active}-${i}`}
              className={`flex ${line.who === "caller" ? "justify-start" : "justify-end"}`}
            >
              <div
                className={`max-w-[88%] rounded-2xl px-3.5 py-2 text-[13px] leading-snug ${
                  line.who === "caller"
                    ? "rounded-es-sm bg-white text-[rgb(var(--m-ink))]"
                    : "rounded-ee-sm bg-[rgb(var(--m-ink))] text-white"
                }`}
              >
                {line.line}
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
        className="flex w-full items-center gap-4 py-5 text-start"
      >
        <span className="mk-h3 flex-1 !text-[17px]">{q}</span>
        {open ? (
          <Minus className="h-4 w-4 flex-shrink-0 text-[rgb(var(--m-ink-3))]" strokeWidth={2.5} />
        ) : (
          <Plus className="h-4 w-4 flex-shrink-0 text-[rgb(var(--m-ink-3))]" strokeWidth={2.5} />
        )}
      </button>
      {open && <p className="mk-body max-w-[70ch] pb-5 pe-8">{a}</p>}
    </div>
  );
}

export default function LandingPage() {
  const { t, dir } = useLocale();
  // Arrows point the way the language reads. In a right-to-left locale a
  // "continue" arrow aimed right points backwards.
  const Forward = (props: { className?: string; strokeWidth?: number }) => (
    <ArrowRight {...props} className={`${props.className ?? ""} ${dir === "rtl" ? "-scale-x-100" : ""}`} />
  );

  return (
    // The console themes with `data-theme`; the marketing site does not.
    // Scoping the palette to this wrapper is what keeps a visitor in dark mode
    // from getting a half-inverted landing page.
    <div className="marketing min-h-screen">
      <Nav />

      {/* ── Hero ── */}
      <section className="mx-auto grid w-full max-w-[1340px] items-center gap-12 px-6 py-16 lg:grid-cols-[1.06fr_1fr] lg:items-start lg:gap-16 lg:py-20">
        <div>
          <span className="mk-pill">
            <Sparkles className="h-3.5 w-3.5" strokeWidth={2.5} />
            {t.hero.badge}
          </span>
          <h1 className="mk-display mt-5">{t.hero.headline}</h1>
          <p className="mk-lead mt-6 max-w-[54ch]">{t.hero.sub}</p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link to="/register" className="mk-btn mk-btn-primary">
              {t.hero.ctaPrimary}
              <Forward className="h-4 w-4" strokeWidth={2.5} />
            </Link>
            <a href="#runtime" className="mk-btn mk-btn-secondary">
              {t.hero.ctaSecondary}
            </a>
          </div>
          <p className="mt-4 text-[13px] text-[rgb(var(--m-ink-3))]">{t.hero.note}</p>
        </div>
        <div className="lg:pt-1">
          <HeroPanel />
        </div>
      </section>

      {/* ── Proof metrics ── */}
      <section className="border-y mk-rule mk-band">
        <div className="mk-section grid gap-8 py-10 sm:grid-cols-3">
          {t.proof.map((p) => (
            <div key={p.title}>
              <p className="font-display text-[2rem] font-bold leading-none tracking-tight">
                {p.title}
              </p>
              <p className="mk-body mt-2 !text-[13.5px]">{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Who it is for ── */}
      <section className="mk-section py-14">
        <p className="text-center text-[12.5px] font-semibold uppercase tracking-[0.14em] text-[rgb(var(--m-ink-3))]">
          {t.industries.label}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-4">
          {t.industries.items.map((s) => (
            <span key={s} className="font-display text-[17px] font-semibold text-[rgb(var(--m-ink-3))]">
              {s}
            </span>
          ))}
        </div>
      </section>

      {/* ── Why us ── */}
      <section className="mk-section py-16">
        <p className="mk-eyebrow">{t.why.eyebrow}</p>
        <h2 className="mk-h2 mt-3 max-w-[20ch]">{t.why.heading}</h2>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {t.why.cards.map((c, i) => {
            const Icon = WHY_ICONS[i];
            return (
              <div key={c.title} className="mk-card mk-card-hover">
                <span className="mk-chip">
                  <Icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="mk-h3 mt-4">{c.title}</h3>
                <p className="mk-body mt-2">{c.body}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Capabilities ── */}
      <section id="capabilities" className="border-y mk-rule mk-band">
        <div className="mk-section py-16">
          <p className="mk-eyebrow">{t.capabilities.eyebrow}</p>
          <h2 className="mk-h2 mt-3 max-w-[22ch]">{t.capabilities.heading}</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {t.capabilities.cards.map((c, i) => {
              const Icon = CAPABILITY_ICONS[i];
              return (
                <div key={c.title} className="mk-card mk-card-hover">
                  <div className="flex items-start justify-between gap-3">
                    <span className="mk-chip">
                      <Icon className="h-5 w-5" strokeWidth={2} />
                    </span>
                    {CAPABILITY_SOON.has(i) && (
                      <span className="rounded-full border mk-rule px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-[rgb(var(--m-ink-3))]">
                        {t.capabilities.soon}
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
        <p className="mk-eyebrow">{t.runtime.eyebrow}</p>
        <h2 className="mk-h2 mt-3 max-w-[24ch]">{t.runtime.heading}</h2>
        <p className="mk-lead mt-4 max-w-[62ch]">{t.runtime.lead}</p>
        <div className="mt-10">
          <RuntimePanel />
        </div>
      </section>

      {/* ── Pricing ── */}
      <section id="pricing" className="border-y mk-rule mk-band">
        <div className="mk-section grid gap-10 py-16 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="mk-eyebrow">{t.pricing.eyebrow}</p>
            <h2 className="mk-h2 mt-3">{t.pricing.heading}</h2>
            <p className="mk-lead mt-4 max-w-[46ch]">{t.pricing.lead}</p>
            <Link to="/register" className="mk-btn mk-btn-primary mt-7">
              {t.pricing.cta}
              <Forward className="h-4 w-4" strokeWidth={2.5} />
            </Link>
          </div>
          <div className="mk-card">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-display text-[2.6rem] font-bold leading-none tracking-tight">
                {t.pricing.planName}
              </span>
              <span className="mk-pill">{t.pricing.planBadge}</span>
            </div>
            <p className="mk-body mt-3">{t.pricing.planBody}</p>
            <ul className="mt-6 space-y-2.5">
              {t.pricing.features.map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-[14px]">
                  <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-[rgb(var(--m-accent-ink))]" strokeWidth={2.75} />
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
            “{t.testimonial.before}
            <span className="text-[rgb(var(--m-accent-ink))]">{t.testimonial.highlight}</span>
            {t.testimonial.after}”
          </blockquote>
          <figcaption className="mk-body mt-6 !text-[13.5px]">{t.testimonial.source}</figcaption>
        </figure>
      </section>

      {/* ── Products ── */}
      <section className="border-y mk-rule mk-band">
        <div className="mk-section py-16">
          <p className="mk-eyebrow">{t.products.eyebrow}</p>
          <h2 className="mk-h2 mt-3">{t.products.heading}</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {t.products.cards.map((c, i) => {
              const Icon = PRODUCT_ICONS[i];
              return (
                <Link key={c.title} to={PRODUCT_LINKS[i]} className="mk-card mk-card-hover group block">
                  <span className="mk-chip">
                    <Icon className="h-5 w-5" strokeWidth={2} />
                  </span>
                  <h3 className="mk-h3 mt-4 !text-[16px]">{c.title}</h3>
                  <p className="mk-body mt-2 !text-[13.5px]">{c.body}</p>
                  <span className="mt-4 inline-flex items-center gap-1.5 text-[12.5px] font-bold uppercase tracking-wider text-[rgb(var(--m-accent-ink))]">
                    {t.products.explore}
                    <Forward className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" strokeWidth={2.75} />
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Resources ── */}
      <section className="mk-section py-16">
        <p className="mk-eyebrow">{t.resources.eyebrow}</p>
        <h2 className="mk-h2 mt-3">{t.resources.heading}</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {t.resources.cards.map((c, i) => {
            const Icon = RESOURCE_ICONS[i];
            return (
              <Link key={c.title} to={RESOURCE_LINKS[i]} className="mk-card mk-card-hover block">
                <span className="mk-chip">
                  <Icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="mk-h3 mt-4 !text-[16px]">{c.title}</h3>
                <p className="mk-body mt-2 !text-[13.5px]">{c.body}</p>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ── Closing CTA ── */}
      <section className="mk-invert">
        <div className="mk-section grid items-center gap-10 py-20 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <h2 className="mk-h2">{t.closing.heading}</h2>
            <p className="mk-lead mt-4 max-w-[46ch]">{t.closing.lead}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/register" className="mk-btn mk-btn-primary">
                {t.closing.ctaPrimary}
                <Forward className="h-4 w-4" strokeWidth={2.5} />
              </Link>
              <Link to="/report-issue" className="mk-btn mk-btn-secondary">
                {t.closing.ctaSecondary}
              </Link>
            </div>
          </div>
          <div className="mk-card">
            <p className="mk-eyebrow">{t.closing.stepsEyebrow}</p>
            <ol className="mt-4 space-y-4">
              {t.closing.steps.map((step, i) => (
                <li key={step.title} className="flex gap-3.5">
                  <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-[rgb(var(--m-accent))] text-[12px] font-bold text-[rgb(11,11,12)]">
                    {i + 1}
                  </span>
                  <span>
                    <span className="block text-[14px] font-semibold">{step.title}</span>
                    <span className="mk-body !text-[13px]">{step.body}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section id="faq" className="mk-section py-16">
        <p className="mk-eyebrow">{t.faq.eyebrow}</p>
        <h2 className="mk-h2 mt-3">{t.faq.heading}</h2>
        <div className="mt-8 border-t mk-rule">
          {t.faq.items.map((f) => (
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
            © {new Date().getFullYear()} {t.footer.rights}
          </p>
          <div className="ms-auto flex items-center gap-5 text-[13px] font-medium text-[rgb(var(--m-ink-2))]">
            <a href="#capabilities" className="hover:text-[rgb(var(--m-ink))]">{t.footer.product}</a>
            <a href="#pricing" className="hover:text-[rgb(var(--m-ink))]">{t.footer.pricing}</a>
            <Link to="/report-issue" className="hover:text-[rgb(var(--m-ink))]">{t.footer.support}</Link>
            <Link to="/login" className="hover:text-[rgb(var(--m-ink))]">{t.footer.login}</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
