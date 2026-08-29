// Portuguese (pt-BR). Brazilian rather than European — it is the larger market
// by an order of magnitude, and the two differ enough in business register
// ("agendar" vs "marcar", "celular" vs "telemóvel") that splitting the
// difference would read as neither.
import { LandingCopy } from "./types";

export const pt: LandingCopy = {
  nav: {
    product: "Produto",
    howItWorks: "Como funciona",
    pricing: "Preços",
    faq: "Dúvidas",
    login: "Entrar",
    dashboard: "Painel",
    startBuilding: "Começar",
    language: "Idioma",
  },
  hero: {
    badge: "Voz · WhatsApp · Chat",
    headline: "Agentes de IA que atendem, agendam e fazem o follow-up — em todos os seus canais.",
    sub:
      "Dê à sua recepção um colega que nunca perde uma ligação. Os agentes da Evara atendem o telefone, respondem no WhatsApp e no chat, consultam sua agenda real, fecham o agendamento e te entregam as anotações.",
    ctaPrimary: "Comece grátis",
    ctaSecondary: "Ver funcionando",
    note: "Sem cartão · Seu primeiro agente atendendo no mesmo dia",
  },
  proof: [
    { title: "24/7", body: "Nenhuma ligação e nenhuma mensagem sem resposta" },
    { title: "4 canais", body: "Telefone, WhatsApp, chat no site e widget incorporável" },
    { title: "Zero", body: "Preços, datas ou horários inventados — toda resposta é fundamentada" },
  ],
  industries: {
    label: "Cuidando da recepção de",
    items: [
      "Clínicas odontológicas", "Salões e spas", "Laboratórios de análises",
      "Recrutamento", "Imobiliárias", "Serviços residenciais",
    ],
  },
  why: {
    eyebrow: "Por que a Evara",
    heading: "Feito para concluir o atendimento, não para parecer que concluiu.",
    cards: [
      {
        title: "Ele nunca inventa uma resposta",
        body:
          "Cada informação vem dos seus próprios documentos e cada horário vem da sua agenda real. Quando o agente não sabe algo, ele diz e indica quem pode confirmar — não chuta preço nem horário.",
      },
      {
        title: "Ele conclui o atendimento de verdade",
        body:
          "Não é um chatbot que anota recado. O agente consulta a disponibilidade, segura o horário enquanto pega os dados, registra o agendamento e envia a confirmação — do início ao fim, com a pessoa ainda na linha.",
      },
      {
        title: "O controle continua com você",
        body:
          "Leia cada conversa, assuma qualquer uma no meio do caminho e mude o que o agente diz editando frases comuns — sem engenharia de prompt, sem novo deploy e sem depender da gente.",
      },
    ],
  },
  capabilities: {
    eyebrow: "O que o agente faz",
    heading: "Um colega só, em todos os canais que você já usa.",
    soon: "Em breve",
    cards: [
      {
        title: "Atende o telefone",
        body:
          "Uma voz real em ligações recebidas e feitas, com a sua própria voz clonada se você quiser. Lida com interrupções, espera enquanto a pessoa pensa e nunca fala por cima.",
      },
      {
        title: "Faz o agendamento",
        body:
          "Lê seus serviços, sua equipe e seu horário de funcionamento, oferece só os horários realmente livres, segura o horário enquanto pega os dados e agenda. Remarcação e cancelamento também.",
      },
      {
        title: "Cuida do seu WhatsApp",
        body:
          "Conecte seu número pelo QR e o agente já responde por lá. Ainda tem uma caixa de entrada compartilhada para o time: atribua uma conversa, marque com etiqueta, assuma e devolva.",
      },
      {
        title: "Conhece o seu negócio",
        body:
          "Suba sua tabela de preços, suas políticas e suas dúvidas frequentes. O agente responde a partir desses documentos e não afirma nada que não tenha lido — a diferença entre ser útil e errar com confiança.",
      },
      {
        title: "Recebe o pagamento",
        body:
          "Vai enviar um link de sinal ou cobrança na mesma conversa e confirmar o agendamento assim que cair, para o horário ficar pago e não só anotado.",
      },
      {
        title: "Faz o follow-up sozinho",
        body:
          "Retoma um lead parado, lembra o paciente na véspera e dispara campanha para uma lista — e para no instante em que alguém responde, seguindo a conversa dali.",
      },
    ],
  },
  runtime: {
    eyebrow: "Como funciona",
    heading: "Você descreve a função. Ele aparece para o turno.",
    lead:
      "Um agente é uma descrição de função, um conjunto de documentos e o que ele tem permissão de fazer. Escolha um ponto de partida e altere em frases comuns: não há prompt para programar nem nada para publicar de novo.",
  },
  scenes: [
    {
      channel: "Ligação ao vivo",
      role: "Recepção de clínica odontológica",
      transcript: [
        { who: "caller", line: "Oi, vocês têm horário para limpeza esta semana?" },
        { who: "agent", line: "Temos — quinta às 16h15 ou sexta às 11h com a Dra. Rao. Qual fica melhor?" },
        { who: "caller", line: "Quinta, por favor." },
        { who: "agent", line: "Agendado. A confirmação chega no WhatsApp em instantes." },
      ],
      outcome: { text: "Agendado · qui 16h15 · Dra. Rao", pill: "Confirmado" },
    },
    {
      channel: "WhatsApp",
      role: "Triagem de primeira etapa",
      transcript: [
        { who: "agent", line: "Oi, Priya — podemos falar rapidinho sobre a vaga de engenheira de obra?" },
        { who: "caller", line: "Claro. Qual é o salário?" },
        { who: "agent", line: "A faixa é de 12 a 18 LPA conforme a experiência. Funciona para você?" },
        { who: "caller", line: "Funciona. Tenho 6 anos em projetos de metrô." },
      ],
      outcome: { text: "Triada · 6 anos · aviso 30 dias", pill: "Pré-selecionada" },
    },
    {
      channel: "WhatsApp",
      role: "Assistente de agendamento do salão",
      transcript: [
        { who: "caller", line: "Consigo corte e coloração com a Aisha no sábado?" },
        { who: "agent", line: "A Aisha tem às 10h30 — são duas horas para os dois serviços. Seguro para você?" },
        { who: "caller", line: "Pode segurar, sim 🙌" },
        { who: "agent", line: "Segurei e agendei. Te lembro na sexta à noite." },
      ],
      outcome: { text: "Agendado · sáb 10h30 · Aisha", pill: "Lembrete ativo" },
    },
    {
      channel: "Chat no site",
      role: "Agente de consultas imobiliárias",
      transcript: [
        { who: "caller", line: "O apartamento de 2 quartos em Wakad ainda está disponível?" },
        { who: "agent", line: "Está — ₹78 lakh, face leste, pronto para morar. Quer visitar neste fim de semana?" },
        { who: "caller", line: "Sábado de manhã funciona." },
        { who: "agent", line: "Visita marcada para as 11h. Já envio a localização e a planta." },
      ],
      outcome: { text: "Visita · sáb 11h · Wakad", pill: "Lead qualificado" },
    },
    {
      channel: "Ligação ao vivo",
      role: "Recepção de laboratório",
      transcript: [
        { who: "caller", line: "Preciso remarcar meu exame de sangue de amanhã." },
        { who: "agent", line: "Sem problema — tenho segunda às 8h ou terça às 7h30, os dois em jejum." },
        { who: "caller", line: "Segunda." },
        { who: "agent", line: "Remarcado para segunda às 8h. Lembre-se: nada de comer depois das 22h de domingo." },
      ],
      outcome: { text: "Remarcado · seg 8h · em jejum", pill: "Confirmado" },
    },
  ],
  pricing: {
    eyebrow: "Preços",
    heading: "Pague pelas conversas que você realmente atende.",
    lead:
      "Uma mensalidade fixa de plataforma e depois o uso. Defina um teto diário por workspace para que uma campanha fora de controle não te surpreenda no fim do mês.",
    cta: "Comece grátis",
    planName: "Por uso",
    planBadge: "Grátis enquanto você monta",
    planBody:
      "Crie, teste e ajuste quantos agentes quiser antes de qualquer um entrar no ar. A cobrança começa quando começam as ligações e mensagens reais.",
    features: [
      "Agentes e documentos de conhecimento ilimitados",
      "Voz, WhatsApp, chat no site e widget incorporável",
      "Agendamento, remarcação e lembretes na agenda real",
      "Caixa de entrada compartilhada com assunção e atribuição",
      "Sua própria voz clonada nas ligações feitas",
      "Um teto de gasto diário sob seu controle",
    ],
  },
  testimonial: {
    before:
      "A gente perdia agendamento toda noite porque não tinha ninguém para atender. O agente atende, olha a agenda e agenda. Nossos ",
    highlight: "agendamentos fora do horário saíram do zero",
    after: " para um terço da semana.",
    source: "Gerente da clínica · grupo odontológico com várias unidades",
  },
  products: {
    eyebrow: "A plataforma",
    heading: "Tudo o que você precisa para rodar agentes em produção.",
    explore: "Explorar",
    cards: [
      {
        title: "Assistentes de voz com IA",
        body: "Monte o agente, dê seus documentos, teste numa ligação e coloque num número.",
      },
      {
        title: "Agente de WhatsApp",
        body: "Conecte um número pelo QR, responda automaticamente e trabalhe a caixa em equipe.",
      },
      {
        title: "Agente de recrutamento",
        body: "Faz a triagem dos candidatos de ponta a ponta e escreve cada entrevista para você.",
      },
      {
        title: "Clonagem de voz",
        body: "Coloque sua própria voz em toda ligação que seus agentes fizerem.",
      },
    ],
  },
  resources: {
    eyebrow: "Também incluso",
    heading: "As partes sem glamour, já prontas.",
    cards: [
      { title: "Base de conhecimento", body: "Tudo o que seus agentes podem ler, numa biblioteca só." },
      { title: "Agenda", body: "Serviços, equipe, unidades e horários de funcionamento." },
      { title: "Análises", body: "Cada ligação, cada resposta e quanto custou." },
      { title: "Integrações", body: "Sua agenda, seu CRM, seu webhook." },
    ],
  },
  closing: {
    heading: "Coloque um agente na sua recepção esta semana.",
    lead:
      "Monte, dê seus documentos e sua agenda, e ouça ele atender — antes de decidir se aponta um número real para ele.",
    ctaPrimary: "Comece grátis",
    ctaSecondary: "Falar com a gente",
    stepsEyebrow: "Como é o primeiro dia",
    steps: [
      { title: "Descreva a função", body: "Em frases comuns. “Você é a recepcionista de uma clínica odontológica.”" },
      { title: "Suba o que ele precisa saber", body: "Tabela de preços, políticas, lista de procedimentos, dúvidas frequentes." },
      { title: "Cadastre serviços e horários", body: "Para que os horários oferecidos sejam horários que você consegue cumprir." },
      { title: "Teste numa ligação", body: "Depois aponte um número de telefone ou de WhatsApp para ele." },
    ],
  },
  faq: {
    eyebrow: "Dúvidas frequentes",
    heading: "O que perguntam antes de começar.",
    items: [
      {
        q: "Quanto tempo leva para ter um agente atendendo?",
        a: "Uma tarde. Crie o assistente, suba os documentos de onde ele deve responder, cadastre seus serviços e horários e teste numa ligação pelo site. Colocar num número real de telefone ou WhatsApp é o último passo, não o primeiro.",
      },
      {
        q: "Ele vai inventar coisas?",
        a: "Ele foi construído para não inventar. As respostas sobre o seu negócio saem só dos documentos que você sobe, e os horários só da sua agenda ao vivo — o agente não consegue oferecer um horário que não conferiu. Quando falta alguma informação, ele diz e indica quem pode confirmar, em vez de chutar.",
      },
      {
        q: "O que acontece quando ele não consegue ajudar?",
        a: "Ele passa para uma pessoa. Você define o que está fora do escopo e o agente redireciona em vez de improvisar. Na caixa compartilhada você também pode assumir qualquer conversa no meio e devolver quando terminar.",
      },
      {
        q: "Ele pode usar a minha própria voz?",
        a: "Pode. Clone sua voz uma vez e todas as ligações feitas pelos seus agentes podem usá-la. Se preferir que não, há uma biblioteca de vozes em vários idiomas e sotaques.",
      },
      {
        q: "Em quais canais ele funciona?",
        a: "Ligações recebidas e feitas, WhatsApp, chat no seu próprio site e um widget incorporável. O mesmo agente, o mesmo conhecimento e um histórico único por pessoa em todos eles.",
      },
      {
        q: "Ele conecta na agenda que já usamos?",
        a: "Sim — o agente lê e escreve disponibilidade real em vez de manter uma cópia própria, então um horário agendado por telefone some da sua agenda na hora, e vice-versa.",
      },
      {
        q: "Quem consegue ver as conversas?",
        a: "Seu workspace, e mais ninguém. Cada registro é isolado por cliente no próprio banco de dados, não só na aplicação, e seus documentos nunca são usados para treinar um modelo compartilhado.",
      },
      {
        q: "Quanto custa?",
        a: "Uma mensalidade fixa de plataforma mais o uso — você paga pelos minutos e mensagens que seus agentes realmente atendem, com um teto diário por workspace definido por você para que uma campanha fora de controle não surpreenda.",
      },
    ],
  },
  footer: {
    rights: "Evara AI. Agentes que atendem, agendam e fazem o follow-up.",
    product: "Produto",
    pricing: "Preços",
    support: "Suporte",
    login: "Entrar",
  },
};
