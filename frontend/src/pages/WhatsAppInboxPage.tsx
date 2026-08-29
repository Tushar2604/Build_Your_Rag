// WhatsApp inbox — the shared workspace for QR-linked numbers.
//
// Three panes under one counter strip: the thread rail, the conversation, and
// the contact. That is the shape of every shared inbox people already know, and
// it is the only one where all three questions a team asks at once — which
// thread, what was said, who is this — are answerable without navigating.
//
// Everything the team adds on top of WhatsApp's own data (owner, tags, pin,
// open/closed, contact card, internal notes) lives on the conversation row and
// is written through one PATCH, so two people working the same thread cannot
// clobber each other's unrelated edits.
//
// It polls rather than holding a socket, matching the rest of the app and
// surviving the free-tier host sleeping mid-view.
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Bot, Check, ChevronDown, MessageSquarePlus, MoreVertical, Paperclip,
  Pin, PinOff, Search, Send, User, UserPlus, X,
} from "lucide-react";

import { ApiError } from "../api/client";
import DictateButton from "../components/DictateButton";
import {
  ConversationPatch,
  InboxConversation,
  InboxMessage,
  InboxStats,
  assignConversation,
  getInboxStats,
  listConversations,
  listMessages,
  markRead,
  sendAttachment,
  sendMessage,
  updateConversation,
} from "../api/whatsappInbox";
import { TeamMember, getTeam } from "../api/team";
import { WhatsAppWebSession, listWebSessions } from "../api/whatsappWeb";
import { useAuth } from "../store/auth";
import InboxStatsBar from "../components/inbox/InboxStatsBar";
import ContactPanel from "../components/inbox/ContactPanel";
import {
  Avatar, ConversationThread, MediaIcon, sizeLabel, timeLabel,
} from "../components/ConversationThread";

const POLL_MS = 4000;

type FilterKey = "all" | "unread" | "mine" | "unassigned" | "attachments" | "takeover";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "mine", label: "Assigned to Me" },
  { key: "unassigned", label: "Unassigned" },
  { key: "attachments", label: "Media" },
  { key: "takeover", label: "Assistant off" },
];

/** Filter chips map onto query params rather than filtering client-side, so a
 * thread on page 2 still matches. */
function filterParams(key: FilterKey) {
  switch (key) {
    case "unread":
      return { unreadOnly: true };
    case "mine":
      return { assignedToMe: true };
    case "unassigned":
      return { unassigned: true };
    case "attachments":
      return { hasAttachment: true };
    case "takeover":
      return { autoReply: false };
    default:
      return {};
  }
}

/** "zara.ahmed@acme.com" -> "ZA". The avatar for a teammate, who is identified
 * by an email address and nothing else. */
function memberInitials(email: string): string {
  const local = email.split("@")[0] || email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

function memberName(email: string): string {
  const local = email.split("@")[0] || email;
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

/** The small circle standing in for whoever owns a thread. */
function AssigneeChip({ email, size = 22 }: { email: string; size?: number }) {
  return (
    <span
      title={email}
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      className="inline-flex flex-shrink-0 items-center justify-center rounded-full
                 bg-brand-500/15 font-bold uppercase tracking-tight text-brand-700"
    >
      {memberInitials(email)}
    </span>
  );
}

/** A menu anchored to its trigger, dismissed by clicking anywhere else. Small
 * enough not to be worth a dependency, and used three times on this page. */
function Menu({
  open,
  onClose,
  children,
  align = "right",
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  useEffect(() => {
    if (!open) return;
    // Deferred to the next tick so the click that opened the menu doesn't
    // immediately close it again.
    const id = window.setTimeout(() => document.addEventListener("click", onClose), 0);
    return () => {
      window.clearTimeout(id);
      document.removeEventListener("click", onClose);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      role="menu"
      onClick={(e) => e.stopPropagation()}
      className={`chrome-popover animate-scale-in absolute top-full z-30 mt-1.5 min-w-[200px]
                  overflow-hidden rounded-xl p-1.5 ${align === "right" ? "right-0" : "left-0"}`}
    >
      {children}
    </div>
  );
}

function MenuItem({
  onClick,
  icon: Icon,
  children,
  danger,
}: {
  onClick: () => void;
  icon?: typeof User;
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`chrome-popover-item flex w-full items-center gap-2.5 rounded-lg px-3 py-2
                  text-left text-[13px] ${danger ? "text-red-600" : ""}`}
    >
      {Icon && <Icon className="h-4 w-4 flex-shrink-0 text-gray-500" strokeWidth={1.75} />}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}

export default function WhatsAppInboxPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const { email: myEmail } = useAuth();

  const [sessions, setSessions] = useState<WhatsAppWebSession[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [stats, setStats] = useState<InboxStats | null>(null);
  const [conversations, setConversations] = useState<InboxConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const [threadSearchOpen, setThreadSearchOpen] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [numberMenu, setNumberMenu] = useState(false);
  const [assignMenu, setAssignMenu] = useState(false);
  const [threadMenu, setThreadMenu] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const session = useMemo(
    () => sessions.find((s) => s.id === sessionId) || null,
    [sessions, sessionId],
  );
  const selected = useMemo(
    () => conversations.find((c) => c.id === selectedId) || null,
    [conversations, selectedId],
  );

  useEffect(() => {
    listWebSessions().then(setSessions).catch(() => setSessions([]));
    // Admin-only, like this page. A failure just means the assign menu offers
    // nobody, which is better than the page refusing to render.
    getTeam()
      .then((t) => setTeam(t.members.filter((mem) => mem.is_active)))
      .catch(() => setTeam([]));
  }, []);

  const loadStats = useCallback(() => {
    getInboxStats().then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(loadStats, [loadStats]);

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

  // One timer for all three. Skipped while the tab is hidden so a backgrounded
  // inbox is not polling a sleeping free-tier instance awake.
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.hidden) return;
      void loadConversations();
      void loadMessages();
      loadStats();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [loadConversations, loadMessages, loadStats]);

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

  /** Apply a change locally and on the server at once. Optimistic because
   * every one of these is a toggle someone just clicked, and a 4s poll is far
   * too long to wait to see a pin move. */
  const patchSelected = useCallback(
    async (patch: ConversationPatch) => {
      if (!selectedId) return;
      try {
        const updated = await updateConversation(selectedId, patch);
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not save that change.");
        // Re-read rather than guess: the row on screen is now out of step with
        // the server, and only one of them is right.
        void loadConversations();
        throw e;
      }
    },
    [selectedId, loadConversations],
  );

  async function openConversation(conversation: InboxConversation) {
    setSelectedId(conversation.id);
    setMessages([]);
    setThreadSearch("");
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

  async function assign(userId: string | null) {
    if (!selected) return;
    setAssignMenu(false);
    try {
      const updated = await assignConversation(selected.id, userId);
      setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change who owns this chat.");
    }
  }

  async function submitReply() {
    const text = draft.trim();
    if (!selected || sending || (!text && !pendingFile)) return;
    setSending(true);
    setError(null);
    try {
      const sent = pendingFile
        ? await sendAttachment(selected.id, pendingFile, text)
        : await sendMessage(selected.id, text);
      setMessages((prev) => [...prev, sent]);
      setDraft("");
      setPendingFile(null);
      void loadConversations();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send the message.");
    } finally {
      setSending(false);
    }
  }

  function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setPendingFile(file);
    // Reset so picking the same file again still fires a change event.
    e.target.value = "";
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

  // Searching within a thread filters rather than jumps: the messages that
  // match are the answer, and scrolling to a highlight in a thousand-message
  // thread only tells you where one of them is.
  const visibleMessages = useMemo(() => {
    const q = threadSearch.trim().toLowerCase();
    if (!q) return messages;
    return messages.filter((msg) => msg.content.toLowerCase().includes(q));
  }, [messages, threadSearch]);

  const linked = sessions.filter((s) => s.status === "linked");

  return (
    <div className="page-flush">
      <InboxStatsBar stats={stats} />

      <div className="flex min-h-0 flex-1">
        {/* ── Thread rail ────────────────────────────────────────────────── */}
        <aside className="flex w-[340px] flex-shrink-0 flex-col border-r border-gray-200 bg-surface">
          <header className="flex-shrink-0 px-4 pt-3.5 pb-3">
            <div className="flex items-center gap-2.5">
              <Link
                to="/channels?tab=whatsapp"
                aria-label="Back to WhatsApp numbers"
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full
                           bg-brand-500/12 text-brand-600 transition-colors hover:bg-brand-500/20"
              >
                <ArrowLeft className="h-[18px] w-[18px]" strokeWidth={2} />
              </Link>

              {/* Which number this inbox is for, and the way to switch. A
                  workspace can have several linked handsets, and hunting back
                  through Channels to change which one you are reading is the
                  navigation this replaces. */}
              <div className="relative min-w-0 flex-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setNumberMenu((v) => !v);
                  }}
                  aria-haspopup="menu"
                  aria-expanded={numberMenu}
                  className="flex w-full items-center gap-1.5 text-left"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-1">
                      <span className="truncate font-display text-[14.5px] font-bold text-gray-900">
                        {session?.display_name || session?.phone_number || "WhatsApp inbox"}
                      </span>
                      <ChevronDown
                        className="h-3.5 w-3.5 flex-shrink-0 text-gray-500"
                        strokeWidth={2.5}
                      />
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span
                        className={session?.status === "linked" ? "dot-live" : "dot bg-amber-500"}
                        aria-hidden="true"
                      />
                      <span className="truncate text-[11.5px] text-gray-500">
                        {session?.status === "linked" ? "Connected" : session?.health || "Not linked"}
                      </span>
                    </span>
                  </span>
                </button>
                <Menu open={numberMenu} onClose={() => setNumberMenu(false)} align="left">
                  {linked.length === 0 && (
                    <p className="px-3 py-2 text-[12.5px] text-gray-500">
                      No other numbers are linked.
                    </p>
                  )}
                  {linked.map((s) => (
                    <MenuItem
                      key={s.id}
                      icon={s.id === sessionId ? Check : undefined}
                      onClick={() => {
                        setNumberMenu(false);
                        setSelectedId(null);
                        navigate(`/channels/whatsapp/${s.id}/inbox`);
                      }}
                    >
                      {s.phone_number || "Pairing…"}
                    </MenuItem>
                  ))}
                </Menu>
              </div>

              <Link
                to="/broadcasts/new"
                aria-label="Start a new campaign"
                title="Start a new campaign"
                className="icon-btn flex-shrink-0"
              >
                <MessageSquarePlus className="h-[18px] w-[18px]" strokeWidth={2} />
              </Link>
            </div>

            <div className="relative mt-3">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
                strokeWidth={1.75}
              />
              <input
                className="input h-9 rounded-full pl-9 text-[13px]"
                placeholder="Search conversations…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="mt-2.5 flex gap-1.5 overflow-x-auto pb-0.5">
              {FILTERS.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  aria-pressed={filter === chip.key}
                  onClick={() => setFilter(chip.key)}
                  className={`flex-shrink-0 rounded-full px-2.5 py-1 text-[11.5px] font-semibold
                              transition-colors ${
                                filter === chip.key
                                  ? "bg-brand-600 text-white"
                                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900"
                              }`}
                >
                  {chip.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-gray-400">
              {total} chat{total === 1 ? "" : "s"}
              {session?.chatbot_name ? ` · ${session.chatbot_name} is answering` : " · no assistant"}
            </p>
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
                <div className="skeleton h-[72px] rounded-xl" />
                <div className="skeleton h-[72px] rounded-xl" />
                <div className="skeleton h-[72px] rounded-xl" />
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
                    className={`flex w-full items-start gap-3 border-l-2 px-4 py-3 text-left
                                transition-colors ${
                                  active
                                    ? "border-brand-500 bg-brand-500/10"
                                    : "border-transparent hover:bg-gray-100"
                                }`}
                  >
                    <Avatar name={c.display_name} phone={c.phone_number} size={40} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-1">
                          {c.pinned && (
                            <Pin
                              className="h-3 w-3 flex-shrink-0 text-gray-400"
                              strokeWidth={2.5}
                              aria-label="Pinned"
                            />
                          )}
                          <span className="truncate text-[14px] font-semibold text-gray-900">
                            {c.display_name || c.phone_number}
                          </span>
                        </span>
                        <span
                          className={`flex-shrink-0 text-[11px] tabular-nums ${
                            c.unread_count > 0 ? "font-semibold text-brand-600" : "text-gray-400"
                          }`}
                        >
                          {timeLabel(c.last_message_at)}
                        </span>
                      </span>

                      {/* Company and number on their own line, the way the
                          contact identifies themselves — a name alone is not
                          enough to tell two Ahmeds apart. */}
                      <span className="mt-0.5 block truncate text-[11.5px] text-gray-500">
                        {[c.company, c.phone_number].filter(Boolean).join(" · ")}
                      </span>

                      <span className="mt-1 flex items-center gap-1.5">
                        {c.has_attachment && (
                          <Paperclip
                            className="h-3 w-3 flex-shrink-0 text-gray-400"
                            strokeWidth={2}
                            aria-label="Has attachment"
                          />
                        )}
                        <span className="min-w-0 flex-1 truncate text-[12.5px] text-gray-500">
                          {c.last_message_preview || "—"}
                        </span>
                        {c.unread_count > 0 && (
                          <span
                            className="flex h-[18px] min-w-[18px] flex-shrink-0 items-center
                                       justify-center rounded-full bg-brand-600 px-1 text-[10px]
                                       font-bold tabular-nums text-white"
                          >
                            {c.unread_count}
                          </span>
                        )}
                      </span>

                      {(c.tags.length > 0 || c.assignee_email || !c.auto_reply) && (
                        <span className="mt-1.5 flex items-center gap-1.5">
                          {c.tags.slice(0, 2).map((tag) => (
                            <span
                              key={tag}
                              className="flex-shrink-0 rounded-full bg-brand-500/10 px-1.5 py-0.5
                                         text-[10px] font-semibold text-brand-700"
                            >
                              {tag}
                            </span>
                          ))}
                          {c.tags.length > 2 && (
                            <span className="text-[10px] text-gray-400">
                              +{c.tags.length - 2}
                            </span>
                          )}
                          {!c.auto_reply && (
                            <span
                              title="A human is handling this chat"
                              className="flex-shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5
                                         text-[10px] font-semibold text-amber-700"
                            >
                              manual
                            </span>
                          )}
                          {c.assignee_email && (
                            <span className="ml-auto flex-shrink-0">
                              <AssigneeChip email={c.assignee_email} size={20} />
                            </span>
                          )}
                        </span>
                      )}
                    </span>
                  </button>

                  {/* Selection for campaigns. Kept out of the row button
                      (nesting a control inside a button is invalid) and
                      revealed on hover so it does not compete with reading. */}
                  <label
                    className={`absolute left-3 top-4 cursor-pointer rounded p-1 transition-opacity ${
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
                  <p className="truncate text-[14.5px] font-semibold text-gray-900">
                    {selected.display_name || selected.phone_number}
                  </p>
                  <p className="truncate text-[11.5px] text-gray-500">
                    {[selected.company, selected.phone_number].filter(Boolean).join(" · ")}
                    {selected.auto_reply && session?.chatbot_name && (
                      <> · answered by {session.chatbot_name}</>
                    )}
                  </p>
                </div>

                {/* Owner. A chip rather than a select, because most of the time
                    it is being read, not changed. */}
                <div className="relative flex-shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setAssignMenu((v) => !v);
                    }}
                    aria-haspopup="menu"
                    aria-expanded={assignMenu}
                    className={`flex items-center gap-1.5 rounded-full px-2 py-1 text-[12px]
                                font-semibold transition-colors ${
                                  selected.assignee_email
                                    ? "bg-brand-500/10 text-brand-700 hover:bg-brand-500/20"
                                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                                }`}
                  >
                    {selected.assignee_email ? (
                      <>
                        <AssigneeChip email={selected.assignee_email} size={18} />
                        <span className="hidden max-w-[9rem] truncate sm:inline">
                          {memberName(selected.assignee_email)}
                        </span>
                      </>
                    ) : (
                      <>
                        <UserPlus className="h-4 w-4" strokeWidth={2} />
                        <span className="hidden sm:inline">Assign</span>
                      </>
                    )}
                  </button>
                  <Menu open={assignMenu} onClose={() => setAssignMenu(false)}>
                    {team.map((mem) => (
                      <MenuItem
                        key={mem.id}
                        icon={mem.id === selected.assignee_id ? Check : undefined}
                        onClick={() => void assign(mem.id)}
                      >
                        {memberName(mem.email)}
                        {mem.email === myEmail ? " (you)" : ""}
                      </MenuItem>
                    ))}
                    {selected.assignee_id && (
                      <MenuItem icon={X} onClick={() => void assign(null)}>
                        Unassign
                      </MenuItem>
                    )}
                    {team.length === 0 && (
                      <p className="px-3 py-2 text-[12.5px] text-gray-500">
                        Invite teammates from Team to assign chats.
                      </p>
                    )}
                  </Menu>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setThreadSearchOpen((v) => !v);
                    setThreadSearch("");
                  }}
                  aria-label="Search in this conversation"
                  aria-pressed={threadSearchOpen}
                  className="icon-btn flex-shrink-0"
                >
                  <Search className="h-[18px] w-[18px]" strokeWidth={2} />
                </button>

                <div className="relative flex-shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setThreadMenu((v) => !v);
                    }}
                    aria-haspopup="menu"
                    aria-expanded={threadMenu}
                    aria-label="Conversation options"
                    className="icon-btn"
                  >
                    <MoreVertical className="h-[18px] w-[18px]" strokeWidth={2} />
                  </button>
                  <Menu open={threadMenu} onClose={() => setThreadMenu(false)}>
                    <MenuItem
                      icon={selected.pinned ? PinOff : Pin}
                      onClick={() => {
                        setThreadMenu(false);
                        void patchSelected({ pinned: !selected.pinned }).catch(() => {});
                      }}
                    >
                      {selected.pinned ? "Unpin from top" : "Pin to top"}
                    </MenuItem>
                    <MenuItem
                      icon={selected.auto_reply ? User : Bot}
                      onClick={() => {
                        setThreadMenu(false);
                        void patchSelected({ auto_reply: !selected.auto_reply }).catch(() => {});
                      }}
                    >
                      {selected.auto_reply ? "Take over from the assistant" : "Hand back to the assistant"}
                    </MenuItem>
                    <MenuItem
                      icon={Check}
                      onClick={() => {
                        setThreadMenu(false);
                        void patchSelected({
                          status: selected.status === "open" ? "closed" : "open",
                        }).catch(() => {});
                      }}
                    >
                      {selected.status === "open" ? "Mark as closed" : "Reopen this chat"}
                    </MenuItem>
                  </Menu>
                </div>
              </header>

              {/* Who owns this and what state it is in, stated once under the
                  header — the two facts a second person opening the thread
                  needs before they type anything. */}
              <div className="flex flex-shrink-0 items-center gap-2 border-b border-gray-200 bg-surface-2 px-5 py-1.5">
                {selected.assignee_email ? (
                  <span className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-700">
                    <AssigneeChip email={selected.assignee_email} size={18} />
                    Assigned: {memberName(selected.assignee_email)}
                  </span>
                ) : (
                  <span className="text-[12px] text-gray-500">Unassigned</span>
                )}
                <span className="ml-auto flex items-center gap-2 text-[11.5px] text-gray-500">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5
                                text-[11px] font-semibold ${
                                  selected.status === "open"
                                    ? "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200"
                                    : "bg-gray-100 text-gray-600 ring-1 ring-inset ring-gray-200"
                                }`}
                  >
                    {selected.status === "open" ? "Open" : "Closed"}
                  </span>
                  {selected.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-brand-500/10 px-2 py-0.5 text-[11px] font-semibold text-brand-700"
                    >
                      {tag}
                    </span>
                  ))}
                </span>
              </div>

              {threadSearchOpen && (
                <div className="flex-shrink-0 border-b border-gray-200 bg-surface px-5 py-2">
                  <input
                    autoFocus
                    value={threadSearch}
                    onChange={(e) => setThreadSearch(e.target.value)}
                    placeholder="Find in this conversation…"
                    aria-label="Find in this conversation"
                    className="input h-8 text-[13px]"
                  />
                  {threadSearch && (
                    <p className="mt-1 text-[11.5px] text-gray-500">
                      {visibleMessages.length} of {messages.length} messages match.
                    </p>
                  )}
                </div>
              )}

              <ConversationThread
                conversationId={selected.id}
                messages={visibleMessages}
                scrollRef={threadRef}
                emptyLabel={
                  threadSearch ? "No messages match that search." : "No messages yet."
                }
              />

              {!selected.auto_reply && (
                <p className="flex-shrink-0 border-t border-amber-200 bg-amber-50 px-5 py-2 text-[11.5px] text-amber-800">
                  The assistant is paused for this chat — replies are yours to send.
                </p>
              )}

              <div className="flex-shrink-0 border-t border-gray-200 bg-surface px-4 py-3">
                {pendingFile && (
                  <div className="mb-2 flex items-center gap-2.5 rounded-xl bg-gray-100 px-3 py-2 text-[12.5px]">
                    <MediaIcon
                      kind={pendingFile.type.startsWith("image/") ? "image" : "document"}
                      className="h-4 w-4 flex-shrink-0 text-gray-500"
                    />
                    <span className="min-w-0 flex-1 truncate font-medium text-gray-800">
                      {pendingFile.name}
                    </span>
                    <span className="flex-shrink-0 tabular-nums text-gray-400">
                      {sizeLabel(pendingFile.size)}
                    </span>
                    <button
                      type="button"
                      onClick={() => setPendingFile(null)}
                      aria-label="Remove attachment"
                      className="icon-btn flex-shrink-0"
                    >
                      <X className="h-3.5 w-3.5" strokeWidth={2} />
                    </button>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  <input ref={fileInputRef} type="file" className="hidden" onChange={onPickFile} />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    aria-label="Attach a file"
                    className="icon-btn mb-px h-[42px] w-[42px] flex-shrink-0"
                  >
                    <Paperclip className="h-[18px] w-[18px]" strokeWidth={2} />
                  </button>
                  <textarea
                    ref={composerRef}
                    rows={1}
                    className="input min-h-[42px] flex-1 resize-none rounded-2xl py-2.5 text-[14px]"
                    placeholder={
                      pendingFile
                        ? "Add a caption (optional)…"
                        : selected.auto_reply
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
                  {/* Between the field and Send, where the eye already is on
                      the way to sending. Interim preview suppressed — the
                      composer sits at the bottom of a scrolling thread, and a
                      chip above it would cover the last message. */}
                  <DictateButton
                    value={draft}
                    onChange={setDraft}
                    showInterim={false}
                    className="mb-px self-end"
                  />
                  <button
                    type="button"
                    onClick={submitReply}
                    disabled={sending || (!draft.trim() && !pendingFile)}
                    aria-label="Send reply"
                    className="mb-px flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center
                               rounded-full bg-brand-600 text-white shadow-xs transition-colors
                               hover:bg-brand-700 disabled:opacity-40 disabled:hover:bg-brand-600"
                  >
                    <Send className="h-[18px] w-[18px]" strokeWidth={2} />
                  </button>
                </div>
              </div>
            </>
          )}
        </section>

        {/* ── Contact ──────────────────────────────────────────────────────── */}
        {selected && (
          <ContactPanel
            conversation={selected}
            messages={messages}
            onPatch={patchSelected}
          />
        )}
      </div>
    </div>
  );
}
