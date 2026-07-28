import { useState, useEffect, FormEvent } from "react";
import {
  listWhatsAppChannels, connectWhatsAppChannel, disconnectWhatsAppChannel, WhatsAppChannel,
} from "../api/whatsapp";
import { listChatbots, Chatbot } from "../api/chatbots";
import { ApiError } from "../api/client";

function ConnectModal({
  chatbots,
  onCreate,
  onClose,
}: {
  chatbots: Chatbot[];
  onCreate: (c: WhatsAppChannel) => void;
  onClose: () => void;
}) {
  const [chatbotId, setChatbotId] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [accountSid, setAccountSid] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WhatsAppChannel | null>(null);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!chatbotId || !phoneNumber || !accountSid || !authToken) return;
    setLoading(true);
    setError(null);
    try {
      const channel = await connectWhatsAppChannel({
        chatbot_id: chatbotId,
        phone_number: phoneNumber,
        twilio_account_sid: accountSid,
        twilio_auth_token: authToken,
      });
      setResult(channel);
      onCreate(channel);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to connect WhatsApp.");
    } finally {
      setLoading(false);
    }
  }

  function copy(val: string) {
    navigator.clipboard.writeText(val);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 backdrop-blur-sm px-4 animate-fade-in"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">
            {result ? "WhatsApp connected" : "Connect WhatsApp"}
          </h2>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {result ? (
          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-gray-600">
              Last step — paste this webhook URL into Twilio, under your WhatsApp Sandbox (or Sender)
              settings, in the <strong>"WHEN A MESSAGE COMES IN"</strong> field:
            </p>
            <div>
              <div className="flex items-center gap-2">
                <input readOnly value={result.webhook_url} className="input flex-1 text-xs font-mono" />
                <button type="button" onClick={() => copy(result.webhook_url)} className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap">
                  Copy
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500">
              Once saved in Twilio, message <strong>{result.phone_number}</strong> on WhatsApp — it'll be
              answered by <strong>{result.chatbot_name}</strong>.
            </p>
            <div className="flex justify-end pt-2">
              <button type="button" onClick={onClose} className="btn-primary">Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreate}>
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="label">Assistant *</label>
                <select required className="input" value={chatbotId} onChange={(e) => setChatbotId(e.target.value)}>
                  <option value="">Select an assistant…</option>
                  {chatbots.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">WhatsApp number *</label>
                <input required className="input font-mono" value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)} placeholder="+14155238886" />
                <p className="text-xs text-gray-400 mt-1">
                  E.164 format. Use your Twilio Sandbox number to start, or your approved WhatsApp Sender later.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Twilio Account SID *</label>
                  <input required className="input font-mono text-xs" value={accountSid}
                    onChange={(e) => setAccountSid(e.target.value)} placeholder="ACxxxxxxxxxxxxxxxx" />
                </div>
                <div>
                  <label className="label">Twilio Auth Token *</label>
                  <input required type="password" className="input font-mono text-xs" value={authToken}
                    onChange={(e) => setAuthToken(e.target.value)} />
                </div>
              </div>
              <p className="text-xs text-gray-400">
                Both are on your Twilio Console dashboard. Stored only to sign/verify this channel's own
                webhook traffic — never shared with other tenants.
              </p>
              {error && (
                <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/60">
              <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={loading || !chatbotId || !phoneNumber || !accountSid || !authToken} className="btn-primary">
                {loading ? "Connecting…" : "Connect →"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<WhatsAppChannel[]>([]);
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [loading, setLoading] = useState(true);
  const [showConnect, setShowConnect] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listWhatsAppChannels(), listChatbots()])
      .then(([c, b]) => { setChannels(c); setChatbots(b); })
      .finally(() => setLoading(false));
  }, []);

  function handleCreated(channel: WhatsAppChannel) {
    setChannels((prev) => [channel, ...prev]);
  }

  async function handleDisconnect(id: string) {
    try {
      await disconnectWhatsAppChannel(id);
      setChannels((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to disconnect.");
    }
  }

  return (
    <div className="page">
      {showConnect && (
        <ConnectModal chatbots={chatbots} onCreate={handleCreated} onClose={() => setShowConnect(false)} />
      )}

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="page-title">Channels</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? "Loading…" : `${channels.length} channel${channels.length !== 1 ? "s" : ""} connected`}
          </p>
        </div>
        <button onClick={() => setShowConnect(true)} className="btn-primary">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Connect WhatsApp
        </button>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead><tr><th>Assistant</th><th>Number</th><th>Status</th><th /></tr></thead>
            <tbody>
              {[...Array(2)].map((_, i) => (
                <tr key={i}><td colSpan={4}><div className="skeleton h-5 w-full" /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : channels.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center">
              <svg className="w-6 h-6 text-emerald-600" fill="currentColor" viewBox="0 0 24 24">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
                <path d="M12.001 2C6.478 2 2 6.478 2 12c0 1.85.505 3.583 1.383 5.07L2.06 22l4.955-1.301C8.464 21.518 10.174 22 12.001 22c5.522 0 10-4.478 10-10S17.523 2 12.001 2zm5.85 15.85a8.313 8.313 0 01-5.85 2.415 8.31 8.31 0 01-4.229-1.152l-.303-.18-3.153.828.842-3.075-.198-.316A8.31 8.31 0 013.69 12c0-4.588 3.723-8.311 8.311-8.311 2.22 0 4.307.865 5.877 2.436a8.257 8.257 0 012.434 5.876c0 2.223-.867 4.31-2.461 5.85z" />
              </svg>
            </div>
            <p className="empty-state-title">No channels connected</p>
            <p className="empty-state-desc">
              Deploy any assistant directly into WhatsApp — connect a Twilio WhatsApp number and it
              answers real conversations, grounded in the same knowledge base as everywhere else.
            </p>
            <button onClick={() => setShowConnect(true)} className="btn-primary mt-5">
              Connect your first number
            </button>
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Assistant</th>
                <th>Number</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium text-gray-900">{c.chatbot_name}</td>
                  <td className="font-mono text-xs text-gray-600">{c.phone_number}</td>
                  <td>
                    <span className={`badge ${c.status === "active" ? "badge-live" : "badge-draft"}`}>
                      {c.status === "active" ? "Active" : c.status}
                    </span>
                  </td>
                  <td className="text-right">
                    <button
                      onClick={() => handleDisconnect(c.id)}
                      className="text-xs text-red-600 hover:text-red-700 font-medium"
                    >
                      Disconnect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-6 rounded-xl bg-blue-50 border border-blue-100 px-5 py-4 text-sm text-blue-900">
        <p className="font-semibold mb-1">Don't have a Twilio number yet?</p>
        <p className="text-blue-800/80 text-xs leading-relaxed">
          Twilio's WhatsApp Sandbox is free for development — create a Twilio account, activate the
          Sandbox under Messaging → Try it out → Send a WhatsApp message, and join it by sending the
          given code from your own phone. Use that Sandbox number and your Account SID / Auth Token
          (both on your Twilio Console dashboard) above.
        </p>
      </div>
    </div>
  );
}
