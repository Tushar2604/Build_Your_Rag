// Broadcast campaigns — list + create. A campaign is created in `queued` and
// sends nothing until it's opened and started, so an operator can review the
// contact list before 500 people get a message.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  Broadcast,
  BroadcastStatus,
  createBroadcast,
  deleteBroadcast,
  listBroadcasts,
} from "../api/broadcasts";
import { Chatbot, listChatbots } from "../api/chatbots";

const STATUS_STYLES: Record<BroadcastStatus, string> = {
  queued: "bg-gray-100 text-gray-600",
  sending: "bg-blue-100 text-blue-700",
  paused: "bg-amber-100 text-amber-700",
  completed: "bg-emerald-100 text-emerald-700",
};

function StatusPill({ status }: { status: BroadcastStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  );
}

function CreateModal({
  chatbots,
  onClose,
  onCreated,
}: {
  chatbots: Chatbot[];
  onClose: () => void;
  onCreated: (b: Broadcast) => void;
}) {
  const [chatbotId, setChatbotId] = useState(chatbots[0]?.id ?? "");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [contacts, setContacts] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await createBroadcast({
        chatbot_id: chatbotId,
        name,
        message_template: message,
        recipients_text: contacts,
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create the campaign.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={submit}
        className="card w-full max-w-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto"
      >
        <h2 className="section-title">New broadcast campaign</h2>

        <div>
          <label className="label">Assistant *</label>
          <select
            className="input"
            value={chatbotId}
            onChange={(e) => setChatbotId(e.target.value)}
            required
          >
            {chatbots.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <p className="text-xs text-gray-400 mt-1">
            Must already be connected to a WhatsApp number under Channels.
            Replies are answered by this assistant.
          </p>
        </div>

        <div>
          <label className="label">Campaign name *</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="BIM Structure — India"
            maxLength={160}
            required
          />
        </div>

        <div>
          <label className="label">Message *</label>
          <textarea
            className="input resize-none"
            rows={4}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={1600}
            placeholder="Hi {{first_name}}, this is the HR Assistant from ENGISOFT Engineering…"
            required
          />
          <p className="text-xs text-gray-400 mt-1">
            Placeholders: <code>{"{{name}}"}</code>, <code>{"{{first_name}}"}</code>,{" "}
            <code>{"{{phone}}"}</code> · {message.length}/1600
          </p>
        </div>

        <div>
          <label className="label">Contacts</label>
          <textarea
            className="input resize-none font-mono text-xs"
            rows={6}
            value={contacts}
            onChange={(e) => setContacts(e.target.value)}
            placeholder={"+917502163963, Mohammed Yacoob\n+971553752665, Aisha\n+918143227567"}
          />
          <p className="text-xs text-gray-400 mt-1">
            One per line, or paste a CSV. Numbers must include a country code —
            anything that can't be read is reported back rather than skipped.
            You can add more later.
          </p>
        </div>

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Cancel
          </button>
          <button type="submit" disabled={saving || !chatbotId} className="btn-primary text-sm">
            {saving ? "Creating…" : "Create campaign"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function BroadcastsPage() {
  const navigate = useNavigate();
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listBroadcasts(), listChatbots()])
      .then(([b, c]) => {
        setBroadcasts(b);
        setChatbots(c);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns."))
      .finally(() => setLoading(false));
  }, []);

  async function remove(id: string) {
    try {
      await deleteBroadcast(id);
      setBroadcasts((prev) => prev.filter((b) => b.id !== id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to delete.");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="page-title">Broadcast</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading
              ? "Loading…"
              : `${broadcasts.length} campaign${broadcasts.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          disabled={chatbots.length === 0}
          className="btn-primary text-sm"
        >
          New campaign
        </button>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && broadcasts.length === 0 && (
        <div className="card p-10 text-center">
          <p className="text-sm text-gray-500">No campaigns yet.</p>
          <p className="text-xs text-gray-400 mt-1">
            A broadcast messages a list of contacts on WhatsApp, then lets your
            assistant handle every reply.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {broadcasts.map((b) => (
          <div key={b.id} className="card p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <Link
                    to={`/broadcasts/${b.id}`}
                    className="text-sm font-semibold text-gray-900 hover:text-brand-700 truncate"
                  >
                    {b.name}
                  </Link>
                  <StatusPill status={b.status} />
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {b.chatbot_name} · from {b.from_number || "—"}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => navigate(`/broadcasts/${b.id}`)}
                  className="btn-secondary text-xs px-3 py-1.5 h-auto"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => remove(b.id)}
                  className="text-xs text-gray-400 hover:text-red-600 px-2"
                  aria-label={`Delete ${b.name}`}
                >
                  Delete
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-3 sm:grid-cols-6 gap-3 text-center">
              {[
                ["Total", b.total_count],
                ["Sent", b.sent_count],
                ["Delivered", b.delivered_count],
                ["Read", b.read_count],
                ["Replied", b.replied_count],
                ["Failed", b.failed_count],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <p className="text-lg font-semibold tabular-nums text-gray-900">{value}</p>
                  <p className="text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <CreateModal
          chatbots={chatbots}
          onClose={() => setShowCreate(false)}
          onCreated={(b) => {
            setShowCreate(false);
            navigate(`/broadcasts/${b.id}`);
          }}
        />
      )}
    </div>
  );
}
