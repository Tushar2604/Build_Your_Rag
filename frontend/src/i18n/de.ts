// German (de). "Sie" throughout — B2B. Compound nouns are kept short where a
// natural alternative exists, because German runs roughly a third longer than
// English and the hero headline has a fixed number of lines to live in.
import { LandingCopy } from "./types";

export const de: LandingCopy = {
  nav: {
    product: "Produkt",
    howItWorks: "So funktioniert's",
    pricing: "Preise",
    faq: "FAQ",
    login: "Anmelden",
    dashboard: "Dashboard",
    startBuilding: "Loslegen",
    language: "Sprache",
  },
  hero: {
    badge: "Sprache · WhatsApp · Chat",
    headline: "KI-Agenten, die abnehmen, Termine buchen und nachfassen — auf all Ihren Kanälen.",
    sub:
      "Geben Sie Ihrem Empfang eine Verstärkung, die keinen Anruf verpasst. Evara-Agenten gehen ans Telefon, antworten auf WhatsApp und im Chat, sehen in Ihren echten Kalender, buchen den Termin und übergeben Ihnen die Notizen.",
    ctaPrimary: "Kostenlos starten",
    ctaSecondary: "Live ansehen",
    note: "Ohne Kreditkarte · Ihr erster Agent antwortet noch am selben Tag",
  },
  proof: [
    { title: "24/7", body: "Kein verpasster Anruf, keine liegengebliebene Nachricht" },
    { title: "4 Kanäle", body: "Telefon, WhatsApp, Web-Chat und einbettbares Widget" },
    { title: "Null", body: "Erfundene Preise, Termine oder Zeiten — jede Antwort ist belegt" },
  ],
  industries: {
    label: "Am Empfang von",
    items: [
      "Zahnarztpraxen", "Salons und Spas", "Laboren",
      "Personalvermittlung", "Immobilien", "Handwerk und Service",
    ],
  },
  why: {
    eyebrow: "Warum Evara",
    heading: "Gebaut, um die Sache zu erledigen — nicht, um so zu klingen.",
    cards: [
      {
        title: "Er erfindet nie eine Antwort",
        body:
          "Jede Angabe stammt aus Ihren eigenen Dokumenten, jede Uhrzeit aus Ihrem echten Kalender. Weiß der Agent etwas nicht, sagt er das und nennt die Person, die es bestätigen kann — er rät weder einen Preis noch einen Termin.",
      },
      {
        title: "Er bringt es wirklich zu Ende",
        body:
          "Kein Chatbot, der eine Nachricht entgegennimmt. Der Agent prüft die Verfügbarkeit, hält den Termin, während er die Daten aufnimmt, trägt die Buchung ein und schickt die Bestätigung — von Anfang bis Ende, solange der Anrufer noch dran ist.",
      },
      {
        title: "Sie behalten die Zügel",
        body:
          "Lesen Sie jedes Gespräch mit, übernehmen Sie mittendrin, und ändern Sie mit ganz normalen Sätzen, was der Agent sagt — kein Prompt-Engineering, kein Deployment, kein Warten auf uns.",
      },
    ],
  },
  capabilities: {
    eyebrow: "Was der Agent tut",
    heading: "Eine Verstärkung, auf allen Kanälen, die Sie ohnehin nutzen.",
    soon: "Demnächst",
    cards: [
      {
        title: "Geht ans Telefon",
        body:
          "Eine echte Stimme bei ein- und ausgehenden Anrufen, auf Wunsch Ihre eigene geklonte. Er kommt mit Unterbrechungen zurecht, lässt Denkpausen zu und redet nie dazwischen.",
      },
      {
        title: "Bucht den Termin",
        body:
          "Er liest Ihre Leistungen, Ihr Team und Ihre Öffnungszeiten, bietet nur wirklich freie Zeiten an, hält sie während der Datenaufnahme und bucht. Verschieben und Absagen ebenso.",
      },
      {
        title: "Betreut Ihr WhatsApp",
        body:
          "Nummer per QR verbinden — der Agent antwortet dort. Dazu ein gemeinsamer Posteingang fürs Team: Chat zuweisen, verschlagworten, übernehmen und zurückgeben.",
      },
      {
        title: "Kennt Ihr Geschäft",
        body:
          "Laden Sie Preisliste, Richtlinien und häufige Fragen hoch. Der Agent antwortet aus diesen Dokumenten und behauptet nichts, was er nicht gelesen hat — der Unterschied zwischen hilfreich und selbstbewusst falsch.",
      },
      {
        title: "Nimmt die Zahlung entgegen",
        body:
          "Wird im selben Gespräch einen Anzahlungs- oder Rechnungslink senden und die Buchung bestätigen, sobald das Geld da ist — der Termin ist dann bezahlt, nicht nur notiert.",
      },
      {
        title: "Fasst von selbst nach",
        body:
          "Er hakt bei stillen Interessenten nach, erinnert Patienten am Vortag und fährt Kampagnen an eine Liste — und hört auf, sobald jemand antwortet, um das Gespräch weiterzuführen.",
      },
    ],
  },
  runtime: {
    eyebrow: "So funktioniert's",
    heading: "Sie beschreiben die Rolle. Er erscheint zur Schicht.",
    lead:
      "Ein Agent besteht aus einer Rollenbeschreibung, ein paar Dokumenten und dem, was er tun darf. Wählen Sie einen Ausgangspunkt und ändern Sie ihn in normalen Sätzen: kein Prompt zu bauen, nichts erneut auszurollen.",
  },
  scenes: [
    {
      channel: "Live-Anruf",
      role: "Empfang Zahnarztpraxis",
      transcript: [
        { who: "caller", line: "Guten Tag, haben Sie diese Woche noch einen Termin zur Zahnreinigung?" },
        { who: "agent", line: "Ja — Donnerstag 16:15 Uhr oder Freitag 11:00 Uhr bei Dr. Rao. Was passt Ihnen?" },
        { who: "caller", line: "Donnerstag, bitte." },
        { who: "agent", line: "Eingetragen. Die Bestätigung kommt gleich per WhatsApp." },
      ],
      outcome: { text: "Gebucht · Do 16:15 · Dr. Rao", pill: "Bestätigt" },
    },
    {
      channel: "WhatsApp",
      role: "Vorauswahl erste Runde",
      transcript: [
        { who: "agent", line: "Hallo Priya — kurz zur Stelle als Bauleiterin?" },
        { who: "caller", line: "Gern. Wie ist das Gehalt?" },
        { who: "agent", line: "Die Spanne liegt je nach Erfahrung bei 12–18 LPA. Passt das für Sie?" },
        { who: "caller", line: "Passt. Ich habe 6 Jahre Erfahrung im U-Bahn-Bau." },
      ],
      outcome: { text: "Geprüft · 6 Jahre · Kündigungsfrist 30 Tage", pill: "In der Auswahl" },
    },
    {
      channel: "WhatsApp",
      role: "Terminassistenz Salon",
      transcript: [
        { who: "caller", line: "Bekomme ich am Samstag Schnitt und Farbe bei Aisha?" },
        { who: "agent", line: "Aisha hat 10:30 Uhr frei — für beides zwei Stunden. Soll ich reservieren?" },
        { who: "caller", line: "Ja, gerne 🙌" },
        { who: "agent", line: "Reserviert und gebucht. Ich erinnere Sie Freitagabend." },
      ],
      outcome: { text: "Gebucht · Sa 10:30 · Aisha", pill: "Erinnerung aktiv" },
    },
    {
      channel: "Web-Chat",
      role: "Immobilienanfragen",
      transcript: [
        { who: "caller", line: "Ist die 3-Zimmer-Wohnung in Wakad noch zu haben?" },
        { who: "agent", line: "Ja — 78 Lakh ₹, Ostlage, bezugsfertig. Möchten Sie sie am Wochenende sehen?" },
        { who: "caller", line: "Samstagvormittag passt." },
        { who: "agent", line: "Besichtigung um 11:00 Uhr. Ich schicke Ihnen Adresse und Grundriss." },
      ],
      outcome: { text: "Besichtigung · Sa 11:00 · Wakad", pill: "Qualifiziert" },
    },
    {
      channel: "Live-Anruf",
      role: "Empfang Labor",
      transcript: [
        { who: "caller", line: "Ich muss meine Blutabnahme von morgen verschieben." },
        { who: "agent", line: "Kein Problem — Montag 8:00 Uhr oder Dienstag 7:30 Uhr, beides nüchtern." },
        { who: "caller", line: "Montag." },
        { who: "agent", line: "Auf Montag 8:00 Uhr verschoben. Bitte denken Sie daran: ab Sonntag 22 Uhr nichts mehr essen." },
      ],
      outcome: { text: "Verschoben · Mo 8:00 · nüchtern", pill: "Bestätigt" },
    },
  ],
  pricing: {
    eyebrow: "Preise",
    heading: "Zahlen Sie für die Gespräche, die Sie wirklich führen.",
    lead:
      "Eine feste Plattformgebühr, danach Verbrauch. Legen Sie ein Tageslimit je Workspace fest, damit eine entgleiste Kampagne Sie zum Monatsende nicht überrascht.",
    cta: "Kostenlos starten",
    planName: "Nach Verbrauch",
    planBadge: "Kostenlos beim Aufbau",
    planBody:
      "Bauen, testen und feilen Sie an beliebig vielen Agenten, bevor einer live geht. Abgerechnet wird ab dem ersten echten Anruf und der ersten echten Nachricht.",
    features: [
      "Unbegrenzt Agenten und Wissensdokumente",
      "Sprache, WhatsApp, Web-Chat und einbettbares Widget",
      "Buchen, Verschieben und Erinnern im echten Kalender",
      "Gemeinsamer Posteingang mit Übernahme und Zuweisung",
      "Ihre eigene geklonte Stimme bei ausgehenden Anrufen",
      "Ein Tagesbudget, das Sie selbst bestimmen",
    ],
  },
  testimonial: {
    before:
      "Uns gingen jeden Abend Termine verloren, weil niemand abnahm. Der Agent antwortet, sieht in den Kalender und trägt sie ein. Unsere ",
    highlight: "Buchungen außerhalb der Öffnungszeiten stiegen von null",
    after: " auf ein Drittel der Woche.",
    source: "Praxismanagerin · Zahnarztgruppe mit mehreren Standorten",
  },
  products: {
    eyebrow: "Die Plattform",
    heading: "Alles, um Agenten im Echtbetrieb zu führen.",
    explore: "Ansehen",
    cards: [
      {
        title: "KI-Sprachassistenten",
        body: "Agent bauen, Dokumente geben, im Anruf testen, auf eine Nummer legen.",
      },
      {
        title: "WhatsApp-Agent",
        body: "Nummer per QR verbinden, automatisch antworten, Posteingang im Team bearbeiten.",
      },
      {
        title: "Recruiting-Agent",
        body: "Führt die komplette Vorauswahl und schreibt Ihnen jedes Gespräch auf.",
      },
      {
        title: "Stimmklon",
        body: "Ihre eigene Stimme bei jedem ausgehenden Anruf Ihrer Agenten.",
      },
    ],
  },
  resources: {
    eyebrow: "Ebenfalls dabei",
    heading: "Die unglamourösen Teile, schon gebaut.",
    cards: [
      { title: "Wissensbasis", body: "Alles, was Ihre Agenten lesen dürfen, an einem Ort." },
      { title: "Terminplanung", body: "Leistungen, Team, Standorte und Öffnungszeiten." },
      { title: "Auswertungen", body: "Jeder Anruf, jede Antwort und was sie gekostet hat." },
      { title: "Integrationen", body: "Ihr Kalender, Ihr CRM, Ihr Webhook." },
    ],
  },
  closing: {
    heading: "Setzen Sie diese Woche einen Agenten an Ihren Empfang.",
    lead:
      "Bauen Sie ihn, geben Sie ihm Ihre Dokumente und Ihren Kalender, und hören Sie ihn antworten — bevor Sie entscheiden, ob Sie ihm eine echte Nummer geben.",
    ctaPrimary: "Kostenlos starten",
    ctaSecondary: "Mit uns sprechen",
    stepsEyebrow: "So sieht Tag eins aus",
    steps: [
      { title: "Rolle beschreiben", body: "In normalen Sätzen. „Sie sind der Empfang einer Zahnarztpraxis.“" },
      { title: "Hochladen, was er wissen muss", body: "Preisliste, Richtlinien, Behandlungsangebot, häufige Fragen." },
      { title: "Leistungen und Zeiten anlegen", body: "Damit die angebotenen Zeiten auch Zeiten sind, die Sie halten können." },
      { title: "Im Anruf testen", body: "Danach eine Telefon- oder WhatsApp-Nummer darauf legen." },
    ],
  },
  faq: {
    eyebrow: "FAQ",
    heading: "Was man vor dem Start wissen will.",
    items: [
      {
        q: "Wie lange dauert es, bis ein Agent antwortet?",
        a: "Ein Nachmittag. Assistenten anlegen, die Dokumente hochladen, aus denen er antworten soll, Leistungen und Öffnungszeiten eintragen und im Web-Anruf testen. Ihn auf eine echte Telefon- oder WhatsApp-Nummer zu legen ist der letzte Schritt, nicht der erste.",
      },
      {
        q: "Erfindet er Dinge?",
        a: "Er ist so gebaut, dass er es nicht tut. Antworten über Ihr Geschäft kommen ausschließlich aus den Dokumenten, die Sie hochladen, und Terminzeiten ausschließlich aus Ihrem Live-Kalender — der Agent kann keine Zeit anbieten, die er nicht geprüft hat. Fehlt etwas, sagt er es und nennt die Person, die es bestätigen kann, statt zu raten.",
      },
      {
        q: "Was passiert, wenn er nicht weiterhelfen kann?",
        a: "Er übergibt an einen Menschen. Sie legen fest, was außerhalb seines Rahmens liegt, und der Agent verweist weiter, statt zu improvisieren. Im gemeinsamen Posteingang können Sie außerdem jedes Gespräch mittendrin übernehmen und danach zurückgeben.",
      },
      {
        q: "Kann er meine eigene Stimme nutzen?",
        a: "Ja. Klonen Sie Ihre Stimme einmal, und jeder ausgehende Anruf Ihrer Agenten kann sie verwenden. Wenn Ihnen das lieber nicht ist, steht eine Stimmbibliothek in mehreren Sprachen und Akzenten bereit.",
      },
      {
        q: "Auf welchen Kanälen funktioniert er?",
        a: "Ein- und ausgehende Anrufe, WhatsApp, Web-Chat auf Ihrer eigenen Seite und ein einbettbares Widget. Derselbe Agent, dasselbe Wissen und ein einziger Gesprächsverlauf pro Person über alle Kanäle hinweg.",
      },
      {
        q: "Lässt er sich mit unserem bestehenden Kalender verbinden?",
        a: "Ja — der Agent liest und schreibt echte Verfügbarkeiten, statt eine eigene Kopie zu führen. Eine telefonisch gebuchte Zeit ist damit sofort aus Ihrem Kalender verschwunden, und umgekehrt.",
      },
      {
        q: "Wer kann die Gespräche sehen?",
        a: "Ihr Workspace, sonst niemand. Jeder Datensatz ist bereits in der Datenbank selbst nach Mandant getrennt, nicht erst in der Anwendung, und Ihre Dokumente werden nie zum Training eines gemeinsamen Modells verwendet.",
      },
      {
        q: "Was kostet es?",
        a: "Eine feste monatliche Plattformgebühr plus Verbrauch — abgerechnet werden die Minuten und Nachrichten, die Ihre Agenten tatsächlich bearbeiten, mit einem Tageslimit je Workspace, das Sie selbst setzen, damit eine entgleiste Kampagne Sie nicht überrascht.",
      },
    ],
  },
  footer: {
    rights: "Evara AI. Agenten, die abnehmen, buchen und nachfassen.",
    product: "Produkt",
    pricing: "Preise",
    support: "Support",
    login: "Anmelden",
  },
};
