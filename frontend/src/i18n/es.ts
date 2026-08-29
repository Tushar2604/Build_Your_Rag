// Spanish (es). Neutral Latin-American Spanish — "ustedes" rather than
// "vosotros", and vocabulary that reads naturally in both Spain and Mexico.
//
// The transcript in each scene is localised too, not just the surrounding
// prose: a page claiming the agent speaks your language, demonstrating it in
// English, argues against itself.
import { LandingCopy } from "./types";

export const es: LandingCopy = {
  nav: {
    product: "Producto",
    howItWorks: "Cómo funciona",
    pricing: "Precios",
    faq: "Preguntas",
    login: "Iniciar sesión",
    dashboard: "Panel",
    startBuilding: "Empezar",
    language: "Idioma",
  },
  hero: {
    badge: "Voz · WhatsApp · Chat",
    headline: "Agentes de IA que contestan, agendan y dan seguimiento — en todos tus canales.",
    sub:
      "Dale a tu recepción un compañero que nunca deja una llamada sin contestar. Los agentes de Evara atienden el teléfono, responden por WhatsApp y chat, consultan tu calendario real, cierran la cita y te pasan las notas.",
    ctaPrimary: "Empieza gratis",
    ctaSecondary: "Ver cómo funciona",
    note: "Sin tarjeta · Tu primer agente contestando el mismo día",
  },
  proof: [
    { title: "24/7", body: "Ni una llamada ni un mensaje sin responder" },
    { title: "4 canales", body: "Teléfono, WhatsApp, chat web y widget integrable" },
    { title: "Cero", body: "Precios, fechas u horarios inventados — toda respuesta está fundamentada" },
  ],
  industries: {
    label: "Atendiendo la recepción de",
    items: [
      "Clínicas dentales", "Salones y spas", "Laboratorios clínicos",
      "Reclutamiento", "Inmobiliarias", "Servicios a domicilio",
    ],
  },
  why: {
    eyebrow: "Por qué Evara",
    heading: "Hecho para terminar el trabajo, no para aparentar que lo hizo.",
    cards: [
      {
        title: "Nunca inventa una respuesta",
        body:
          "Cada dato sale de tus propios documentos y cada horario de tu calendario real. Cuando el agente no sabe algo, lo dice y le indica al cliente quién sí puede confirmarlo — no adivina un precio ni un horario.",
      },
      {
        title: "De verdad completa la gestión",
        body:
          "No es un chatbot que toma recados. El agente consulta la disponibilidad, reserva el horario mientras pide los datos, registra la cita y envía la confirmación — de principio a fin, con el cliente todavía en la línea.",
      },
      {
        title: "Tú sigues al mando",
        body:
          "Lee cada conversación, toma el control a mitad del hilo y cambia lo que dice el agente editando frases normales: sin ingeniería de prompts, sin volver a desplegar y sin esperarnos.",
      },
    ],
  },
  capabilities: {
    eyebrow: "Qué hace el agente",
    heading: "Un solo compañero, en todos los canales que ya usas.",
    soon: "Muy pronto",
    cards: [
      {
        title: "Contesta el teléfono",
        body:
          "Una voz real en llamadas entrantes y salientes, con tu propia voz clonada si quieres. Maneja interrupciones, espera mientras la persona piensa y nunca le habla encima.",
      },
      {
        title: "Agenda la cita",
        body:
          "Lee tus servicios, tu personal y tu horario de atención, ofrece solo huecos realmente libres, los aparta mientras toma los datos y cierra la cita. También reprograma y cancela.",
      },
      {
        title: "Lleva tu WhatsApp",
        body:
          "Vincula tu número con un QR y el agente responde ahí. Encima, una bandeja compartida para tu equipo: asigna un chat, etiquétalo, tómalo y devuélvelo.",
      },
      {
        title: "Conoce tu negocio",
        body:
          "Sube tu lista de precios, tus políticas y tus preguntas frecuentes. El agente responde desde esos documentos y no afirma nada que no haya leído — la diferencia entre ser útil y equivocarse con seguridad.",
      },
      {
        title: "Cobra el anticipo",
        body:
          "Enviará un enlace de pago o factura en la misma conversación y confirmará la cita en cuanto se acredite, para que el horario quede pagado y no solo apuntado.",
      },
      {
        title: "Da seguimiento solo",
        body:
          "Insiste con un prospecto callado, recuerda la cita el día anterior y lanza campañas a una lista — y se detiene en cuanto alguien responde para retomar la conversación.",
      },
    ],
  },
  runtime: {
    eyebrow: "Cómo funciona",
    heading: "Tú describes el puesto. Él se presenta al turno.",
    lead:
      "Un agente es una descripción de puesto, un conjunto de documentos y las acciones que tiene permitidas. Elige un punto de partida y cámbialo con frases normales: no hay prompt que programar ni nada que volver a desplegar.",
  },
  scenes: [
    {
      channel: "Llamada en vivo",
      role: "Recepción de clínica dental",
      transcript: [
        { who: "caller", line: "Hola, ¿tienen hueco para una limpieza esta semana?" },
        { who: "agent", line: "Sí — jueves a las 16:15 o viernes a las 11:00 con la Dra. Rao. ¿Cuál le viene mejor?" },
        { who: "caller", line: "El jueves, por favor." },
        { who: "agent", line: "Agendado. Le llega la confirmación por WhatsApp en un momento." },
      ],
      outcome: { text: "Agendado · jue 16:15 · Dra. Rao", pill: "Confirmado" },
    },
    {
      channel: "WhatsApp",
      role: "Filtro de primera ronda",
      transcript: [
        { who: "agent", line: "Hola Priya, ¿hablamos un momento sobre la vacante de ingeniera de obra?" },
        { who: "caller", line: "Claro. ¿Cuál es el sueldo?" },
        { who: "agent", line: "El rango es de 12 a 18 LPA según la experiencia. ¿Te encaja?" },
        { who: "caller", line: "Me encaja. Tengo 6 años en proyectos de metro." },
      ],
      outcome: { text: "Filtrada · 6 años · aviso 30 días", pill: "Preseleccionada" },
    },
    {
      channel: "WhatsApp",
      role: "Reservas del salón",
      transcript: [
        { who: "caller", line: "¿Puedo hacerme corte y color con Aisha el sábado?" },
        { who: "agent", line: "Aisha tiene las 10:30 — son dos horas para ambos. ¿Se lo aparto?" },
        { who: "caller", line: "Sí, por favor 🙌" },
        { who: "agent", line: "Apartado y confirmado. Le recuerdo el viernes por la tarde." },
      ],
      outcome: { text: "Reservado · sáb 10:30 · Aisha", pill: "Recordatorio activo" },
    },
    {
      channel: "Chat web",
      role: "Agente de consultas inmobiliarias",
      transcript: [
        { who: "caller", line: "¿Sigue disponible el piso de 2 recámaras en Wakad?" },
        { who: "agent", line: "Sí — 78 lakh, orientación este, listo para entrar. ¿Lo visitamos este fin de semana?" },
        { who: "caller", line: "El sábado por la mañana me sirve." },
        { who: "agent", line: "Visita agendada a las 11:00. Le envío la ubicación y el plano." },
      ],
      outcome: { text: "Visita · sáb 11:00 · Wakad", pill: "Prospecto calificado" },
    },
    {
      channel: "Llamada en vivo",
      role: "Recepción de laboratorio clínico",
      transcript: [
        { who: "caller", line: "Necesito cambiar mi análisis de sangre de mañana." },
        { who: "agent", line: "Sin problema — tengo lunes a las 8:00 o martes a las 7:30, ambos en ayunas." },
        { who: "caller", line: "El lunes." },
        { who: "agent", line: "Movido al lunes a las 8:00. Recuerde: sin alimentos después de las 22:00 del domingo." },
      ],
      outcome: { text: "Cambiado · lun 8:00 · en ayunas", pill: "Confirmado" },
    },
  ],
  pricing: {
    eyebrow: "Precios",
    heading: "Paga por las conversaciones que realmente atiendes.",
    lead:
      "Una cuota fija de plataforma y después consumo. Define un tope diario por espacio de trabajo para que una campaña desbocada no te sorprenda a fin de mes.",
    cta: "Empieza gratis",
    planName: "Por consumo",
    planBadge: "Gratis mientras construyes",
    planBody:
      "Crea, prueba y ajusta todos los agentes que quieras antes de que uno solo entre en producción. La facturación empieza cuando empiezan las llamadas y los mensajes reales.",
    features: [
      "Agentes y documentos de conocimiento ilimitados",
      "Voz, WhatsApp, chat web y widget integrable",
      "Reservas, cambios y recordatorios sobre tu calendario real",
      "Bandeja compartida con toma de control y asignación",
      "Tu propia voz clonada en las llamadas salientes",
      "Un tope de gasto diario que tú controlas",
    ],
  },
  testimonial: {
    before:
      "Perdíamos citas cada tarde porque no había nadie para contestar. El agente responde, mira la agenda y las registra. Nuestras ",
    highlight: "citas fuera de horario pasaron de cero",
    after: " a un tercio de la semana.",
    source: "Gerente de clínica · grupo dental con varias sedes",
  },
  products: {
    eyebrow: "La plataforma",
    heading: "Todo lo necesario para operar agentes en producción.",
    explore: "Explorar",
    cards: [
      {
        title: "Asistentes de voz con IA",
        body: "Crea el agente, dale tus documentos, pruébalo en una llamada y ponlo en un número.",
      },
      {
        title: "Agente de WhatsApp",
        body: "Vincula un número con QR, responde automáticamente y trabaja la bandeja en equipo.",
      },
      {
        title: "Agente de reclutamiento",
        body: "Filtra candidatos de principio a fin y te redacta cada entrevista.",
      },
      {
        title: "Clonación de voz",
        body: "Pon tu propia voz en cada llamada saliente de tus agentes.",
      },
    ],
  },
  resources: {
    eyebrow: "También incluido",
    heading: "Las partes menos vistosas, ya resueltas.",
    cards: [
      { title: "Base de conocimiento", body: "Todo lo que tus agentes pueden leer, en una biblioteca." },
      { title: "Agenda", body: "Servicios, personal, sedes y horarios de atención." },
      { title: "Analítica", body: "Cada llamada, cada respuesta y lo que costó." },
      { title: "Integraciones", body: "Tu calendario, tu CRM, tu webhook." },
    ],
  },
  closing: {
    heading: "Pon un agente en tu recepción esta semana.",
    lead:
      "Créalo, dale tus documentos y tu calendario, y escúchalo contestar — antes de decidir si le apuntas un número real.",
    ctaPrimary: "Empieza gratis",
    ctaSecondary: "Hablar con nosotros",
    stepsEyebrow: "Cómo es el primer día",
    steps: [
      { title: "Describe el puesto", body: "Con frases normales. «Eres la recepción de una clínica dental.»" },
      { title: "Sube lo que debe saber", body: "Lista de precios, políticas, carta de tratamientos, preguntas frecuentes." },
      { title: "Añade servicios y horarios", body: "Para que los huecos que ofrezca sean huecos que puedas cumplir." },
      { title: "Pruébalo en una llamada", body: "Y después apúntale un número de teléfono o de WhatsApp." },
    ],
  },
  faq: {
    eyebrow: "Preguntas frecuentes",
    heading: "Lo que la gente pregunta antes de empezar.",
    items: [
      {
        q: "¿Cuánto se tarda en tener un agente contestando?",
        a: "Una tarde. Crea el asistente, sube los documentos de los que debe responder, añade tus servicios y horarios, y pruébalo en una llamada web. Ponerlo en un número real de teléfono o WhatsApp es el último paso, no el primero.",
      },
      {
        q: "¿Se va a inventar cosas?",
        a: "Está construido para no hacerlo. Las respuestas sobre tu negocio salen solo de los documentos que subes, y los horarios solo de tu calendario en vivo: el agente no puede ofrecer un hueco que no haya comprobado. Cuando falta algo lo dice e indica quién puede confirmarlo, en lugar de adivinar.",
      },
      {
        q: "¿Qué pasa cuando no puede ayudar?",
        a: "Deriva a una persona. Tú defines qué queda fuera de su alcance y el agente redirige en vez de improvisar. En la bandeja compartida también puedes tomar cualquier conversación a mitad del hilo y devolverla cuando termines.",
      },
      {
        q: "¿Puede usar mi propia voz?",
        a: "Sí. Clona tu voz una vez y todas las llamadas salientes de tus agentes pueden usarla. Si prefieres que no, hay una biblioteca de voces en distintos idiomas y acentos.",
      },
      {
        q: "¿En qué canales funciona?",
        a: "Llamadas entrantes y salientes, WhatsApp, chat web en tu propio sitio y un widget integrable. El mismo agente, el mismo conocimiento y un solo historial por persona en todos ellos.",
      },
      {
        q: "¿Se conecta al calendario que ya usamos?",
        a: "Sí — el agente lee y escribe disponibilidad real en lugar de mantener su propia copia, así que un hueco reservado por teléfono desaparece de tu calendario al instante y al revés.",
      },
      {
        q: "¿Quién puede ver las conversaciones?",
        a: "Tu espacio de trabajo y nadie más. Cada registro está aislado por inquilino en la propia base de datos, no solo en la aplicación, y tus documentos nunca se usan para entrenar un modelo compartido.",
      },
      {
        q: "¿Cuánto cuesta?",
        a: "Una cuota mensual fija de plataforma más consumo: se te cobran los minutos y mensajes que tus agentes atienden de verdad, con un tope diario por espacio de trabajo que tú defines para que una campaña desbocada no te sorprenda.",
      },
    ],
  },
  footer: {
    rights: "Evara AI. Agentes que contestan, agendan y dan seguimiento.",
    product: "Producto",
    pricing: "Precios",
    support: "Soporte",
    login: "Iniciar sesión",
  },
};
