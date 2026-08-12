// WhatsApp inbox — the chat window for a QR-linked personal number.
//
// Two panes: threads on the left, the selected conversation on the right. It
// polls rather than holding a socket, matching the rest of the app and
// surviving the free-tier host sleeping mid-view.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  InboxConversation,
  InboxMessage,
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
  { key: "attachments", label: "Attachments" },
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

function sizeLabel(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const KIND_ICON: Record<string, string> = {
  image: "🖼️",
  video: "🎬",
  audio: "🎤",
  document: "📄",
  sticker: "🌟",
};

/** Renders an attachment. Images are fetched as object URLs because the media
 * endpoint needs an Authorization header that `<img src>` cannot send. */
function Attachment({
  conversationId,
  message,
}: {
  conversationId: string;
  message: InboxMessage;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const isImage = message.media_kind === "image" || message.media_kind === "sticker";

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
      <div className="rounded-lg bg-black/10 px-3 py-2 text-[11px] italic opacity-80">
        {KIND_ICON[message.media_kind] || "📎"} {message.media_kind || "attachment"} — not stored
      </div>
    );
  }

  if (isImage) {
    if (failed) return <div className="text-[11px] italic opacity-80">Image unavailable</div>;
    if (!url) return <div className="skeleton h-40 w-56 rounded-lg" />;
    return (
      <a href={url} target="_blank" rel="noreferrer">
        <img
          src={url}
          alt={message.media_filename || "Attachment"}
          className="max-h-64 rounded-lg object-cover"
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
      className="flex items-center gap-2 rounded-lg bg-black/10 px-3 py-2 text-left text-[12px] hover:bg-black/20"
    >
      <span aria-hidden="true">{KIND_ICON[message.media_kind] || "📎"}</span>
      <span className="truncate max-w-[14rem]">
        {message.media_filename || message.media_kind}
      </span>
      <span className="opacity-70 tabular-nums">{sizeLabel(message.media_size_bytes)}</span>
      {failed && <span className="text-red-200">failed</span>}
    </button>
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

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between border-b border-gray-200 bg-surface px-6 py-4 flex-shrink-0">
        <div>
          <h1 className="section-title">
            {session?.phone_number || "WhatsApp inbox"}
            {session?.status === "linked" && (
              <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                linked
              </span>
            )}
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {total} conversation{total === 1 ? "" : "s"}
            {session?.chatbot_name ? ` · ${session.chatbot_name} answers by default` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {checked.size > 0 && (
            <button type="button" onClick={startCampaign} className="btn-primary text-sm">
              Start campaign ({checked.size})
            </button>
          )}
          <Link to="/channels?tab=whatsapp" className="btn-secondary text-sm">
            Channels
          </Link>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="mx-6 mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 grid gap-4 p-4 sm:p-6 lg:grid-cols-[22rem_1fr]">
        {/* --- Threads --- */}
        <div className="card p-4 flex flex-col min-h-0">
          <input
            className="input h-8 text-sm mb-3"
            placeholder="Search name, number or message…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="flex flex-wrap gap-1.5 mb-3">
            {FILTERS.map((chip) => (
              <button
                key={chip.key}
                type="button"
                aria-pressed={filter === chip.key}
                onClick={() => setFilter(chip.key)}
                className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition ${
                  filter === chip.key
                    ? "bg-brand-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {chip.label}
              </button>
            ))}
          </div>

          <ul className="flex-1 overflow-y-auto -mx-1">
            {loading && <li className="skeleton h-14 mx-1 mb-2 rounded-lg" />}
            {!loading && conversations.length === 0 && (
              <li className="text-sm text-gray-400 px-3 py-6 text-center">
                {search || filter !== "all"
                  ? "No conversations match this filter."
                  : "No messages yet. When someone messages this number, the thread appears here."}
              </li>
            )}
            {conversations.map((c) => (
              <li key={c.id}>
                <div
                  className={`mx-1 mb-1 flex items-center gap-2 rounded-lg px-2 py-2 ${
                    c.id === selectedId
                      ? "border border-brand-200 bg-brand-50"
                      : "border border-transparent hover:bg-gray-50"
                  }`}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${c.phone_number}`}
                    checked={checked.has(c.id)}
                    onChange={() => toggleChecked(c.id)}
                    className="flex-shrink-0"
                  />
                  <button
                    type="button"
                    onClick={() => openConversation(c)}
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-gray-900">
                        {c.display_name || c.phone_number}
                      </span>
                      <span className="flex-shrink-0 text-[10px] text-gray-400 tabular-nums">
                        {timeLabel(c.last_message_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {c.has_attachment && <span aria-label="Has attachment">📎</span>}
                      <span className="truncate text-xs text-gray-500 flex-1">
                        {c.last_message_preview || "—"}
                      </span>
                      {c.unread_count > 0 && (
                        <span className="flex-shrink-0 rounded-full bg-brand-600 px-1.5 text-[10px] font-semibold text-white tabular-nums">
                          {c.unread_count}
                        </span>
                      )}
                      {!c.auto_reply && (
                        <span
                          title="A human is handling this conversation"
                          className="flex-shrink-0 rounded-full bg-amber-100 px-1.5 text-[10px] font-medium text-amber-700"
                        >
                          manual
                        </span>
                      )}
                    </div>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* --- Thread --- */}
        <div className="card p-0 flex flex-col min-h-0">
          {!selected ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
              Select a conversation to read it.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-gray-900">
                    {selected.display_name || selected.phone_number}
                  </p>
                  <p className="text-[11px] text-gray-500">{selected.phone_number}</p>
                </div>
                <button
                  type="button"
                  onClick={toggleTakeover}
                  className={selected.auto_reply ? "btn-secondary text-xs" : "btn-primary text-xs"}
                >
                  {selected.auto_reply ? "Take over" : "Hand back to assistant"}
                </button>
              </div>

              {!selected.auto_reply && (
                <p className="bg-amber-50 px-4 py-2 text-[11px] text-amber-800 border-b border-amber-100">
                  The assistant is paused for this conversation — replies are yours to send.
                </p>
              )}

              <div ref={threadRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-2">
                {messages.length === 0 && (
                  <p className="text-center text-sm text-gray-400 py-8">No messages yet.</p>
                )}
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.direction === "out" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[75%] rounded-2xl px-3.5 py-2 text-sm ${
                        msg.direction === "out"
                          ? "bg-emerald-600 text-white"
                          : "bg-gray-100 text-gray-900"
                      }`}
                    >
                      {msg.media_kind && (
                        <div className="mb-1">
                          <Attachment conversationId={selected.id} message={msg} />
                        </div>
                      )}
                      {msg.content && (
                        <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                      )}
                      <p
                        className={`mt-1 text-[10px] tabular-nums ${
                          msg.direction === "out" ? "text-white/70" : "text-gray-400"
                        }`}
                      >
                        {new Date(msg.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="border-t border-gray-100 p-3 flex items-end gap-2">
                <textarea
                  className="input resize-none min-h-[40px] max-h-32 flex-1 text-sm"
                  placeholder="Type a reply…"
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
                  className="btn-primary text-sm disabled:opacity-40"
                >
                  {sending ? "Sending…" : "Send"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
