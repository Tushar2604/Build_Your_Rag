// New campaign — a full page rather than a modal.
//
// Creating a campaign means choosing an assistant, a mode, a number, a message,
// and a contact list, and then reading the list back before anything sends. A
// modal makes you scroll a small box to check a thousand numbers, and gives you
// nowhere to see the message and the recipients at once.
//
// Nothing sends here. The campaign is created `queued`, and the detail page has
// the Start button — so a mistyped message costs an edit, not a thousand
// messages.
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle, ArrowLeft, Check, Loader2, MessageSquare, Radio, Smartphone, Users,
} from "lucide-react";
import {
  BroadcastMode,
  CampaignSender,
  createBroadcast,
  listCampaignSenders,
} from "../api/broadcasts";
import { Chatbot, listChatbots } from "../api/chatbots";
import { ApiError } from "../api/client";
import ContactPicker from "../components/ContactPicker";

const MAX_MESSAGE = 1600;

const MODES: { id: BroadcastMode; label: string; description: string; icon: typeof Radio }[] = [
  {
    id: "broadcast",
    label: "Broadcast",
    description:
      "Send the message and stop. Replies are still recorded against the campaign, but the assistant does not answer them.",
    icon: Radio,
  },
  {
    id: "broadcast_reply",
    label: "Broadcast + Reply",
    description:
      "Send the message and let the assistant take the conversation from there — grounded in its knowledge base, with full multi-turn memory.",
    icon: MessageSquare,
  },
];

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[13.5px] font-semibold text-gray-900 mb-1.5">{label}</label>
      {hint && <p className="text-xs text-gray-500 mb-2 leading-relaxed">{hint}</p>}
      {children}
    </div>
  );
}

export default function BroadcastCreatePage() {
  const navigate = useNavigate();

  const [assistants, setAssistants] = useState<Chatbot[]>([]);
  const [senders, setSenders] = useState<CampaignSender[]>([]);
  const [loading, setLoading] = useState(true);

  const [chatbotId, setChatbotId] = useState("");
  const [mode, setMode] = useState<BroadcastMode>("broadcast_reply");
  const [senderId, setSenderId] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  // Arrives when the WhatsApp inbox hands over a set of selected threads, so
  // the operator does not retype numbers they were just looking at.
  const handover = (useLocation().state ?? {}) as {
    contacts?: string;
    senderSessionId?: string;
  };
  const [contacts, setContacts] = useState(handover.contacts ?? "");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listChatbots(), listCampaignSenders().catch(() => [])])
      .then(([bots, availableSenders]) => {
        setAssistants(bots);
        setSenders(availableSenders);
        if (bots[0]) setChatbotId(bots[0].id);
        // Prefer the number the contacts came from; the campaign should send
        // from the same WhatsApp the operator was reading.
        const handedOver = handover.senderSessionId
          ? availableSenders.find((s) => s.id === handover.senderSessionId && s.available)
          : undefined;
        const chosen = handedOver ?? availableSenders.find((s) => s.available);
        if (chosen) setSenderId(`${chosen.kind}:${chosen.id}`);
      })
      .catch(() => setError("Could not load assistants and numbers."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedSender = useMemo(
    () => senders.find((s) => `${s.kind}:${s.id}` === senderId) ?? null,
    [senders, senderId],
  );
  const usableSenders = senders.filter((s) => s.available);

  const canSubmit =
    !!chatbotId && !!name.trim() && !!message.trim() && !!selectedSender?.available && !saving;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !selectedSender) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createBroadcast({
        chatbot_id: chatbotId,
        name: name.trim(),
        message_template: message.trim(),
        recipients_text: contacts,
        mode,
        sender_kind: selectedSender.kind,
        sender_id: selectedSender.id,
      });
      navigate(`/broadcasts/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the campaign.");
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-8 space-y-4">
        <div className="skeleton h-8 w-64" />
        <div className="skeleton h-40 rounded-2xl" />
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="max-w-4xl mx-auto px-8 py-8 animate-fade-in space-y-5">
      <header>
        <Link
          to="/broadcasts"
          className="inline-flex items-center gap-1.5 text-[13px] text-gray-500 hover:text-gray-300 mb-3"
        >
          <ArrowLeft className="w-4 h-4" strokeWidth={2} />
          Campaigns
        </Link>
        <h1 className="text-[28px] font-bold text-gray-900 tracking-tight">New campaign</h1>
        <p className="text-[14.5px] text-gray-500 mt-1">
          Nothing sends until you press Start on the next screen.
        </p>
      </header>

      {assistants.length === 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3.5 text-[13px] text-amber-900">
          You need an assistant before you can run a campaign —{" "}
          <Link to="/assistants" className="underline font-medium">
            create one first
          </Link>
          .
        </div>
      )}

      {/* ── Mode ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <h2 className="text-[15px] font-semibold text-gray-900 mb-1">Mode</h2>
        <p className="text-xs text-gray-500 mb-4">
          What happens when someone replies to this campaign.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {MODES.map((m) => {
            const Icon = m.icon;
            const active = mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setMode(m.id)}
                aria-pressed={active}
                className={`text-left rounded-xl border p-4 transition-colors ${
                  active
                    ? "border-brand-500 bg-brand-500/[0.07]"
                    : "border-gray-200 bg-surface-2 hover:border-gray-300"
                }`}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <Icon
                    className={`w-4 h-4 ${active ? "text-brand-400" : "text-gray-500"}`}
                    strokeWidth={1.75}
                  />
                  <span
                    className={`text-[14px] font-semibold ${active ? "text-brand-400" : "text-gray-900"}`}
                  >
                    {m.label}
                  </span>
                  {active && <Check className="w-4 h-4 text-brand-400 ml-auto" strokeWidth={2.5} />}
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">{m.description}</p>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Assistant + sender ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5 space-y-4">
        <Field
          label="Assistant"
          hint={
            mode === "broadcast_reply"
              ? "This assistant answers the replies, using its own knowledge base."
              : "Used to compose the conversation record. It will not answer replies in Broadcast mode."
          }
        >
          <select
            className="input"
            value={chatbotId}
            onChange={(e) => setChatbotId(e.target.value)}
            disabled={assistants.length === 0}
          >
            {assistants.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.display_id ? ` · #${a.display_id}` : ""}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Send from"
          hint="A Cloud API business number, or a personal WhatsApp linked by QR under WhatsApp Numbers."
        >
          {senders.length === 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
              No WhatsApp number is connected yet. Add a Cloud API number under{" "}
              <Link to="/channels" className="underline font-medium">
                Phone Numbers
              </Link>
              , or link your phone under{" "}
              <Link to="/channels?tab=whatsapp" className="underline font-medium">
                WhatsApp Numbers
              </Link>
              .
            </div>
          ) : (
            <div className="space-y-2">
              {senders.map((s) => {
                const value = `${s.kind}:${s.id}`;
                const active = senderId === value;
                return (
                  <label
                    key={value}
                    className={`flex items-start gap-3 rounded-xl border px-4 py-3 transition-colors ${
                      !s.available
                        ? "border-gray-200 bg-surface-2 opacity-60 cursor-not-allowed"
                        : active
                          ? "border-brand-500 bg-brand-500/[0.07] cursor-pointer"
                          : "border-gray-200 bg-surface-2 hover:border-gray-300 cursor-pointer"
                    }`}
                  >
                    <input
                      type="radio"
                      name="sender"
                      className="mt-1 w-4 h-4 text-brand-600 focus:ring-brand-500"
                      value={value}
                      checked={active}
                      disabled={!s.available}
                      onChange={() => setSenderId(value)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 flex-wrap">
                        <Smartphone className="w-3.5 h-3.5 text-gray-500" strokeWidth={1.75} />
                        <span className="text-[13.5px] font-medium text-gray-900">
                          {s.phone_number || "Personal WhatsApp"}
                        </span>
                        <span className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] font-semibold text-gray-500">
                          {s.kind === "cloud_api" ? "Cloud API" : "Phone WhatsApp"}
                        </span>
                      </span>
                      {s.chatbot_name && (
                        <span className="block text-xs text-gray-500 mt-1">
                          Currently answering as {s.chatbot_name}
                        </span>
                      )}
                      {!s.available && s.unavailable_reason && (
                        <span className="block text-xs text-amber-700 mt-1">
                          {s.unavailable_reason}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </Field>
      </section>

      {/* ── Message ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5 space-y-4">
        <Field label="Campaign name" hint="Only you see this — it labels the campaign in your list.">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={160}
            placeholder="March re-engagement"
          />
        </Field>

        <Field
          label="Message"
          hint="Placeholders are filled per contact: {{name}}, {{first_name}}, {{phone}}. An unknown placeholder is left visible rather than blanked, so a typo is obvious in a test send."
        >
          <textarea
            className="input resize-y text-[13.5px] leading-relaxed bg-surface-2"
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={MAX_MESSAGE}
            placeholder="Hi {{first_name}}, we're running a special this month — want the details?"
          />
          <p className="text-[11px] text-gray-500 text-right mt-1 tabular-nums">
            {message.length}/{MAX_MESSAGE}
          </p>
        </Field>
      </section>

      {/* ── Contacts ── */}
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <Field
          label="Contacts"
          hint="Paste them, upload a CSV, or pick from a linked WhatsApp. Numbers must include the country code — a local-looking number is skipped rather than guessed at, because a wrong guess messages a stranger."
        >
          <ContactPicker
            value={contacts}
            onChange={setContacts}
            sessionId={handover.senderSessionId}
          />
        </Field>
        {!contacts.trim() && (
          <p className="text-[13px] text-gray-500 mt-2 flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5" strokeWidth={1.75} />
            No contacts yet — you can add them on the next screen too.
          </p>
        )}
      </section>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-4 pb-4">
        <p className="text-xs text-gray-500 flex items-center gap-1.5 min-w-0">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={1.75} />
          Created paused. Review the contact list, then press Start.
        </p>
        <div className="flex items-center gap-3 flex-shrink-0">
          <Link to="/broadcasts" className="btn-secondary">
            Cancel
          </Link>
          <button
            type="submit"
            disabled={!canSubmit || usableSenders.length === 0}
            className="btn-primary px-5"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                Creating…
              </>
            ) : (
              "Create campaign"
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
