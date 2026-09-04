import { useState, useEffect, FormEvent } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { Link } from "react-router-dom";
import {
  listWhatsAppChannels, connectWhatsAppChannel, disconnectWhatsAppChannel, WhatsAppChannel,
  WhatsAppProvider,
} from "../api/whatsapp";
import { listChatbots, Chatbot } from "../api/chatbots";
import { ApiError } from "../api/client";
import WhatsAppQrModal from "../components/WhatsAppQrModal";
import {
  ReplyReadiness, WhatsAppWebSession, WhatsAppWebOptions, attachAssistant,
  createWebSession, getReplyReadiness, getWhatsAppWebOptions, listWebSessions,
  mergeDuplicateNumbers, unlinkWebSession,
} from "../api/whatsappWeb";

function ConnectModal({
  chatbots,
  provider,
  onCreate,
  onClose,
}: {
  chatbots: Chatbot[];
  /** Which vendor's credentials to ask for. The two have nothing in common
   * beyond the assistant and the number, so the form branches rather than
   * showing six fields of which half are always blank. */
  provider: WhatsAppProvider;
  onCreate: (c: WhatsAppChannel) => void;
  onClose: () => void;
}) {
  const isCloud = provider === "cloud";
  const [chatbotId, setChatbotId] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [accountSid, setAccountSid] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [wabaId, setWabaId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WhatsAppChannel | null>(null);

  const credentialsReady = isCloud
    ? Boolean(phoneNumberId && accessToken)
    : Boolean(accountSid && authToken);
  const ready = Boolean(chatbotId && phoneNumber && credentialsReady);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setLoading(true);
    setError(null);
    try {
      const channel = await connectWhatsAppChannel({
        chatbot_id: chatbotId,
        phone_number: phoneNumber,
        provider,
        ...(isCloud
          ? {
              phone_number_id: phoneNumberId.trim(),
              waba_id: wabaId.trim(),
              access_token: accessToken.trim(),
            }
          : { twilio_account_sid: accountSid, twilio_auth_token: authToken }),
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
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">
            {result
              ? "WhatsApp connected"
              : isCloud
                ? "Connect WhatsApp Cloud API"
                : "Connect WhatsApp"}
          </h2>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {result ? (
          <div className="px-6 py-5 space-y-4">
            {result.setup_warning && (
              // The number is connected and still cannot receive anything,
              // because the app secret or verify token is missing from the
              // deployment. Said here because this is the screen the operator
              // is looking at when they wonder why nothing arrives.
              <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
                {result.setup_warning}
              </div>
            )}
            <p className="text-sm text-gray-600">
              {isCloud ? (
                <>
                  Last step — in the Meta App Dashboard under{" "}
                  <strong>WhatsApp → Configuration</strong>, set this as the Callback URL,
                  enter your verify token, then <strong>subscribe to the "messages" field</strong>{" "}
                  (without that subscription nothing is ever delivered):
                </>
              ) : (
                <>
                  Last step — paste this webhook URL into Twilio, under your WhatsApp Sandbox
                  (or Sender) settings, in the <strong>"WHEN A MESSAGE COMES IN"</strong> field:
                </>
              )}
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
              Once saved{isCloud ? " in Meta" : " in Twilio"}, message{" "}
              <strong>{result.phone_number}</strong> on WhatsApp — it'll be answered by{" "}
              <strong>{result.chatbot_name}</strong>.
            </p>
            {isCloud && (
              <p className="text-xs text-gray-400">
                While the number is in development, Meta only delivers messages from the
                phone numbers you added as test recipients under WhatsApp → API Setup.
              </p>
            )}
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
                  {isCloud
                    ? "E.164 format — the display number shown under WhatsApp → API Setup."
                    : "E.164 format. Use your Twilio Sandbox number to start, or your approved WhatsApp Sender later."}
                </p>
              </div>

              {isCloud ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="label">Phone number ID *</label>
                      <input required className="input font-mono text-xs" value={phoneNumberId}
                        onChange={(e) => setPhoneNumberId(e.target.value)} placeholder="100000000000001" />
                    </div>
                    <div>
                      <label className="label">WhatsApp Business Account ID</label>
                      <input className="input font-mono text-xs" value={wabaId}
                        onChange={(e) => setWabaId(e.target.value)} placeholder="200000000000002" />
                    </div>
                  </div>
                  <div>
                    <label className="label">Access token *</label>
                    <input required type="password" className="input font-mono text-xs" value={accessToken}
                      onChange={(e) => setAccessToken(e.target.value)} />
                    <p className="text-xs text-gray-400 mt-1">
                      Use a <strong>permanent System User token</strong> for anything real — the
                      one shown on the API Setup page expires after 24 hours and the number
                      silently stops replying when it does.
                    </p>
                  </div>
                  <p className="text-xs text-gray-400">
                    All three are on the Meta App Dashboard under WhatsApp → API Setup. Stored
                    against this channel only, and never returned once saved.
                  </p>
                </>
              ) : (
                <>
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
                </>
              )}
              {error && (
                <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/60">
              <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={loading || !ready} className="btn-primary">
                {loading ? "Connecting…" : "Connect →"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/* ── Connection method picker ── */

interface Method {
  id: string;
  icon: string;
  title: string;
  description: string;
  available: boolean;
  badge?: string;
  note?: string;
}

const METHODS: Method[] = [
  {
    id: "twilio",
    icon: "🔴",
    title: "Import from Twilio WhatsApp",
    description: "Connect your existing Twilio WhatsApp Business number.",
    available: true,
  },
  {
    id: "phone",
    icon: "💬",
    title: "Phone WhatsApp",
    description: "Scan a QR with your phone. Links your personal account.",
    available: true,
    badge: "Try now",
  },
  {
    id: "cloud",
    icon: "🔵",
    title: "WhatsApp Cloud Business",
    description: "Meta's official Business API. Phone number ID + access token.",
    available: true,
    badge: "Recommended",
  },
  {
    id: "interakt",
    icon: "🟢",
    title: "Import WhatsApp with Interakt",
    description: "Connect via Interakt API key.",
    available: false,
    note: "Needs an Interakt adapter.",
  },
];

function MethodCard({ method, onPick }: { method: Method; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={!method.available}
      title={method.available ? undefined : method.note}
      className={`card p-5 text-left flex flex-col relative transition ${
        method.available
          ? "hover:border-brand-300 hover:shadow-sm cursor-pointer"
          : "opacity-60 cursor-not-allowed"
      }`}
    >
      {method.badge && (
        <span className="absolute top-3 right-3 rounded-full bg-brand-50 text-brand-700 px-2 py-0.5 text-[10px] font-semibold">
          {method.badge}
        </span>
      )}
      <span className="text-3xl" aria-hidden="true">{method.icon}</span>
      <h3 className="text-sm font-semibold text-gray-900 mt-3">{method.title}</h3>
      <p className="text-xs text-gray-500 mt-1 flex-1">{method.description}</p>
      {!method.available && (
        <p className="text-[10px] text-amber-700 mt-2">Setup required</p>
      )}
    </button>
  );
}

/* ── Linked personal (QR) numbers ── */

/** A phone number reduced to what actually identifies it — WhatsApp reports
 * whatever shape the handset registered, so "+971 50 123 4567" and
 * "971501234567" are the same number and never string-equal. */
function digits(phoneNumber: string): string {
  return phoneNumber.replace(/\D/g, "");
}

/**
 * One row per number.
 *
 * The server merges duplicates properly (moving the history across and
 * unlinking the stale device); this is the display-side belt to that braces,
 * for the window between a second scan landing and the merge running. Keeps
 * the first of each group, which is the newest — `listWebSessions` returns
 * newest first, and the newest session is the one holding the live socket.
 */
function dedupeByNumber(sessions: WhatsAppWebSession[]): WhatsAppWebSession[] {
  const seen = new Set<string>();
  return sessions.filter((s) => {
    const key = digits(s.phone_number);
    // A session still pairing has no number yet and is not a duplicate of
    // anything — every one of them has to stay visible to be scannable.
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const WEB_STATUS_STYLES: Record<WhatsAppWebSession["status"], string> = {
  linked: "bg-emerald-100 text-emerald-700",
  awaiting_scan: "bg-amber-100 text-amber-700",
  disconnected: "bg-amber-100 text-amber-700",
  pending: "bg-gray-100 text-gray-600",
  logged_out: "bg-red-100 text-red-700",
  failed: "bg-red-100 text-red-700",
};

function WebSessionRow({
  session,
  chatbots,
  onChanged,
  onResume,
}: {
  session: WhatsAppWebSession;
  chatbots: Chatbot[];
  onChanged: () => void;
  onResume: (s: WhatsAppWebSession) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Why this number is or is not answering. Asked per row rather than once for
  // the page: the bridge check is shared, but "linked", "assistant attached"
  // and "chats handed to a person" are all per number.
  const [readiness, setReadiness] = useState<ReplyReadiness | null>(null);

  useEffect(() => {
    getReplyReadiness(session.id).then(setReadiness).catch(() => setReadiness(null));
  }, [session.id, session.status, session.chatbot_id]);

  async function pickAssistant(chatbotId: string) {
    setBusy(true);
    setError(null);
    try {
      await attachAssistant(session.id, chatbotId || null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not attach the assistant.");
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await unlinkWebSession(session.id);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not unlink.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900">
              {session.phone_number || "Not linked yet"}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${WEB_STATUS_STYLES[session.status]}`}
            >
              {session.status.replace("_", " ")}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">{session.health}</p>
          {/* The single most useful sentence on this page. Every condition
              between an inbound message and a reply used to fail silently —
              a log line and nothing on screen — which is why "it stopped
              replying" kept coming back looking like the same bug when it was
              a different gate each time. */}
          {readiness && (
            <p
              className={`mt-1 flex items-start gap-1.5 text-xs ${
                readiness.ready ? "text-emerald-700" : "text-amber-700"
              }`}
            >
              {readiness.ready ? (
                <Check className="mt-px h-3.5 w-3.5 flex-shrink-0" strokeWidth={2.5} />
              ) : (
                <AlertTriangle className="mt-px h-3.5 w-3.5 flex-shrink-0" strokeWidth={2.5} />
              )}
              <span>{readiness.detail}</span>
            </p>
          )}
          {session.last_error && (
            <p className="text-xs text-red-600 mt-1">{session.last_error}</p>
          )}
          {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select
            className="input h-8 text-xs max-w-[14rem]"
            value={session.chatbot_id ?? ""}
            disabled={busy || session.status !== "linked"}
            onChange={(e) => pickAssistant(e.target.value)}
          >
            <option value="">No assistant — receive only</option>
            {chatbots.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>

          {session.status !== "linked" && (
            <button
              type="button"
              onClick={() => onResume(session)}
              disabled={busy}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Show QR
            </button>
          )}
          {session.status === "linked" && (
            <Link
              to={`/channels/whatsapp/${session.id}/inbox`}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              Open inbox
            </Link>
          )}
          <button
            type="button"
            onClick={unlink}
            disabled={busy}
            className="text-xs text-gray-400 hover:text-red-600 px-2"
          >
            Unlink
          </button>
        </div>
      </div>
    </li>
  );
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<WhatsAppChannel[]>([]);
  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [webSessions, setWebSessions] = useState<WhatsAppWebSession[]>([]);
  const [webOptions, setWebOptions] = useState<WhatsAppWebOptions | null>(null);
  const [qrSession, setQrSession] = useState<WhatsAppWebSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [showConnect, setShowConnect] = useState(false);
  // Which vendor the open connect dialog is asking about. Set by the tile that
  // opened it, so one modal serves both without a second copy of the form.
  const [connectProvider, setConnectProvider] = useState<WhatsAppProvider>("twilio");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Reload the linked numbers, folding any duplicates together first.
   *
   * Scanning the QR for a number that is already connected mints a second
   * session — the row has to exist before the handset reports which number it
   * is, so there is no way to prevent it up front. New ones are absorbed
   * server-side at link time; this heals workspaces that already have them,
   * and is a no-op (and cheap) when there is nothing to merge.
   */
  async function loadWeb() {
    try {
      await mergeDuplicateNumbers();
    } catch {
      // Merging is a tidy-up. If it fails, the list is still worth showing —
      // it will just show the duplicate until the next attempt.
    }
    try {
      setWebSessions(await listWebSessions());
    } catch {
      setWebSessions([]);
    }
  }

  useEffect(() => {
    Promise.all([listWhatsAppChannels(), listChatbots()])
      .then(([c, b]) => { setChannels(c); setChatbots(b); })
      .finally(() => setLoading(false));
    getWhatsAppWebOptions().then(setWebOptions).catch(() => setWebOptions(null));
    void loadWeb();
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

  async function startPhoneLink() {
    if (webOptions && !webOptions.enabled) {
      setError(webOptions.message);
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const session = await createWebSession();
      setQrSession(session);
      await loadWeb();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the pairing session.");
    } finally {
      setStarting(false);
    }
  }

  function pickMethod(id: string) {
    if (id === "twilio" || id === "cloud") {
      setConnectProvider(id === "cloud" ? "cloud" : "twilio");
      setShowConnect(true);
    }
    if (id === "phone") void startPhoneLink();
  }

  return (
    <div className="page">
      {showConnect && (
        <ConnectModal
          chatbots={chatbots}
          provider={connectProvider}
          onCreate={handleCreated}
          onClose={() => setShowConnect(false)}
        />
      )}
      {qrSession && (
        <WhatsAppQrModal
          session={qrSession}
          onClose={() => { setQrSession(null); void loadWeb(); }}
          onLinked={() => { setQrSession(null); void loadWeb(); }}
        />
      )}

      <div className="page-header" data-tour="channels-grid">
        <div>
          <h1 className="page-title">WhatsApp</h1>
          <p className="text-sm text-gray-500 mt-1">Connect and manage your WhatsApp numbers.</p>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <div className="text-center mb-6">
        <h2 className="text-lg font-semibold text-gray-900">Connect WhatsApp</h2>
        <p className="text-sm text-gray-500 mt-1">
          Pick a method below, attach your assistant, and let it handle replies.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 mb-8">
        {METHODS.map((method) => (
          <MethodCard
            key={method.id}
            method={
              method.id === "phone" && webOptions && !webOptions.enabled
                ? { ...method, available: false, note: webOptions.message }
                : method
            }
            onPick={() => pickMethod(method.id)}
          />
        ))}
      </div>

      {starting && (
        <p className="text-sm text-gray-500 mb-4">Starting a pairing session…</p>
      )}

      {webOptions?.enabled && !webOptions.bridge_healthy && (
        <div className="mb-6 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800">
          The WhatsApp bridge isn't responding right now. {webOptions.message}
        </div>
      )}

      {webSessions.length > 0 && (
        <div className="card p-5 mb-6">
          <h2 className="section-title mb-1">Linked personal numbers</h2>
          <p className="text-xs text-gray-500 mb-4">
            Inbound only — these answer people who message them. Broadcasts run on
            Twilio numbers, where recipients opted in.
          </p>
          <ul className="divide-y divide-gray-100">
            {dedupeByNumber(webSessions).map((s) => (
              <WebSessionRow
                key={s.id}
                session={s}
                chatbots={chatbots}
                onChanged={loadWeb}
                onResume={setQrSession}
              />
            ))}
          </ul>
        </div>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="section-title">Business numbers</h2>
          <span className="text-xs text-gray-400">
            {loading ? "Loading…" : `${channels.length} connected`}
          </span>
        </div>

        {channels.length === 0 ? (
          <p className="text-sm text-gray-400 py-4">
            No business numbers connected. Meta's Cloud API is the official route —
            a test number is free under WhatsApp → API Setup. Twilio's WhatsApp
            Sandbox works too, under Messaging → Try it out.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Assistant</th><th>Number</th><th>Provider</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {channels.map((c) => (
                  <tr key={c.id}>
                    <td className="font-medium text-gray-900">{c.chatbot_name}</td>
                    <td className="font-mono text-xs text-gray-600">{c.phone_number}</td>
                    <td className="text-xs text-gray-600">
                      {c.provider === "cloud" ? "Meta Cloud API" : "Twilio"}
                      {/* A connected number that still cannot receive anything,
                          because the deployment is missing its app secret or
                          verify token. Shown on the row, since this list is
                          where someone looks when nothing arrives. */}
                      {c.setup_warning && (
                        <span title={c.setup_warning} className="ml-1.5 text-amber-600">
                          &#9888;
                        </span>
                      )}
                    </td>
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
      </div>
    </div>
  );
}
