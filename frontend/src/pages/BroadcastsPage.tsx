// Broadcast campaigns — the list. Creating one is its own page
// (BroadcastCreatePage): choosing a mode, a number, a message and a contact
// list is too much to review inside a modal.
//
// A campaign is created in `queued` and sends nothing until it is opened and
// started, so an operator can check the contact list before 500 people get a
// message.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  Broadcast,
  BroadcastStatus,
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

export default function BroadcastsPage() {
  const navigate = useNavigate();
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [loading, setLoading] = useState(true);
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
        <Link
          to="/broadcasts/new"
          className={`btn-primary text-sm ${chatbots.length === 0 ? "pointer-events-none opacity-50" : ""}`}
          aria-disabled={chatbots.length === 0}
        >
          New campaign
        </Link>
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
                <p className="text-xs text-gray-500 mt-1 flex items-center gap-2 flex-wrap">
                  <span>{b.chatbot_name} · from {b.from_number || "—"}</span>
                  <span className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] font-semibold">
                    {b.mode === "broadcast_reply" ? "Broadcast + Reply" : "Broadcast"}
                  </span>
                  <span className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] font-semibold">
                    {b.sender_kind === "personal" ? "Phone WhatsApp" : "Cloud API"}
                  </span>
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
    </div>
  );
}
