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
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Bot, Paperclip, Search, Send, User, X } from "lucide-react";

import { ApiError } from "../api/client";
import {
  InboxConversation,
  InboxMessage,
  listConversations,
  listMessages,
  markRead,
  sendAttachment,
  sendMessage,
  setAutoReply,
} from "../api/whatsappInbox";
import { WhatsAppWebSession, listWebSessions } from "../api/whatsappWeb";
import { Avatar, ConversationThread, MediaIcon, sizeLabel, timeLabel } from "../components/ConversationThread";

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
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

            <ConversationThread
              conversationId={selected.id}
              messages={messages}
              scrollRef={threadRef}
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
                    className="w-4 h-4 flex-shrink-0 text-gray-500"
                  />
                  <span className="min-w-0 flex-1 truncate font-medium text-gray-800">
                    {pendingFile.name}
                  </span>
                  <span className="flex-shrink-0 text-gray-400 tabular-nums">
                    {sizeLabel(pendingFile.size)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPendingFile(null)}
                    aria-label="Remove attachment"
                    className="icon-btn flex-shrink-0"
                  >
                    <X className="w-3.5 h-3.5" strokeWidth={2} />
                  </button>
                </div>
              )}
              <div className="flex items-end gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={onPickFile}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="Attach a file"
                  className="icon-btn mb-px h-[42px] w-[42px] flex-shrink-0"
                >
                  <Paperclip className="w-[18px] h-[18px]" strokeWidth={2} />
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
                <button
                  type="button"
                  onClick={submitReply}
                  disabled={sending || (!draft.trim() && !pendingFile)}
                  aria-label="Send reply"
                  className="mb-px flex h-[42px] w-[42px] flex-shrink-0 items-center justify-center
                             rounded-full bg-emerald-600 text-white shadow-xs transition-colors
                             hover:bg-emerald-700 disabled:opacity-40 disabled:hover:bg-emerald-600"
                >
                  <Send className="w-[18px] h-[18px]" strokeWidth={2} />
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
