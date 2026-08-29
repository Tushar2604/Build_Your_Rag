// The shape of every word on the marketing site.
//
// One interface rather than flat dotted keys ("hero.headline"): the compiler
// then tells a translator exactly what is missing, instead of the page
// rendering the key name to a visitor. Every locale file below is typed as
// `LandingCopy`, so a forgotten FAQ answer is a build error rather than a
// support ticket.
//
// Arrays are fixed-length tuples where the layout depends on the count — three
// proof figures sit in a three-column grid, and a locale that supplied four
// would silently break it.

export interface Card {
  title: string;
  body: string;
}

export interface Scene {
  /** "Live call" / "WhatsApp" / "Web chat", in this locale. */
  channel: string;
  role: string;
  transcript: { who: "agent" | "caller"; line: string }[];
  outcome: { text: string; pill: string };
}

export interface LandingCopy {
  nav: {
    product: string;
    howItWorks: string;
    pricing: string;
    faq: string;
    login: string;
    dashboard: string;
    startBuilding: string;
    language: string;
  };
  hero: {
    badge: string;
    headline: string;
    sub: string;
    ctaPrimary: string;
    ctaSecondary: string;
    note: string;
  };
  proof: [Card, Card, Card];
  industries: { label: string; items: string[] };
  why: { eyebrow: string; heading: string; cards: [Card, Card, Card] };
  capabilities: {
    eyebrow: string;
    heading: string;
    soon: string;
    cards: [Card, Card, Card, Card, Card, Card];
  };
  runtime: { eyebrow: string; heading: string; lead: string };
  /** The five rotating hero demos. Localised on purpose: a page claiming the
   * agent speaks your language, demonstrating it in English, is arguing
   * against itself. */
  scenes: [Scene, Scene, Scene, Scene, Scene];
  pricing: {
    eyebrow: string;
    heading: string;
    lead: string;
    cta: string;
    planName: string;
    planBadge: string;
    planBody: string;
    features: string[];
  };
  testimonial: { before: string; highlight: string; after: string; source: string };
  products: { eyebrow: string; heading: string; explore: string; cards: Card[] };
  resources: { eyebrow: string; heading: string; cards: Card[] };
  closing: {
    heading: string;
    lead: string;
    ctaPrimary: string;
    ctaSecondary: string;
    stepsEyebrow: string;
    steps: Card[];
  };
  faq: { eyebrow: string; heading: string; items: { q: string; a: string }[] };
  footer: { rights: string; product: string; pricing: string; support: string; login: string };
}
