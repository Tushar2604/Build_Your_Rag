// Candidates — every WhatsApp contact this workspace has ever talked to,
// across every connected number, in one place. Where an HR user goes to
// reopen a specific person's conversation and see whatever they sent —
// resume, marksheet, degree — without having to remember which WhatsApp
// number the conversation came in on.
//
// Deliberately read-oriented: replying lives in the per-number inbox
// (WhatsAppInboxPage), which already owns polling, takeover, and the
// composer. This page links out to it for personal/QR-linked numbers rather
// than re-implementing send here.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Download, MessageCircle, Paperclip, Search, Users } from "lucide-react";

import { Candidate, listCandidates } from "../api/candidates";
import { ApiError } from "../api/client";
import { InboxMessage, fetchMediaObjectUrl, listMessages } from "../api/whatsappInbox";
import { Avatar, ConversationThread, MediaIcon, sizeLabel, timeLabel } from "../components/ConversationThread";

type FilterKey = "all" | "unread" | "documents";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "documents", label: "Has documents" },
];

function filterParams(key: FilterKey) {
  switch (key) {
    case "unread":
      return { unreadOnly: true };
    case "documents":
      return { hasAttachment: true };
    default:
      return {};
  }
}

/** One shared attachment in the Documents strip. A thin wrapper around the
 * same fetch-as-object-URL pattern `Attachment` uses inline in the thread —
 * this one always renders as a labelled chip, never inline as an image,
 * because a resume and a photo should look the same size in a document list. */
function DocumentChip({ candidateId, message }: { candidateId: string; message: InboxMessage }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function open() {
    if (!message.media_available || busy) return;
    setBusy(true);
    try {
      const objectUrl = await fetchMediaObjectUrl(candidateId, message.id);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = message.media_filename || `${message.media_kind}-${message.id}`;
      a.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={open}
      disabled={!message.media_available || busy}
      className="flex w-56 flex-shrink-0 items-center gap-2.5 rounded-xl border border-gray-200
                 bg-surface px-3 py-2.5 text-left shadow-xs transition-colors hover:bg-gray-50
                 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
        <MediaIcon kind={message.media_kind} className="w-4 h-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-medium text-gray-900">
          {message.media_filename || message.media_kind || "Attachment"}
        </span>
        <span className="block text-[11px] text-gray-500">
          {failed ? "Download failed" : message.media_available ? sizeLabel(message.media_size_bytes) : "Not stored"}
        </span>
      </span>
      {message.media_available && <Download className="w-3.5 h-3.5 flex-shrink-0 text-gray-400" strokeWidth={2} />}
    </button>
  );
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => candidates.find((c) => c.id === selectedId) || null,
    [candidates, selectedId],
  );

  const documents = useMemo(() => messages.filter((m) => m.media_kind), [messages]);

  const loadCandidates = useCallback(async () => {
    try {
      const page = await listCandidates({ search: search.trim(), ...filterParams(filter), pageSize: 50 });
      setCandidates(page.candidates);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load candidates.");
    } finally {
      setLoading(false);
    }
  }, [search, filter]);

  useEffect(() => {
    void loadCandidates();
  }, [loadCandidates]);

  useEffect(() => {
    if (!selectedId) return;
    setMessagesLoading(true);
    // The max the endpoint allows — this view is "read the whole history",
    // not a live feed, so there's no reason to page it for the vast majority
    // of recruiting conversations.
    listMessages(selectedId, 500)
      .then(setMessages)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load this conversation."))
      .finally(() => setMessagesLoading(false));
  }, [selectedId]);

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* ── Candidate rail ───────────────────────────────────────────────── */}
      <aside className="flex w-[360px] flex-shrink-0 flex-col border-r border-gray-200 bg-surface">
        <header className="flex-shrink-0 px-4 pt-4 pb-3">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
              <Users className="w-4 h-4" strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="truncate font-display text-[15px] font-semibold text-gray-900">Candidates</h1>
              <p className="truncate text-[11px] text-gray-500">
                {total} conversation{total === 1 ? "" : "s"} across every WhatsApp number
              </p>
            </div>
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

        <ul className="min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <li className="space-y-2 p-3">
              <div className="skeleton h-16 rounded-xl" />
              <div className="skeleton h-16 rounded-xl" />
              <div className="skeleton h-16 rounded-xl" />
            </li>
          )}
          {!loading && candidates.length === 0 && (
            <li className="px-6 py-12 text-center text-sm text-gray-500">
              {search || filter !== "all"
                ? "No candidates match this filter."
                : "No conversations yet. Once someone messages any of your WhatsApp numbers, they'll show up here."}
            </li>
          )}
          {candidates.map((c) => {
            const active = c.id === selectedId;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(c.id)}
                  aria-current={active ? "true" : undefined}
                  className={`flex w-full items-center gap-3 border-l-2 px-4 py-3 text-left transition-colors ${
                    active ? "border-brand-500 bg-brand-500/10" : "border-transparent hover:bg-gray-100"
                  }`}
                >
                  <Avatar name={c.display_name} phone={c.phone_number} emoji />
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
                          aria-label="Sent documents"
                        />
                      )}
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-gray-500">
                        {c.last_message_preview || "—"}
                      </span>
                      {c.unread_count > 0 && (
                        <span className="flex h-[18px] min-w-[18px] flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-bold tabular-nums text-white">
                          {c.unread_count}
                        </span>
                      )}
                    </span>
                    {/* The number is the identity here, so it stays visible
                        even once a name is known — an HR user searching their
                        own phone needs it, and half these contacts never get
                        saved a name at all. */}
                    <span className="mt-1 block truncate text-[10.5px] text-gray-400">
                      {c.display_name ? `${c.phone_number} · ${c.channel_label}` : c.channel_label}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* ── Profile ──────────────────────────────────────────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col bg-canvas">
        {error && (
          <div role="alert" className="flex-shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        {!selected ? (
          <div className="empty-state flex-1">
            <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-500/10 text-brand-600">
              <Users className="h-8 w-8" strokeWidth={1.5} />
            </span>
            <p className="empty-state-title">Pick a candidate to open their conversation</p>
            <p className="empty-state-desc">
              The full chat history and any documents they've sent — resume, marksheet, degree — show up here.
            </p>
          </div>
        ) : (
          <>
            <header className="flex flex-shrink-0 items-center gap-3.5 border-b border-gray-200 bg-surface px-5 py-3">
              <Avatar name={selected.display_name} phone={selected.phone_number} size={46} emoji />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold text-gray-900">
                  {selected.display_name || selected.phone_number}
                </p>
                <p className="truncate text-[11.5px] text-gray-500">
                  {selected.phone_number} · {selected.channel_label}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10.5px] font-medium text-gray-600">
                    {messages.length} message{messages.length === 1 ? "" : "s"}
                  </span>
                  {documents.length > 0 && (
                    <span className="rounded-full bg-brand-500/10 px-2 py-0.5 text-[10.5px] font-medium text-brand-600">
                      {documents.length} document{documents.length === 1 ? "" : "s"}
                    </span>
                  )}
                  {/* Says who is answering this thread, which is the first
                      thing you want to know before replying by hand. */}
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10.5px] font-medium ${
                      selected.auto_reply
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {selected.auto_reply ? "Assistant replying" : "Handled by a human"}
                  </span>
                </div>
              </div>
              {selected.channel_kind === "personal" && selected.session_id && (
                <Link
                  to={`/channels/whatsapp/${selected.session_id}/inbox`}
                  className="btn-sm btn-secondary flex-shrink-0"
                >
                  <MessageCircle className="w-3.5 h-3.5" strokeWidth={2} />
                  Reply in inbox
                </Link>
              )}
            </header>

            {documents.length > 0 && (
              <div className="flex-shrink-0 border-b border-gray-200 bg-surface px-5 py-3">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  Documents ({documents.length})
                </p>
                <div className="flex gap-2.5 overflow-x-auto pb-1">
                  {documents.map((m) => (
                    <DocumentChip key={m.id} candidateId={selected.id} message={m} />
                  ))}
                </div>
              </div>
            )}

            {messagesLoading && messages.length === 0 ? (
              <div className="flex-1 space-y-2 p-5">
                <div className="skeleton h-16 w-2/3 rounded-2xl" />
                <div className="skeleton ml-auto h-16 w-2/3 rounded-2xl" />
                <div className="skeleton h-16 w-1/2 rounded-2xl" />
              </div>
            ) : (
              <ConversationThread
                conversationId={selected.id}
                messages={messages}
                emptyLabel="No messages in this conversation."
              />
            )}
          </>
        )}
      </section>
    </div>
  );
}
