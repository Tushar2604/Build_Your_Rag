// Broadcast campaign console: Overview (funnel + controls + add contacts) and
// Chat Log (contacts list ⇄ conversation thread with human takeover).
//
// While a campaign is `sending`, this polls — the send sweep runs as a
// background task, so progress arrives out-of-band rather than in a response.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  AddRecipientsResult,
  Broadcast,
  BroadcastMessage,
  BroadcastRecipient,
  RecipientStatus,
  addRecipients,
  completeBroadcast,
  getBroadcast,
  listRecipientMessages,
  listRecipients,
  pauseBroadcast,
  retryFailed,
  sendManualMessage,
  startBroadcast,
} from "../api/broadcasts";

const POLL_MS = 4000;
const PAGE_SIZE = 25;

const RECIPIENT_STYLES: Record<RecipientStatus, string> = {
  pending: "bg-gray-100 text-gray-500",
  sent: "bg-blue-50 text-blue-600",
  delivered: "bg-indigo-50 text-indigo-600",
  read: "bg-violet-50 text-violet-600",
  replied: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

function StatusBadge({ status }: { status: RecipientStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${RECIPIENT_STYLES[status]}`}>
      {status}
    </span>
  );
}

/* ── Overview ── */

function OverviewPanel({
  broadcast,
  onChanged,
}: {
  broadcast: Broadcast;
  onChanged: (b: Broadcast) => void;
}) {
  const [contacts, setContacts] = useState("");
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<AddRecipientsResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setAdding(true);
    setError(null);
    setResult(null);
    try {
      const res = await addRecipients(broadcast.id, contacts);
      setResult(res);
      setContacts("");
      onChanged(await getBroadcast(broadcast.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to add contacts.");
    } finally {
      setAdding(false);
    }
  }

  const funnel: [string, number][] = [
    ["Total", broadcast.total_count],
    ["Sent", broadcast.sent_count],
    ["Delivered", broadcast.delivered_count],
    ["Read", broadcast.read_count],
    ["Replied", broadcast.replied_count],
    ["Failed", broadcast.failed_count],
  ];

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="card p-5">
        <h3 className="section-title mb-4">Delivery funnel</h3>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-4 text-center">
          {funnel.map(([label, value]) => (
            <div key={label}>
              <p className="text-2xl font-semibold tabular-nums text-gray-900">{value}</p>
              <p className="text-[10px] uppercase tracking-wide text-gray-400 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-4">
          Counts are cumulative — a contact who read the message also counts as
          sent and delivered.
        </p>
      </div>

      <div className="card p-5">
        <h3 className="section-title mb-2">Message</h3>
        <p className="text-sm text-gray-700 whitespace-pre-wrap bg-gray-50 rounded-lg p-3">
          {broadcast.message_template}
        </p>
        <p className="text-xs text-gray-400 mt-2">
          Sent from {broadcast.from_number || "—"} · replies answered by{" "}
          {broadcast.chatbot_name}
        </p>
      </div>

      <div className="card p-5">
        <h3 className="section-title mb-2">Add contacts</h3>
        <textarea
          className="input resize-none font-mono text-xs"
          rows={5}
          value={contacts}
          onChange={(e) => setContacts(e.target.value)}
          placeholder={"+917502163963, Mohammed Yacoob\n+971553752665"}
        />
        <div className="flex items-center justify-between mt-3">
          <p className="text-xs text-gray-400">
            Numbers already on this campaign are skipped, so re-pasting a list is safe.
          </p>
          <button
            type="button"
            onClick={add}
            disabled={adding || !contacts.trim()}
            className="btn-secondary text-xs px-3 py-1.5 h-auto"
          >
            {adding ? "Adding…" : "Add contacts"}
          </button>
        </div>

        {result && (
          <div className="mt-3 rounded-lg bg-gray-50 border border-gray-200 px-4 py-3 text-xs text-gray-700">
            Added {result.added}
            {result.duplicates > 0 && ` · ${result.duplicates} already on this campaign`}
            {result.invalid.length > 0 && (
              <div className="mt-2 text-amber-700">
                Couldn't read {result.invalid.length} row
                {result.invalid.length !== 1 ? "s" : ""}:{" "}
                <span className="font-mono">{result.invalid.slice(0, 5).join(", ")}</span>
                {result.invalid.length > 5 && " …"}
              </div>
            )}
          </div>
        )}
        {error && (
          <div role="alert" className="mt-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Chat log ── */

function ChatLogPanel({ broadcast }: { broadcast: Broadcast }) {
  const [recipients, setRecipients] = useState<BroadcastRecipient[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<RecipientStatus | null>(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<BroadcastRecipient | null>(null);
  const [messages, setMessages] = useState<BroadcastMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const loadRecipients = useCallback(async () => {
    try {
      const res = await listRecipients(broadcast.id, {
        status,
        search,
        page,
        pageSize: PAGE_SIZE,
      });
      setRecipients(res.recipients);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load contacts.");
    }
  }, [broadcast.id, status, search, page]);

  useEffect(() => {
    void loadRecipients();
  }, [loadRecipients]);

  // Debounced search resets to page 1 — otherwise a narrow filter can land the
  // user on a page that no longer exists.
  useEffect(() => {
    setPage(1);
  }, [status, search]);

  const loadMessages = useCallback(async (recipient: BroadcastRecipient) => {
    try {
      setMessages(await listRecipientMessages(broadcast.id, recipient.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load the conversation.");
    }
  }, [broadcast.id]);

  useEffect(() => {
    if (selected) void loadMessages(selected);
  }, [selected, loadMessages]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  async function send() {
    if (!selected || !draft.trim()) return;
    setSending(true);
    setError(null);
    try {
      const message = await sendManualMessage(broadcast.id, selected.id, draft.trim());
      setMessages((prev) => [...prev, message]);
      setDraft("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to send.");
    } finally {
      setSending(false);
    }
  }

  const chips: { label: string; value: RecipientStatus | null; count: number }[] = [
    { label: "All", value: null, count: broadcast.total_count },
    { label: "Sent", value: "sent", count: broadcast.sent_count },
    { label: "Delivered", value: "delivered", count: broadcast.delivered_count },
    { label: "Read", value: "read", count: broadcast.read_count },
    { label: "Replied", value: "replied", count: broadcast.replied_count },
    { label: "Failed", value: "failed", count: broadcast.failed_count },
  ];

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      {/* Contacts */}
      <div className="card p-4 flex flex-col max-h-[36rem]">
        <div className="flex items-center justify-between mb-3">
          <h3 className="section-title">Contacts ({total})</h3>
          <button
            type="button"
            onClick={() => void loadRecipients()}
            className="text-xs text-gray-400 hover:text-gray-700"
            aria-label="Refresh contacts"
          >
            ↻
          </button>
        </div>

        <input
          className="input h-8 text-sm mb-3"
          placeholder="Search by name or phone…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <div className="flex flex-wrap gap-1.5 mb-3">
          {chips.map((chip) => (
            <button
              key={chip.label}
              type="button"
              aria-pressed={status === chip.value}
              onClick={() => setStatus(chip.value)}
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition ${
                status === chip.value
                  ? "bg-brand-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {chip.label} <span className="tabular-nums opacity-75">{chip.count}</span>
            </button>
          ))}
        </div>

        <ul className="flex-1 overflow-y-auto -mx-1 space-y-1">
          {recipients.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => setSelected(r)}
                className={`w-full text-left rounded-lg px-3 py-2 transition ${
                  selected?.id === r.id ? "bg-brand-50 border border-brand-200" : "hover:bg-gray-50 border border-transparent"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-gray-900 truncate">
                    {r.display_name || r.phone_number}
                  </span>
                  <StatusBadge status={r.status} />
                </div>
                {r.display_name && (
                  <p className="text-xs text-gray-400 truncate">{r.phone_number}</p>
                )}
                {r.error && (
                  <p className="text-[10px] text-red-600 truncate mt-0.5" title={r.error}>
                    {r.error}
                  </p>
                )}
              </button>
            </li>
          ))}
          {recipients.length === 0 && (
            <li className="text-sm text-gray-400 px-3 py-6 text-center">
              No contacts match this filter.
            </li>
          )}
        </ul>

        <div className="flex items-center justify-between pt-3 mt-2 border-t border-gray-100">
          <span className="text-xs text-gray-400 tabular-nums">
            Page {page}/{totalPages}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="btn-secondary text-xs px-3 py-1 h-auto disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn-secondary text-xs px-3 py-1 h-auto disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Thread */}
      <div className="card p-4 flex flex-col max-h-[36rem]">
        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
            Select a contact to see their conversation.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
              <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-sm font-semibold">
                {(selected.display_name || selected.phone_number).charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">
                  {selected.display_name || selected.phone_number}
                </p>
                <p className="text-xs text-gray-400">{selected.phone_number}</p>
              </div>
              <StatusBadge status={selected.status} />
            </div>

            <div ref={threadRef} className="flex-1 overflow-y-auto py-4 space-y-3">
              {messages.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-8">
                  Nothing sent to this contact yet.
                </p>
              )}
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === "assistant" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[75%] rounded-2xl px-3.5 py-2 ${
                      m.role === "assistant"
                        ? "bg-emerald-600 text-white"
                        : "bg-gray-100 text-gray-900"
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap break-words">{m.content}</p>
                    <p
                      className={`text-[10px] mt-1 tabular-nums ${
                        m.role === "assistant" ? "text-emerald-100" : "text-gray-400"
                      }`}
                    >
                      {new Date(m.created_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-gray-100 pt-3">
              <div className="flex gap-2">
                <input
                  className="input flex-1"
                  placeholder="Type a message…"
                  value={draft}
                  maxLength={1600}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={send}
                  disabled={sending || !draft.trim()}
                  className="btn-primary text-sm whitespace-nowrap"
                >
                  {sending ? "Sending…" : "Send"}
                </button>
              </div>
              <p className="text-[10px] text-gray-400 mt-1.5">
                Sends as the assistant and is saved to the conversation, so its
                later replies stay consistent with what you said.
              </p>
            </div>
          </>
        )}

        {error && (
          <div role="alert" className="mt-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Page ── */

export default function BroadcastDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [tab, setTab] = useState<"overview" | "chat">("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBroadcast(id)
      .then(setBroadcast)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Campaign not found."));
  }, [id]);

  // The send sweep runs in the background, so progress only shows up if we ask.
  useEffect(() => {
    if (broadcast?.status !== "sending") return;
    const timer = setInterval(() => {
      getBroadcast(id).then(setBroadcast).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [id, broadcast?.status]);

  async function run(action: (id: string) => Promise<Broadcast>) {
    setBusy(true);
    setError(null);
    try {
      setBroadcast(await action(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That action failed.");
    } finally {
      setBusy(false);
    }
  }

  // Both interim states sit in the same page shell as the loaded view, so the
  // content column doesn't jump sideways once the campaign arrives.
  if (error && !broadcast) {
    return (
      <div className="page">
        <div className="card p-8 text-center">
          <p className="text-sm text-red-700">{error}</p>
          <Link to="/broadcasts" className="btn-secondary text-sm mt-4 inline-block">
            Back to campaigns
          </Link>
        </div>
      </div>
    );
  }
  if (!broadcast) {
    return (
      <div className="page">
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div className="min-w-0">
          <Link to="/broadcasts" className="text-xs text-gray-400 hover:text-gray-700">
            ← Broadcast
          </Link>
          <h1 className="page-title mt-1">{broadcast.name}</h1>
          <p className="text-sm text-gray-500 mt-1">
            Broadcast + Auto Reply · {broadcast.chatbot_name} ·{" "}
            <span className="font-medium">{broadcast.status}</span>
          </p>
        </div>

        <div className="page-header-actions justify-end">
          {broadcast.status !== "sending" && broadcast.status !== "completed" && (
            <button
              type="button"
              onClick={() => run(startBroadcast)}
              disabled={busy}
              className="btn-primary text-xs px-3 py-1.5 h-auto"
            >
              {broadcast.status === "paused" ? "Resume" : "Start campaign"}
            </button>
          )}
          {broadcast.status === "sending" && (
            <button
              type="button"
              onClick={() => run(pauseBroadcast)}
              disabled={busy}
              className="btn-secondary text-xs px-3 py-1.5 h-auto text-amber-700"
            >
              Pause Campaign
            </button>
          )}
          {broadcast.failed_count > 0 && (
            <button
              type="button"
              onClick={() => run(retryFailed)}
              disabled={busy}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Retry failed ({broadcast.failed_count})
            </button>
          )}
          {broadcast.status !== "completed" && (
            <button
              type="button"
              onClick={() => run(completeBroadcast)}
              disabled={busy}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Mark as Completed
            </button>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="tab-bar mb-6">
        <button
          type="button"
          onClick={() => setTab("overview")}
          className={tab === "overview" ? "tab-item-active" : "tab-item"}
        >
          Overview
        </button>
        <button
          type="button"
          onClick={() => setTab("chat")}
          className={tab === "chat" ? "tab-item-active" : "tab-item"}
        >
          Chat Log
        </button>
      </div>

      {tab === "overview" ? (
        <OverviewPanel broadcast={broadcast} onChanged={setBroadcast} />
      ) : (
        <ChatLogPanel broadcast={broadcast} />
      )}
    </div>
  );
}
