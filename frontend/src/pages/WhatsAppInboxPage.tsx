// WhatsApp inbox — the chat window for a QR-linked personal number.
//
// Laid out as a messenger rather than as two cards on a page: a fixed-width
// thread rail against a full-bleed conversation, panes butted together with a
// single hairline between them. That is the shape every user already has
// muscle memory for, and it is the only layout where the message list can own
// the full height of the viewport.
//
// It polls rather than holding a socket, matching the rest of the app and
// surviving the free-tier host sleeping mid-view.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Bot, Check, CheckCheck, FileText, Image as ImageIcon, Mic,
  Paperclip, Search, Send, Sparkles, User, Video,
} from "lucide-react";

import { ApiError } from "../api/client";
import {
  InboxConversation,
  InboxMessage,
  MessageAuthor,
  fetchMediaObjectUrl,
  listConversations,
  listMessages,
  markRead,
  sendMessage,
  setAutoReply,
} from "../api/whatsappInbox";
import { WhatsAppWebSession, listWebSessions } from "../api/whatsappWeb";

const POLL_MS = 4000;

type FilterKey = "all" | "unread" | "attachments" | "takeover";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "attachments", label: "Media" },
  { key: "takeover", label: "Assistant off" },
];

/** Filter chips map onto query params rather than filtering client-side, so a
 * thread on page 2 still matches. */
function filterParams(key: FilterKey) {
  switch (key) {
    case "unread":
      return { unreadOnly: true };
    case "attachments":
      return { hasAttachment: true };
    case "takeover":
      return { autoReply: false };
    default:
      return {};
  }
}

function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso);
  const sameDay = new Date().toDateString() === then.toDateString();
  return sameDay
    ? then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : then.toLocaleDateString([], { day: "numeric", month: "short" });
}

function clockLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** "Today" / "Yesterday" / a date — the separator between days in a thread. */
function dayLabel(iso: string): string {
  const then = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (then.toDateString() === today.toDateString()) return "Today";
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  return then.toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
}

function sizeLabel(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const KIND_ICON = {
  image: ImageIcon,
  video: Video,
  audio: Mic,
  document: FileText,
  sticker: Sparkles,
} as const;

function MediaIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = KIND_ICON[kind as keyof typeof KIND_ICON] || Paperclip;
  return <Icon className={className} strokeWidth={1.75} />;
}

/** Deterministic avatar tint, so the same contact is the same colour every
 * time the list loads. Nine hues, keyed off the number rather than the name —
 * a contact can be renamed, their number cannot. */
const AVATAR_TINTS = [
  "from-violet-500 to-purple-600",
  "from-sky-500 to-blue-600",
  "from-emerald-500 to-teal-600",
  "from-amber-500 to-orange-600",
  "from-rose-500 to-pink-600",
  "from-indigo-500 to-violet-600",
  "from-cyan-500 to-sky-600",
  "from-fuchsia-500 to-purple-600",
  "from-lime-500 to-emerald-600",
];

function tintFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_TINTS[Math.abs(hash) % AVATAR_TINTS.length];
}

function initialsFor(name: string, phone: string): string {
  const source = name.trim() || phone.replace(/[^0-9]/g, "");
  if (!source) return "?";
  const words = source.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function Avatar({
  name,
  phone,
  size = 44,
}: {
  name: string;
  phone: string;
  size?: number;
}) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.34 }}
      className={`flex-shrink-0 inline-flex items-center justify-center rounded-full
                  bg-gradient-to-br ${tintFor(phone)} font-semibold text-white
                  tracking-tight select-none`}
    >
      {initialsFor(name, phone)}
    </span>
  );
}

/** Renders an attachment. Images are fetched as object URLs because the media
 * endpoint needs an Authorization header that `<img src>` cannot send. */
function Attachment({
  conversationId,
  message,
  outgoing,
}: {
  conversationId: string;
  message: InboxMessage;
  outgoing: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const isImage = message.media_kind === "image" || message.media_kind === "sticker";
  // On the green outgoing bubble a neutral tint disappears; on the light
  // incoming one a white one does.
  const chip = outgoing ? "bg-black/15 hover:bg-black/25" : "bg-gray-900/[0.06] hover:bg-gray-900/[0.12]";

  useEffect(() => {
    if (!isImage || !message.media_available) return;
    let revoked: string | null = null;
    let active = true;
    fetchMediaObjectUrl(conversationId, message.id)
      .then((objectUrl) => {
        if (!active) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        revoked = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => setFailed(true));
    return () => {
      active = false;
      // Without this every image scrolled past stays in memory for the tab's life.
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [conversationId, message.id, message.media_available, isImage]);

  if (!message.media_available) {
    return (
      <div className={`flex items-center gap-2 rounded-xl ${chip} px-3 py-2 text-[11px] italic opacity-80`}>
        <MediaIcon kind={message.media_kind} className="w-3.5 h-3.5" />
        {message.media_kind || "attachment"} — not stored
      </div>
    );
  }

  if (isImage) {
    if (failed) return <div className="text-[11px] italic opacity-80">Image unavailable</div>;
    if (!url) return <div className="skeleton h-44 w-60 rounded-xl" />;
    return (
      <a href={url} target="_blank" rel="noreferrer" className="block">
        <img
          src={url}
          alt={message.media_filename || "Attachment"}
          className="max-h-72 rounded-xl object-cover"
        />
      </a>
    );
  }

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          const objectUrl = await fetchMediaObjectUrl(conversationId, message.id);
          const a = document.createElement("a");
          a.href = objectUrl;
          a.download = message.media_filename || `${message.media_kind}-${message.id}`;
          a.click();
          URL.revokeObjectURL(objectUrl);
        } catch {
          setFailed(true);
        }
      }}
      className={`flex w-full items-center gap-2.5 rounded-xl ${chip} px-3 py-2.5 text-left
                  text-[12px] transition-colors`}
    >
      <MediaIcon kind={message.media_kind} className="w-4 h-4 flex-shrink-0" />
      <span className="truncate max-w-[14rem] font-medium">
        {message.media_filename || message.media_kind}
      </span>
      <span className="opacity-70 tabular-nums ml-auto">{sizeLabel(message.media_size_bytes)}</span>
      {failed && <span className="text-red-200">failed</span>}
    </button>
  );
}

/** The small tag on an outgoing bubble saying who wrote it. Only shown for the
 * assistant: an operator reading their own inbox knows which ones they typed,
 * but "did the agent actually answer?" is the question this page exists to
 * settle. */
function AuthorTag({ author }: { author: MessageAuthor }) {
  if (author !== "assistant") return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-black/15 px-1.5 py-0.5
                     text-[9.5px] font-semibold uppercase tracking-wide">
      <Bot className="w-2.5 h-2.5" strokeWidth={2.5} />
      AI
    </span>
  );
}

export default function WhatsAppInboxPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();

  const [session, setSession] = useState<WhatsAppWebSession | null>(null);
  const [conversations, setConversations] = useState<InboxConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const selected = useMemo(
    () => conversations.find((c) => c.id === selectedId) || null,
    [conversations, selectedId],
  );

  useEffect(() => {
    listWebSessions()
      .then((all) => setSession(all.find((s) => s.id === sessionId) || null))
      .catch(() => setSession(null));
  }, [sessionId]);

  const loadConversations = useCallback(async () => {
    try {
      const page = await listConversations(sessionId, {
        search: search.trim(),
        ...filterParams(filter),
        pageSize: 50,
      });
      setConversations(page.conversations);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load conversations.");
    } finally {
      setLoading(false);
    }
  }, [sessionId, search, filter]);

  const loadMessages = useCallback(async () => {
    if (!selectedId) return;
    try {
      setMessages(await listMessages(selectedId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load this conversation.");
    }
  }, [selectedId]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  // One timer for both panes. Skipped while the tab is hidden so a backgrounded
  // inbox is not polling a sleeping free-tier instance awake.
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return;
      void loadConversations();
      void loadMessages();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [loadConversations, loadMessages]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  // The composer grows with the draft up to a cap, the way every messenger's
  // does — a fixed one-line box makes a three-line reply unreadable as you
  // type it.
  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [draft]);

  async function openConversation(conversation: InboxConversation) {
    setSelectedId(conversation.id);
    setMessages([]);
    if (conversation.unread_count > 0) {
      try {
        await markRead(conversation.id);
        setConversations((prev) =>
          prev.map((c) => (c.id === conversation.id ? { ...c, unread_count: 0 } : c)),
        );
      } catch {
        // A failed read receipt is cosmetic; the thread still opens.
      }
    }
  }

  async function toggleTakeover() {
    if (!selected) return;
    const next = !selected.auto_reply;
    try {
      const updated = await setAutoReply(selected.id, next);
      setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change who replies.");
    }
  }

  async function submitReply() {
    const text = draft.trim();
    if (!text || !selected || sending) return;
    setSending(true);
    setError(null);
    try {
      const sent = await sendMessage(selected.id, text);
      setMessages((prev) => [...prev, sent]);
      setDraft("");
      void loadConversations();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send the message.");
    } finally {
      setSending(false);
    }
  }

  function startCampaign() {
    const contacts = conversations
      .filter((c) => checked.has(c.id))
      .map((c) => (c.display_name ? `${c.phone_number}, ${c.display_name}` : c.phone_number))
      .join("\n");
    // Handed to the existing campaign flow rather than duplicating it here.
    navigate("/broadcasts/new", { state: { contacts, senderSessionId: sessionId } });
  }

  function toggleChecked(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Day separators are decided once per render rather than inside the map, so
  // the comparison is always against the previous *rendered* message.
  const withDays = useMemo(
    () =>
      messages.map((msg, i) => ({
        msg,
        day:
          i === 0 ||
          new Date(msg.created_at).toDateString() !==
            new Date(messages[i - 1].created_at).toDateString()
            ? dayLabel(msg.created_at)
            : null,
      })),
    [messages],
  );

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* ── Thread rail ──────────────────────────────────────────────────── */}
      <aside className="flex w-[360px] flex-shrink-0 flex-col border-r border-gray-200 bg-surface">
        <header className="flex-shrink-0 px-4 pt-4 pb-3">
          <div className="flex items-center gap-2">
            <Link
              to="/channels?tab=whatsapp"
              aria-label="Back to WhatsApp numbers"
              className="icon-btn -ml-1 flex-shrink-0"
            >
              <ArrowLeft className="w-[18px] h-[18px]" strokeWidth={2} />
            </Link>
            <div className="min-w-0 flex-1">
              <h1 className="truncate font-display text-[15px] font-semibold text-gray-900">
                {session?.phone_number || "WhatsApp inbox"}
              </h1>
              <p className="truncate text-[11px] text-gray-500">
                {total} chat{total === 1 ? "" : "s"}
                {session?.chatbot_name ? ` · ${session.chatbot_name}` : " · no assistant"}
              </p>
            </div>
            {session?.status === "linked" && (
              <span className="dot-live flex-shrink-0" title="Linked" aria-label="Linked" />
            )}
          </div>

          <div className="relative mt-3">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              strokeWidth={1.75}
            />
            <input
              className="input h-9 rounded-full pl-9 text-[13px]"
              placeholder="Search name, number or message…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {FILTERS.map((chip) => (
              <button
                key={chip.key}
                type="button"
                aria-pressed={filter === chip.key}
                onClick={() => setFilter(chip.key)}
                className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                  filter === chip.key
                    ? "bg-brand-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900"
                }`}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </header>

        {checked.size > 0 && (
          <div className="flex-shrink-0 border-y border-gray-200 bg-brand-500/10 px-4 py-2">
            <button type="button" onClick={startCampaign} className="btn-primary btn-sm w-full">
              Start campaign ({checked.size})
            </button>
          </div>
        )}

        <ul className="min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <li className="space-y-2 p-3">
              <div className="skeleton h-16 rounded-xl" />
              <div className="skeleton h-16 rounded-xl" />
              <div className="skeleton h-16 rounded-xl" />
            </li>
          )}
          {!loading && conversations.length === 0 && (
            <li className="px-6 py-12 text-center text-sm text-gray-500">
              {search || filter !== "all"
                ? "No chats match this filter."
                : "No messages yet. When someone messages this number, the chat appears here."}
            </li>
          )}
          {conversations.map((c) => {
            const active = c.id === selectedId;
            return (
              <li key={c.id} className="group relative">
                <button
                  type="button"
                  onClick={() => openConversation(c)}
                  aria-current={active ? "true" : undefined}
                  className={`flex w-full items-center gap-3 border-l-2 px-4 py-3 text-left transition-colors ${
                    active
                      ? "border-brand-500 bg-brand-500/10"
                      : "border-transparent hover:bg-gray-100"
                  }`}
                >
                  <Avatar name={c.display_name} phone={c.phone_number} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[14px] font-semibold text-gray-900">
                        {c.display_name || c.phone_number}
                      </span>
                      <span
                        className={`flex-shrink-0 text-[11px] tabular-nums ${
                          c.unread_count > 0 ? "font-semibold text-emerald-600" : "text-gray-400"
                        }`}
                      >
                        {timeLabel(c.last_message_at)}
                      </span>
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5">
                      {c.has_attachment && (
                        <Paperclip
                          className="w-3 h-3 flex-shrink-0 text-gray-400"
                          strokeWidth={2}
                          aria-label="Has attachment"
                        />
                      )}
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-gray-500">
                        {c.last_message_preview || "—"}
                      </span>
                      {!c.auto_reply && (
                        <span
                          title="A human is handling this chat"
                          className="flex-shrink-0 rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold text-amber-700"
                        >
                          manual
                        </span>
                      )}
                      {c.unread_count > 0 && (
                        <span className="flex h-[18px] min-w-[18px] flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-bold tabular-nums text-white">
                          {c.unread_count}
                        </span>
                      )}
                    </span>
                  </span>
                </button>

                {/* Selection for campaigns. Kept out of the row button (nesting
                    a control inside a button is invalid) and revealed on hover
                    so it does not compete with reading the list. */}
                <label
                  className={`absolute left-3 top-1/2 -translate-y-1/2 cursor-pointer rounded p-1
                              transition-opacity ${
                                checked.has(c.id)
                                  ? "opacity-100"
                                  : "opacity-0 focus-within:opacity-100 group-hover:opacity-100"
                              }`}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${c.display_name || c.phone_number} for a campaign`}
                    checked={checked.has(c.id)}
                    onChange={() => toggleChecked(c.id)}
                    className="h-4 w-4 accent-[rgb(var(--c-solid))]"
                  />
                </label>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* ── Conversation ─────────────────────────────────────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col bg-canvas">
        {error && (
          <div
            role="alert"
            className="flex-shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        {!selected ? (
          <div className="empty-state flex-1">
            <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-500/10 text-brand-600">
              <Bot className="h-8 w-8" strokeWidth={1.5} />
            </span>
            <p className="empty-state-title">Pick a chat to read it</p>
            <p className="empty-state-desc">
              {session?.chatbot_name
                ? `${session.chatbot_name} answers new messages on this number automatically. Open a chat to follow along, or take it over to reply yourself.`
                : "No assistant is attached to this number yet, so messages arrive but nothing replies. Attach one from WhatsApp Numbers."}
            </p>
          </div>
        ) : (
          <>
            <header className="flex flex-shrink-0 items-center gap-3 border-b border-gray-200 bg-surface px-5 py-2.5">
              <Avatar name={selected.display_name} phone={selected.phone_number} size={38} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-semibold text-gray-900">
                  {selected.display_name || selected.phone_number}
                </p>
                <p className="truncate text-[11.5px] text-gray-500">
                  {selected.phone_number}
                  {selected.auto_reply && session?.chatbot_name && (
                    <> · answered by {session.chatbot_name}</>
                  )}
                </p>
              </div>
              <span
                className={`hidden sm:inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                            text-[11px] font-semibold ${
                              selected.auto_reply
                                ? "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200"
                                : "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200"
                            }`}
              >
                {selected.auto_reply ? (
                  <><Bot className="w-3 h-3" strokeWidth={2.5} /> Assistant on</>
                ) : (
                  <><User className="w-3 h-3" strokeWidth={2.5} /> You're replying</>
                )}
              </span>
              <button
                type="button"
                onClick={toggleTakeover}
                className={`btn-sm flex-shrink-0 ${
                  selected.auto_reply ? "btn-secondary" : "btn-primary"
                }`}
              >
                {selected.auto_reply ? "Take over" : "Hand back"}
              </button>
            </header>

            {/* The message ground. A faint dot texture stands in for WhatsApp's
                wallpaper: enough to separate the bubbles from the page without
                competing with them, and it themes with everything else. */}
            <div
              ref={threadRef}
              className="min-h-0 flex-1 overflow-y-auto bg-dot-grid bg-dot-md px-5 py-5"
            >
              <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
                {messages.length === 0 && (
                  <p className="py-10 text-center text-sm text-gray-500">No messages yet.</p>
                )}
                {withDays.map(({ msg, day }) => {
                  const outgoing = msg.direction === "out";
                  return (
                    <div key={msg.id}>
                      {day && (
                        <div className="my-4 flex justify-center">
                          <span className="rounded-full bg-surface px-3 py-1 text-[11px] font-semibold text-gray-500 shadow-xs">
                            {day}
                          </span>
                        </div>
                      )}
                      <div className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`relative max-w-[78%] px-3 py-2 text-[14px] leading-snug shadow-xs sm:max-w-[68%] ${
                            outgoing
                              ? "rounded-2xl rounded-br-md bg-emerald-600 text-white"
                              : "rounded-2xl rounded-bl-md bg-surface text-gray-900"
                          }`}
                        >
                          {msg.media_kind && (
                            <div className="mb-1.5">
                              <Attachment
                                conversationId={selected.id}
                                message={msg}
                                outgoing={outgoing}
                              />
                            </div>
                          )}
                          {msg.content && (
                            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                          )}
                          <span
                            className={`mt-1 flex items-center justify-end gap-1.5 text-[10px] tabular-nums ${
                              outgoing ? "text-white/70" : "text-gray-400"
                            }`}
                          >
                            <AuthorTag author={msg.author} />
                            {clockLabel(msg.created_at)}
                            {outgoing &&
                              (msg.author === "assistant" ? (
                                <CheckCheck className="w-3.5 h-3.5" strokeWidth={2.5} />
                              ) : (
                                <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
                              ))}
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {!selected.auto_reply && (
              <p className="flex-shrink-0 border-t border-amber-200 bg-amber-50 px-5 py-2 text-[11.5px] text-amber-800">
                The assistant is paused for this chat — replies are yours to send.
              </p>
            )}

            <div className="flex flex-shrink-0 items-end gap-2 border-t border-gray-200 bg-surface px-4 py-3">
              <textarea
                ref={composerRef}
                rows={1}
                className="input min-h-[42px] flex-1 resize-none rounded-2xl py-2.5 text-[14px]"
                placeholder={
                  selected.auto_reply
                    ? "Type to reply yourself — the assistant keeps answering new messages"
                    : "Type a reply…"
                }
                value={draft}
                maxLength={4096}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void submitReply();
                  }
                }}
              />
              <button
                type="button"
                onClick={submitReply}
                disabled={sending || !draft.trim()}
                aria-label="Send reply"
                className="mb-px flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center
                           rounded-full bg-emerald-600 text-white shadow-xs transition-colors
                           hover:bg-emerald-700 disabled:opacity-40 disabled:hover:bg-emerald-600"
              >
                <Send className="w-[18px] h-[18px]" strokeWidth={2} />
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
