// French (fr). "Vous" throughout — this is a business buyer, and tutoiement in
// B2B marketing reads as either American or careless to a French reader.
import { LandingCopy } from "./types";

export const fr: LandingCopy = {
  nav: {
    product: "Produit",
    howItWorks: "Fonctionnement",
    pricing: "Tarifs",
    faq: "FAQ",
    login: "Connexion",
    dashboard: "Tableau de bord",
    startBuilding: "Commencer",
    language: "Langue",
  },
  hero: {
    badge: "Voix · WhatsApp · Chat",
    headline: "Des agents IA qui répondent, réservent et relancent — sur tous vos canaux.",
    sub:
      "Offrez à votre accueil un collègue qui ne manque jamais un appel. Les agents Evara décrochent, répondent sur WhatsApp et en chat, consultent votre véritable agenda, prennent le rendez-vous et vous transmettent le compte rendu.",
    ctaPrimary: "Commencer gratuitement",
    ctaSecondary: "Voir en action",
    note: "Sans carte bancaire · Votre premier agent répond le jour même",
  },
  proof: [
    { title: "24/7", body: "Plus aucun appel ni message sans réponse" },
    { title: "4 canaux", body: "Téléphone, WhatsApp, chat web et widget intégrable" },
    { title: "Zéro", body: "Tarif, date ou créneau inventé — chaque réponse est sourcée" },
  ],
  industries: {
    label: "À l'accueil de",
    items: [
      "Cabinets dentaires", "Salons et spas", "Laboratoires d'analyses",
      "Recrutement", "Immobilier", "Services à domicile",
    ],
  },
  why: {
    eyebrow: "Pourquoi Evara",
    heading: "Conçu pour aller au bout, pas pour en donner l'impression.",
    cards: [
      {
        title: "Il n'invente jamais de réponse",
        body:
          "Chaque information vient de vos propres documents et chaque horaire de votre agenda réel. Quand l'agent ne sait pas, il le dit et indique qui pourra confirmer — il ne devine ni un tarif ni un créneau.",
      },
      {
        title: "Il va réellement au bout",
        body:
          "Ce n'est pas un chatbot qui prend un message. L'agent consulte les disponibilités, bloque le créneau pendant qu'il recueille les informations, enregistre le rendez-vous et envoie la confirmation — de bout en bout, l'appelant encore en ligne.",
      },
      {
        title: "Vous gardez la main",
        body:
          "Relisez chaque conversation, reprenez-en une en cours de route, et changez ce que dit l'agent en modifiant des phrases ordinaires : ni prompt à concevoir, ni redéploiement, ni attente de notre part.",
      },
    ],
  },
  capabilities: {
    eyebrow: "Ce que fait l'agent",
    heading: "Un seul collègue, sur tous les canaux que vous utilisez déjà.",
    soon: "Bientôt disponible",
    cards: [
      {
        title: "Il décroche",
        body:
          "Une vraie voix en appel entrant comme sortant, avec votre propre voix clonée si vous le souhaitez. Il gère les interruptions, laisse le temps de réfléchir et ne parle jamais par-dessus.",
      },
      {
        title: "Il prend le rendez-vous",
        body:
          "Il lit vos prestations, votre équipe et vos horaires, ne propose que des créneaux réellement libres, les bloque le temps de recueillir les informations et confirme. Report et annulation compris.",
      },
      {
        title: "Il tient votre WhatsApp",
        body:
          "Reliez votre numéro par QR et l'agent y répond. Avec, une boîte de réception partagée pour l'équipe : attribuez une conversation, étiquetez-la, reprenez-la, rendez-la.",
      },
      {
        title: "Il connaît votre activité",
        body:
          "Importez vos tarifs, vos conditions et vos questions fréquentes. L'agent répond à partir de ces documents et n'avance rien qu'il n'ait lu — toute la différence entre être utile et se tromper avec assurance.",
      },
      {
        title: "Il encaisse l'acompte",
        body:
          "Il enverra un lien de paiement ou de facture dans la même conversation et confirmera le rendez-vous dès l'encaissement, pour que le créneau soit payé et pas seulement noté.",
      },
      {
        title: "Il relance tout seul",
        body:
          "Il relance un prospect silencieux, rappelle le patient la veille et lance une campagne sur une liste — puis s'arrête dès que quelqu'un répond et reprend la conversation.",
      },
    ],
  },
  runtime: {
    eyebrow: "Fonctionnement",
    heading: "Vous décrivez le poste. Il se présente à la prise de service.",
    lead:
      "Un agent, c'est une description de poste, un ensemble de documents et ce qu'il a le droit de faire. Choisissez un point de départ et modifiez-le en phrases ordinaires : aucun prompt à concevoir, rien à redéployer.",
  },
  scenes: [
    {
      channel: "Appel en direct",
      role: "Accueil de cabinet dentaire",
      transcript: [
        { who: "caller", line: "Bonjour, auriez-vous un créneau pour un détartrage cette semaine ?" },
        { who: "agent", line: "Oui — jeudi à 16h15 ou vendredi à 11h avec le Dr Rao. Que préférez-vous ?" },
        { who: "caller", line: "Jeudi, s'il vous plaît." },
        { who: "agent", line: "C'est noté. Vous recevez la confirmation sur WhatsApp dans un instant." },
      ],
      outcome: { text: "Réservé · jeu. 16h15 · Dr Rao", pill: "Confirmé" },
    },
    {
      channel: "WhatsApp",
      role: "Présélection de premier tour",
      transcript: [
        { who: "agent", line: "Bonjour Priya — un mot rapide sur le poste d'ingénieure travaux ?" },
        { who: "caller", line: "Bien sûr. Quel est le salaire ?" },
        { who: "agent", line: "La fourchette est de 12 à 18 LPA selon l'expérience. Cela vous convient ?" },
        { who: "caller", line: "Cela me convient. J'ai 6 ans sur des projets de métro." },
      ],
      outcome: { text: "Préqualifiée · 6 ans · préavis 30 j", pill: "Retenue" },
    },
    {
      channel: "WhatsApp",
      role: "Réservations du salon",
      transcript: [
        { who: "caller", line: "Je peux avoir une coupe et une couleur avec Aisha samedi ?" },
        { who: "agent", line: "Aisha a 10h30 — comptez deux heures pour les deux. Je vous le bloque ?" },
        { who: "caller", line: "Oui, volontiers 🙌" },
        { who: "agent", line: "Bloqué et réservé. Je vous le rappelle vendredi soir." },
      ],
      outcome: { text: "Réservé · sam. 10h30 · Aisha", pill: "Rappel activé" },
    },
    {
      channel: "Chat web",
      role: "Agent de renseignement immobilier",
      transcript: [
        { who: "caller", line: "Le trois-pièces de Wakad est-il toujours disponible ?" },
        { who: "agent", line: "Oui — 78 lakh ₹, exposé est, habitable immédiatement. Une visite ce week-end ?" },
        { who: "caller", line: "Samedi matin me convient." },
        { who: "agent", line: "Visite fixée à 11h. Je vous envoie l'adresse et le plan." },
      ],
      outcome: { text: "Visite · sam. 11h · Wakad", pill: "Prospect qualifié" },
    },
    {
      channel: "Appel en direct",
      role: "Accueil de laboratoire d'analyses",
      transcript: [
        { who: "caller", line: "Je dois décaler ma prise de sang de demain." },
        { who: "agent", line: "Pas de souci — j'ai lundi 8h ou mardi 7h30, tous deux à jeun." },
        { who: "caller", line: "Lundi." },
        { who: "agent", line: "Décalé à lundi 8h. Pensez-y : plus rien à manger après 22h dimanche." },
      ],
      outcome: { text: "Décalé · lun. 8h00 · à jeun", pill: "Confirmé" },
    },
  ],
  pricing: {
    eyebrow: "Tarifs",
    heading: "Payez les conversations que vous traitez vraiment.",
    lead:
      "Un abonnement fixe, puis la consommation. Fixez un plafond quotidien par espace de travail pour qu'une campagne qui s'emballe ne vous surprenne pas en fin de mois.",
    cta: "Commencer gratuitement",
    planName: "À l'usage",
    planBadge: "Gratuit pendant la conception",
    planBody:
      "Créez, testez et affinez autant d'agents que vous voulez avant qu'un seul ne passe en production. La facturation démarre avec les vrais appels et messages.",
    features: [
      "Agents et documents de connaissance illimités",
      "Voix, WhatsApp, chat web et widget intégrable",
      "Réservation, report et rappels sur votre agenda réel",
      "Boîte partagée avec reprise en main et attribution",
      "Votre propre voix clonée sur les appels sortants",
      "Un plafond de dépense quotidien que vous fixez",
    ],
  },
  testimonial: {
    before:
      "Nous perdions des rendez-vous chaque soir faute de quelqu'un pour décrocher. L'agent répond, consulte l'agenda et les inscrit. Nos ",
    highlight: "rendez-vous hors horaires sont passés de zéro",
    after: " à un tiers de la semaine.",
    source: "Responsable de cabinet · groupe dentaire multi-sites",
  },
  products: {
    eyebrow: "La plateforme",
    heading: "Tout le nécessaire pour exploiter des agents en production.",
    explore: "Découvrir",
    cards: [
      {
        title: "Assistants vocaux IA",
        body: "Créez l'agent, donnez-lui vos documents, testez-le en appel, affectez-lui un numéro.",
      },
      {
        title: "Agent WhatsApp",
        body: "Reliez un numéro par QR, répondez automatiquement et traitez la boîte en équipe.",
      },
      {
        title: "Agent de recrutement",
        body: "Présélectionne les candidats de bout en bout et rédige chaque entretien.",
      },
      {
        title: "Clonage de voix",
        body: "Votre propre voix sur chaque appel sortant de vos agents.",
      },
    ],
  },
  resources: {
    eyebrow: "Également inclus",
    heading: "Les parties ingrates, déjà faites.",
    cards: [
      { title: "Base de connaissances", body: "Tout ce que vos agents peuvent lire, en un seul endroit." },
      { title: "Planning", body: "Prestations, équipe, sites et horaires d'ouverture." },
      { title: "Analyses", body: "Chaque appel, chaque réponse, et ce qu'ils ont coûté." },
      { title: "Intégrations", body: "Votre agenda, votre CRM, votre webhook." },
    ],
  },
  closing: {
    heading: "Mettez un agent à votre accueil cette semaine.",
    lead:
      "Créez-le, donnez-lui vos documents et votre agenda, et écoutez-le répondre — avant de décider si vous lui confiez un vrai numéro.",
    ctaPrimary: "Commencer gratuitement",
    ctaSecondary: "Nous contacter",
    stepsEyebrow: "À quoi ressemble le premier jour",
    steps: [
      { title: "Décrivez le poste", body: "En phrases ordinaires. « Vous êtes à l'accueil d'un cabinet dentaire. »" },
      { title: "Importez ce qu'il doit savoir", body: "Tarifs, conditions, liste des soins, questions fréquentes." },
      { title: "Ajoutez prestations et horaires", body: "Pour que les créneaux proposés soient des créneaux tenables." },
      { title: "Testez-le en appel", body: "Puis affectez-lui un numéro de téléphone ou de WhatsApp." },
    ],
  },
  faq: {
    eyebrow: "FAQ",
    heading: "Les questions posées avant de se lancer.",
    items: [
      {
        q: "Combien de temps pour qu'un agent réponde ?",
        a: "Un après-midi. Créez l'assistant, importez les documents dont il doit tirer ses réponses, ajoutez vos prestations et vos horaires, puis testez-le en appel web. Lui affecter un vrai numéro de téléphone ou de WhatsApp est la dernière étape, pas la première.",
      },
      {
        q: "Va-t-il inventer des choses ?",
        a: "Il est conçu pour ne pas le faire. Les réponses sur votre activité proviennent uniquement des documents que vous importez, et les horaires uniquement de votre agenda en direct : l'agent ne peut pas proposer un créneau qu'il n'a pas vérifié. Quand une information manque, il le dit et indique qui peut confirmer, plutôt que de deviner.",
      },
      {
        q: "Que se passe-t-il quand il ne peut pas aider ?",
        a: "Il transmet à une personne. Vous définissez ce qui sort de son périmètre et l'agent redirige au lieu d'improviser. Dans la boîte partagée, vous pouvez aussi reprendre n'importe quelle conversation en cours et la rendre une fois terminée.",
      },
      {
        q: "Peut-il utiliser ma propre voix ?",
        a: "Oui. Clonez votre voix une fois et tous les appels sortants de vos agents peuvent l'utiliser. Sinon, une bibliothèque de voix est disponible dans plusieurs langues et accents.",
      },
      {
        q: "Sur quels canaux fonctionne-t-il ?",
        a: "Appels entrants et sortants, WhatsApp, chat web sur votre propre site et un widget intégrable. Le même agent, les mêmes connaissances, et un seul historique par personne sur l'ensemble.",
      },
      {
        q: "Se connecte-t-il à l'agenda que nous utilisons déjà ?",
        a: "Oui — l'agent lit et écrit les disponibilités réelles au lieu d'en tenir une copie, si bien qu'un créneau réservé par téléphone disparaît immédiatement de votre agenda, et inversement.",
      },
      {
        q: "Qui peut voir les conversations ?",
        a: "Votre espace de travail, et personne d'autre. Chaque enregistrement est cloisonné par client dans la base de données elle-même, pas seulement dans l'application, et vos documents ne servent jamais à entraîner un modèle partagé.",
      },
      {
        q: "Combien cela coûte-t-il ?",
        a: "Un abonnement mensuel fixe plus la consommation : vous payez les minutes et les messages que vos agents traitent réellement, avec un plafond quotidien par espace de travail que vous fixez pour qu'une campagne emballée ne vous surprenne pas.",
      },
    ],
  },
  footer: {
    rights: "Evara AI. Des agents qui répondent, réservent et relancent.",
    product: "Produit",
    pricing: "Tarifs",
    support: "Assistance",
    login: "Connexion",
  },
};
