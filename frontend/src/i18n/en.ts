// English — the source of truth every other locale is translated from.
//
// When copy changes, it changes here first. The other files are typed against
// the same interface, so a new field breaks their build until it is filled in
// rather than silently falling back and shipping half a page in English.
import { LandingCopy } from "./types";

export const en: LandingCopy = {
  nav: {
    product: "Product",
    howItWorks: "How it works",
    pricing: "Pricing",
    faq: "FAQ",
    login: "Log in",
    dashboard: "Dashboard",
    startBuilding: "Start building",
    language: "Language",
  },
  hero: {
    badge: "Voice · WhatsApp · Chat",
    headline: "AI agents that answer, book, and follow up — on every channel you run.",
    sub:
      "Give your front desk a teammate that never misses a call. Evara agents pick up the phone, reply on WhatsApp and chat, check your real calendar, take the booking, and hand you the notes.",
    ctaPrimary: "Start building for free",
    ctaSecondary: "See it work",
    note: "No card required · Your first agent answering the same day",
  },
  proof: [
    { title: "24/7", body: "Never a missed call or a missed message" },
    { title: "4 channels", body: "Phone, WhatsApp, web chat and an embeddable widget" },
    { title: "Zero", body: "Invented prices, dates or slots — every answer is grounded" },
  ],
  industries: {
    label: "Running the front desk for",
    items: [
      "Dental clinics", "Salons & spas", "Diagnostic labs",
      "Recruitment", "Real estate", "Home services",
    ],
  },
  why: {
    eyebrow: "Why Evara",
    heading: "Built to finish the job, not to sound like it did.",
    cards: [
      {
        title: "It never invents an answer",
        body:
          "Every fact comes from your own documents, and every time comes from your real calendar. When an agent does not know something, it says so and tells the caller who will — it does not guess a price or a slot.",
      },
      {
        title: "It actually completes the job",
        body:
          "Not a chatbot that takes a message. The agent checks availability, holds the slot while it takes the details, writes the booking, and sends the confirmation — end to end, while the caller is still on the line.",
      },
      {
        title: "You stay in the driver's seat",
        body:
          "Read every conversation, take one over mid-thread, and change what the agent says by editing plain sentences — no prompt engineering, no redeploy, no waiting on us.",
      },
    ],
  },
  capabilities: {
    eyebrow: "What the agent does",
    heading: "One teammate, on every channel you already run.",
    soon: "Coming soon",
    cards: [
      {
        title: "Answers the phone",
        body:
          "A real voice on an inbound or outbound call, in your own cloned voice if you want one. It handles interruptions, waits while people think, and never talks over them.",
      },
      {
        title: "Books the appointment",
        body:
          "Reads your services, staff and opening hours, offers only times that are genuinely free, holds the slot while it takes the details, and books it. Reschedules and cancellations too.",
      },
      {
        title: "Runs your WhatsApp",
        body:
          "Link your number by QR and the agent answers there. A shared inbox for your team on top: assign a chat, tag it, take it over, and hand it back.",
      },
      {
        title: "Knows your business",
        body:
          "Upload your price list, policies and FAQs. The agent answers from those documents and cites nothing it has not read — the difference between helpful and confidently wrong.",
      },
      {
        title: "Takes the payment",
        body:
          "Will send a deposit or invoice link in the same conversation and confirm the booking once it settles, so a slot is paid for rather than pencilled in.",
      },
      {
        title: "Follows up on its own",
        body:
          "Chases a quiet lead, reminds a patient the day before, and runs a campaign to a list — then stops the moment someone replies and picks the conversation back up.",
      },
    ],
  },
  runtime: {
    eyebrow: "How it works",
    heading: "You describe the role. It shows up for the shift.",
    lead:
      "An agent is a role description, a set of documents, and the things it is allowed to do. Pick a starting point and change it in plain sentences — there is no prompt to engineer and nothing to redeploy.",
  },
  scenes: [
    {
      channel: "Live call",
      role: "Dental clinic receptionist",
      transcript: [
        { who: "caller", line: "Hi, do you have anything for a cleaning this week?" },
        { who: "agent", line: "We do — Thursday at 4:15pm or Friday at 11am with Dr Rao. Which suits?" },
        { who: "caller", line: "Thursday please." },
        { who: "agent", line: "Booked. You'll get a confirmation on WhatsApp in a moment." },
      ],
      outcome: { text: "Booked · Thu 4:15pm · Dr Rao", pill: "Confirmed" },
    },
    {
      channel: "WhatsApp",
      role: "First-round screener",
      transcript: [
        { who: "agent", line: "Hi Priya — quick chat about the site engineer role?" },
        { who: "caller", line: "Sure. What's the salary?" },
        { who: "agent", line: "The band is 12–18 LPA depending on experience. Does that work?" },
        { who: "caller", line: "Works for me. I have 6 years on metro projects." },
      ],
      outcome: { text: "Screened · 6 yrs · notice 30 days", pill: "Shortlisted" },
    },
    {
      channel: "WhatsApp",
      role: "Salon booking assistant",
      transcript: [
        { who: "caller", line: "Can I get a cut and colour with Aisha on Saturday?" },
        { who: "agent", line: "Aisha has 10:30am — that's two hours for both. Shall I hold it?" },
        { who: "caller", line: "Yes please 🙌" },
        { who: "agent", line: "Held and booked. I'll remind you Friday evening." },
      ],
      outcome: { text: "Booked · Sat 10:30am · Aisha", pill: "Reminder set" },
    },
    {
      channel: "Web chat",
      role: "Property enquiry agent",
      transcript: [
        { who: "caller", line: "Is the 2BHK in Wakad still available?" },
        { who: "agent", line: "It is — ₹78L, east-facing, ready to move. Want to see it this weekend?" },
        { who: "caller", line: "Saturday morning works." },
        { who: "agent", line: "Viewing set for 11am. Sending you the location and the floor plan." },
      ],
      outcome: { text: "Viewing · Sat 11am · Wakad 2BHK", pill: "Lead qualified" },
    },
    {
      channel: "Live call",
      role: "Diagnostic lab front desk",
      transcript: [
        { who: "caller", line: "I need to move my blood test from tomorrow." },
        { who: "agent", line: "No problem — I have Monday 8am or Tuesday 7:30am, both fasting slots." },
        { who: "caller", line: "Monday." },
        { who: "agent", line: "Moved to Monday 8am. Remember: no food after 10pm Sunday." },
      ],
      outcome: { text: "Moved · Mon 8:00am · fasting", pill: "Confirmed" },
    },
  ],
  pricing: {
    eyebrow: "Pricing",
    heading: "Pay for the conversations you actually handle.",
    lead:
      "A flat platform fee, then usage. Set a daily cap per workspace so a campaign that runs away cannot surprise you at the end of the month.",
    cta: "Start free",
    planName: "Usage-based",
    planBadge: "Free while you build",
    planBody:
      "Build, test and tune as many agents as you like before a single one goes live. Billing starts when real calls and messages do.",
    features: [
      "Unlimited agents and knowledge documents",
      "Voice, WhatsApp, web chat and the embeddable widget",
      "Real-calendar booking, rescheduling and reminders",
      "Shared team inbox with takeover and assignment",
      "Your own cloned voice on outbound calls",
      "A daily spend cap you control",
    ],
  },
  testimonial: {
    before:
      "We were losing bookings every evening because nobody was there to pick up. The agent answers, checks the diary, and books them in. Our ",
    highlight: "after-hours bookings went from zero",
    after: " to a third of the week.",
    source: "Practice manager · multi-site dental group",
  },
  products: {
    eyebrow: "The platform",
    heading: "Everything you need to run agents in production.",
    explore: "Explore",
    cards: [
      {
        title: "Voice AI Assistants",
        body: "Build the agent, give it your documents, test it on a call, put it on a number.",
      },
      {
        title: "WhatsApp Agent",
        body: "Link a number by QR, answer automatically, and work the inbox as a team.",
      },
      {
        title: "Hiring Agent",
        body: "Screens candidates end to end and writes up every interview for you.",
      },
      {
        title: "Voice Cloning",
        body: "Put your own voice on every outbound call your agents make.",
      },
    ],
  },
  resources: {
    eyebrow: "Also in the box",
    heading: "The unglamorous parts, already built.",
    cards: [
      { title: "Knowledge base", body: "Everything your agents can read, in one library." },
      { title: "Scheduling", body: "Services, staff, locations and opening hours." },
      { title: "Analytics", body: "Every call, every answer, and what it cost." },
      { title: "Integrations", body: "Your calendar, your CRM, your webhook." },
    ],
  },
  closing: {
    heading: "Put an agent on your front desk this week.",
    lead:
      "Build it, give it your documents and your calendar, and hear it answer — before you decide whether to point a real number at it.",
    ctaPrimary: "Start building for free",
    ctaSecondary: "Talk to us",
    stepsEyebrow: "What day one looks like",
    steps: [
      { title: "Describe the role", body: "In plain sentences. “You are the receptionist for a dental clinic.”" },
      { title: "Upload what it should know", body: "Price list, policies, treatment menu, FAQs." },
      { title: "Add services and opening hours", body: "So the times it offers are times you can honour." },
      { title: "Test it on a call", body: "Then point a phone or WhatsApp number at it." },
    ],
  },
  faq: {
    eyebrow: "FAQ",
    heading: "Questions people ask before they start.",
    items: [
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
    ],
  },
  footer: {
    rights: "Evara AI. Agents that answer, book and follow up.",
    product: "Product",
    pricing: "Pricing",
    support: "Support",
    login: "Log in",
  },
};
