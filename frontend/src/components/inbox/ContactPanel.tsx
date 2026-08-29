// The right-hand pane: who this contact is, what the team has said about them
// internally, and what has happened on the thread.
//
// Three tabs rather than one long column because they answer different
// questions and are consulted at different moments — you read Details while
// composing a reply, Notes before handing the thread to someone else, and
// Activity when working out why it looks the way it does.
import { useEffect, useRef, useState } from "react";
import {
  Bot, Building2, Check, Globe, Link2, Mail, MapPin, Pencil, Phone, Send,
  Trash2, User, X,
} from "lucide-react";

import { ApiError } from "../../api/client";
import {
  ConversationNote,
  ConversationPatch,
  InboxConversation,
  InboxMessage,
  addNote,
  deleteNote,
  listNotes,
} from "../../api/whatsappInbox";
import { Avatar, clockLabel, dayLabel } from "../ConversationThread";

type Tab = "details" | "notes" | "activity";

/** Fields the card edits, in the order they are read. `icon` doubles as the
 * label in the collapsed row, which is why every one of them has to be
 * unambiguous on its own. */
const FIELDS: {
  key: keyof ConversationPatch & keyof InboxConversation;
  label: string;
  icon: typeof User;
  placeholder: string;
  type?: string;
}[] = [
  { key: "company", label: "Company", icon: Building2, placeholder: "Company name" },
  { key: "job_title", label: "Role", icon: User, placeholder: "Job title" },
  { key: "email", label: "Email", icon: Mail, placeholder: "name@company.com", type: "email" },
  { key: "country", label: "Country", icon: Globe, placeholder: "Country" },
  { key: "city", label: "City", icon: MapPin, placeholder: "City" },
  { key: "linkedin_url", label: "LinkedIn", icon: Link2, placeholder: "linkedin.com/in/…" },
  { key: "source", label: "Source", icon: Bot, placeholder: "Where they came from" },
];

/**
 * A rough "is this address plausible" score.
 *
 * Deliberately local and deliberately modest: it is a nudge about a field
 * somebody typed, not a verification. Nothing here contacts a mail server, so
 * it must never be presented as proof the address exists — hence "looks fine"
 * rather than "valid", and hence the free-mail and role-address deductions,
 * which are about how useful the address is rather than whether it works.
 */
function emailQuality(email: string): { score: number; note: string } | null {
  const value = email.trim().toLowerCase();
  if (!value) return null;
  if (!/^[^\s@]+@[^\s@]+\.[a-z]{2,}$/.test(value)) {
    return { score: 0, note: "That doesn't look like an email address." };
  }
  const [local, domain] = value.split("@");
  let score = 100;
  const notes: string[] = [];
  const FREE = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "rediffmail.com"];
  if (FREE.includes(domain)) {
    score -= 15;
    notes.push("personal mailbox");
  }
  if (["info", "sales", "admin", "contact", "support", "hr"].includes(local)) {
    score -= 25;
    notes.push("shared role address");
  }
  if (local.length <= 2) {
    score -= 10;
    notes.push("very short local part");
  }
  return {
    score: Math.max(0, score),
    note: notes.length ? notes.join(", ") : "Looks like a working business address.",
  };
}

function Row({
  icon: Icon,
  value,
  href,
  muted,
}: {
  icon: typeof User;
  value: string;
  href?: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5 py-[5px]">
      <Icon className="h-[15px] w-[15px] flex-shrink-0 text-gray-400" strokeWidth={1.75} />
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="min-w-0 truncate text-[13px] text-brand-600 hover:underline"
        >
          {value}
        </a>
      ) : (
        <span
          className={`min-w-0 truncate text-[13px] ${muted ? "text-gray-400" : "text-gray-800"}`}
        >
          {value}
        </span>
      )}
    </div>
  );
}

function DetailsTab({
  conversation,
  onPatch,
}: {
  conversation: InboxConversation;
  onPatch: (patch: ConversationPatch) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ConversationPatch>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");

  // Dropping the draft when the selection changes is what stops half-typed
  // details from one contact being saved onto the next one.
  useEffect(() => {
    setEditing(false);
    setDraft({});
    setError(null);
  }, [conversation.id]);

  function startEditing() {
    setDraft({
      display_name: conversation.display_name,
      company: conversation.company,
      job_title: conversation.job_title,
      email: conversation.email,
      city: conversation.city,
      country: conversation.country,
      linkedin_url: conversation.linkedin_url,
      source: conversation.source,
    });
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onPatch(draft);
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save those details.");
    } finally {
      setSaving(false);
    }
  }

  async function addTag() {
    const tag = tagInput.trim();
    if (!tag) return;
    setTagInput("");
    await onPatch({ tags: [...conversation.tags, tag] });
  }

  const quality = emailQuality(conversation.email);

  return (
    <div className="space-y-5 px-4 py-4">
      {/* Identity */}
      <div className="flex items-start gap-3">
        <Avatar name={conversation.display_name} phone={conversation.phone_number} size={44} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-gray-900">
            {conversation.display_name || conversation.phone_number}
          </p>
          <p className="truncate text-[12.5px] text-gray-500">
            {conversation.job_title || "No role recorded"}
          </p>
        </div>
        <button
          type="button"
          onClick={editing ? () => setEditing(false) : startEditing}
          aria-label={editing ? "Stop editing" : "Edit contact details"}
          className="icon-btn flex-shrink-0"
        >
          {editing ? (
            <X className="h-4 w-4" strokeWidth={2} />
          ) : (
            <Pencil className="h-4 w-4" strokeWidth={2} />
          )}
        </button>
      </div>

      {/* Contact */}
      <section>
        <p className="eyebrow mb-1.5">Contact</p>
        {editing ? (
          <div className="space-y-2">
            <input
              className="input h-9 text-[13px]"
              placeholder="Display name"
              value={draft.display_name ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, display_name: e.target.value }))}
            />
            {FIELDS.map((f) => (
              <input
                key={f.key}
                className="input h-9 text-[13px]"
                type={f.type || "text"}
                placeholder={f.placeholder}
                aria-label={f.label}
                value={(draft[f.key] as string) ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              />
            ))}
            {error && <p className="text-[12px] text-red-600">{error}</p>}
            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="btn-primary btn-sm flex-1"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="btn-secondary btn-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="-mt-0.5">
            <Row icon={Phone} value={conversation.phone_number} />
            {conversation.company && <Row icon={Building2} value={conversation.company} />}
            {conversation.job_title && <Row icon={User} value={conversation.job_title} />}
            {conversation.email ? (
              <Row icon={Mail} value={conversation.email} href={`mailto:${conversation.email}`} />
            ) : (
              <Row icon={Mail} value="No email recorded" muted />
            )}
            {conversation.country && <Row icon={Globe} value={conversation.country} />}
            {conversation.city && <Row icon={MapPin} value={conversation.city} />}
            {conversation.linkedin_url && (
              <Row
                icon={Link2}
                value={conversation.linkedin_url.replace(/^https?:\/\//, "")}
                href={
                  conversation.linkedin_url.startsWith("http")
                    ? conversation.linkedin_url
                    : `https://${conversation.linkedin_url}`
                }
              />
            )}
            <Row
              icon={Bot}
              value={`Source: ${conversation.source || "WhatsApp Inbound"}`}
              muted={!conversation.source}
            />
          </div>
        )}
      </section>

      {/* Email quality — only where there is an address to say something about */}
      {quality && (
        <section>
          <p className="eyebrow mb-1.5">Email Quality</p>
          <div className="rounded-xl border border-gray-200 bg-surface-2 px-3.5 py-3">
            <div className="flex items-baseline justify-between">
              <span className="text-[12.5px] text-gray-600">Score</span>
              <span className="text-[20px] font-bold tabular-nums text-gray-900">
                {quality.score}
                <span className="text-[12px] font-medium text-gray-400"> / 100</span>
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200">
              <div
                className={`h-full rounded-full ${
                  quality.score >= 80
                    ? "bg-emerald-500"
                    : quality.score >= 50
                      ? "bg-amber-500"
                      : "bg-red-500"
                }`}
                style={{ width: `${quality.score}%` }}
              />
            </div>
            <p className="mt-2 text-[11.5px] leading-snug text-gray-500">{quality.note}</p>
            {/* Said plainly, because a number in a box invites more trust than
                a local regex has earned. */}
            <p className="mt-1 text-[11px] text-gray-400">
              Checked by format only — nothing was sent to this address.
            </p>
          </div>
        </section>
      )}

      {/* Tags */}
      <section>
        <p className="eyebrow mb-1.5">Tags</p>
        <div className="flex flex-wrap gap-1.5">
          {conversation.tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5
                         text-[11px] font-semibold text-brand-700"
            >
              {tag}
              <button
                type="button"
                aria-label={`Remove tag ${tag}`}
                onClick={() => onPatch({ tags: conversation.tags.filter((t) => t !== tag) })}
                className="text-brand-500 hover:text-brand-800"
              >
                <X className="h-3 w-3" strokeWidth={2.5} />
              </button>
            </span>
          ))}
          {conversation.tags.length === 0 && (
            <span className="text-[12px] text-gray-400">No tags yet.</span>
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void addTag();
          }}
          className="mt-2 flex gap-1.5"
        >
          <input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            placeholder="Add a tag…"
            aria-label="Add a tag"
            maxLength={40}
            className="input h-8 flex-1 text-[12.5px]"
          />
          <button
            type="submit"
            disabled={!tagInput.trim()}
            aria-label="Add tag"
            className="icon-btn h-8 w-8 flex-shrink-0 disabled:opacity-40"
          >
            <Check className="h-4 w-4" strokeWidth={2} />
          </button>
        </form>
      </section>
    </div>
  );
}

function NotesTab({
  conversationId,
  notes,
  onChanged,
}: {
  conversationId: string;
  notes: ConversationNote[];
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await addNote(conversationId, body);
      setDraft("");
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save that note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    // No scroller of its own: the panel that hosts the tabs already scrolls,
    // and a second one inside it means a mouse wheel does nothing until the
    // pointer happens to be over the right half of the pane.
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="border-b border-gray-200 p-3"
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          maxLength={2000}
          aria-label="Add an internal note"
          placeholder="Note for your team — the contact never sees this."
          className="input resize-none text-[13px]"
        />
        {error && <p className="mt-1 text-[12px] text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="btn-primary btn-sm mt-2 w-full"
        >
          <Send className="h-3.5 w-3.5" strokeWidth={2} />
          {busy ? "Saving…" : "Add note"}
        </button>
      </form>

      <div className="space-y-2 p-3">
        {notes.length === 0 && (
          <p className="py-6 text-center text-[12.5px] text-gray-400">
            No notes yet. Anything you write here stays inside your team.
          </p>
        )}
        {notes.map((note) => (
          <div key={note.id} className="rounded-xl border border-gray-200 bg-surface-2 p-3">
            <p className="whitespace-pre-wrap break-words text-[13px] leading-snug text-gray-800">
              {note.body}
            </p>
            <div className="mt-2 flex items-center gap-2 text-[11px] text-gray-400">
              <span className="truncate">{note.author_email || "Someone"}</span>
              <span aria-hidden="true">·</span>
              <span className="flex-shrink-0">
                {dayLabel(note.created_at)} {clockLabel(note.created_at)}
              </span>
              <button
                type="button"
                aria-label="Delete note"
                onClick={async () => {
                  await deleteNote(conversationId, note.id);
                  onChanged();
                }}
                className="ml-auto flex-shrink-0 text-gray-400 hover:text-red-600"
              >
                <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Derived from the thread rather than a separate event log: every fact worth
 * showing here — first contact, who has been answering, when they last replied
 * — is already in the messages, and a second source of truth would only give
 * the two of them a way to disagree. */
function ActivityTab({
  conversation,
  messages,
}: {
  conversation: InboxConversation;
  messages: InboxMessage[];
}) {
  const inbound = messages.filter((m) => m.direction === "in");
  const outbound = messages.filter((m) => m.direction === "out");
  const byAssistant = outbound.filter((m) => m.author === "assistant").length;
  const first = messages[0];
  const lastInbound = inbound[inbound.length - 1];

  const entries: { label: string; value: string }[] = [
    {
      label: "Thread opened",
      value: first ? `${dayLabel(first.created_at)} ${clockLabel(first.created_at)}` : "—",
    },
    {
      label: "Last reply from contact",
      value: lastInbound
        ? `${dayLabel(lastInbound.created_at)} ${clockLabel(lastInbound.created_at)}`
        : "They haven't replied yet",
    },
    { label: "Messages received", value: String(inbound.length) },
    { label: "Messages sent", value: String(outbound.length) },
    { label: "Answered by the assistant", value: String(byAssistant) },
    {
      label: "Attachments",
      value: String(messages.filter((m) => m.media_kind).length),
    },
    { label: "Status", value: conversation.status === "open" ? "Open" : "Closed" },
    {
      label: "Replying",
      value: conversation.auto_reply ? "Assistant" : "A person on your team",
    },
    { label: "Owner", value: conversation.assignee_email || "Unassigned" },
  ];

  return (
    <dl className="divide-y divide-gray-200 px-4">
      {entries.map((e) => (
        <div key={e.label} className="flex items-baseline justify-between gap-3 py-2.5">
          <dt className="text-[12.5px] text-gray-500">{e.label}</dt>
          <dd className="min-w-0 truncate text-right text-[12.5px] font-medium text-gray-800">
            {e.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function ContactPanel({
  conversation,
  messages,
  onPatch,
}: {
  conversation: InboxConversation;
  messages: InboxMessage[];
  onPatch: (patch: ConversationPatch) => Promise<void>;
}) {
  const [tab, setTab] = useState<Tab>("details");
  const [notes, setNotes] = useState<ConversationNote[]>([]);
  // Guards the response of a request for the previous contact landing after the
  // selection has already moved on.
  const wantedId = useRef(conversation.id);

  function reloadNotes() {
    wantedId.current = conversation.id;
    const asked = conversation.id;
    listNotes(asked)
      .then((n) => {
        if (wantedId.current === asked) setNotes(n);
      })
      .catch(() => setNotes([]));
  }

  useEffect(reloadNotes, [conversation.id]);

  const TABS: { key: Tab; label: string }[] = [
    { key: "details", label: "Details" },
    { key: "notes", label: notes.length ? `Notes (${notes.length})` : "Notes" },
    { key: "activity", label: "Activity" },
  ];

  return (
    <aside
      aria-label="Contact details"
      className="hidden w-[320px] flex-shrink-0 flex-col border-l border-gray-200 bg-surface xl:flex"
    >
      <div className="flex-shrink-0 p-2.5">
        <div className="segmented w-full">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              aria-pressed={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 ${tab === t.key ? "segmented-item-active" : "segmented-item"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "details" && <DetailsTab conversation={conversation} onPatch={onPatch} />}
        {tab === "notes" && (
          <NotesTab
            conversationId={conversation.id}
            notes={notes}
            onChanged={reloadNotes}
          />
        )}
        {tab === "activity" && (
          <ActivityTab conversation={conversation} messages={messages} />
        )}
      </div>
    </aside>
  );
}
