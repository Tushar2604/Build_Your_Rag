import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../store/auth";
import { listChatbots, Chatbot } from "../api/chatbots";
import { getChatbotRequests, RequestLog } from "../api/analytics";
import { getGoogleStatus, connectGoogle, disconnectGoogle, GoogleStatus } from "../api/integrations";
import { ApiError } from "../api/client";

type Tab = "general" | "apikeys" | "integrations" | "audit";

const TABS: { id: Tab; label: string }[] = [
  { id: "general",      label: "General"      },
  { id: "apikeys",      label: "API Keys"     },
  { id: "integrations", label: "Integrations" },
  { id: "audit",        label: "Audit log"    },
];

/* ── General tab ── */
function GeneralTab() {
  const { tenantId } = useAuth();

  return (
    <div className="space-y-6 max-w-xl">
      <div className="card p-5 space-y-4">
        <h3 className="section-title">Organisation</h3>
        <div>
          <label className="label">Organisation ID</label>
          <input readOnly value={tenantId ?? "—"} className="input font-mono text-xs text-gray-500" />
          <p className="text-xs text-gray-400 mt-1">Used when integrating with external services.</p>
        </div>
      </div>

      <div className="card p-5 space-y-4">
        <h3 className="section-title">Platform</h3>
        <div className="space-y-3 text-sm text-gray-700">
          <div className="flex items-center justify-between py-2 border-b border-gray-50">
            <span className="text-gray-600">Model</span>
            <span className="font-medium font-mono text-xs">claude-sonnet-4-6</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-gray-50">
            <span className="text-gray-600">Embedding model</span>
            <span className="font-medium font-mono text-xs">text-embedding-3-small</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-gray-50">
            <span className="text-gray-600">Vector store</span>
            <span className="font-medium font-mono text-xs">pgvector</span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-gray-600">API version</span>
            <span className="font-medium font-mono text-xs">v1</span>
          </div>
        </div>
      </div>

      <div className="card p-5">
        <h3 className="section-title mb-3">Danger zone</h3>
        <p className="text-sm text-gray-500 mb-4">These actions are irreversible. Proceed with caution.</p>
        <button
          type="button"
          className="btn border border-red-200 text-red-600 hover:bg-red-50 bg-white"
          onClick={() => alert("Contact support to delete your organisation account.")}
        >
          Delete organisation
        </button>
      </div>
    </div>
  );
}

/* ── API Keys tab ── */
function ApiKeysTab() {
  const [bots,    setBots]    = useState<Chatbot[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied,  setCopied]  = useState<string | null>(null);

  useEffect(() => {
    listChatbots().then(setBots).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function copy(val: string, id: string) {
    navigator.clipboard.writeText(val);
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="rounded-xl bg-amber-50 border border-amber-200 px-5 py-3 text-sm text-amber-900">
        <p className="font-semibold">Publishable keys only</p>
        <p className="text-amber-800/80 mt-0.5 text-xs">
          These keys are safe to embed in public-facing pages. They only allow reading from public assistants.
          Your authentication tokens (Bearer) are separate and must never be exposed publicly.
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(2)].map((_, i) => <div key={i} className="card p-5"><div className="skeleton h-4 w-48 mb-2" /><div className="skeleton h-8 w-full" /></div>)}
        </div>
      ) : bots.length === 0 ? (
        <div className="card p-8 text-center text-sm text-gray-500">
          No assistants yet. Create an assistant to get a publishable key.
        </div>
      ) : (
        <div className="space-y-4">
          {bots.map((bot) => (
            <div key={bot.id} className="card p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="text-sm font-medium text-gray-900">{bot.name}</p>
                  <p className={`text-xs mt-0.5 ${bot.is_public ? "text-emerald-600" : "text-gray-400"}`}>
                    {bot.is_public ? "Live · Public access enabled" : "Draft · Not publicly accessible"}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <div>
                  <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide block mb-1">Publishable key</label>
                  <div className="flex items-center gap-2">
                    <input readOnly value={bot.public_key} className="input flex-1 font-mono text-xs text-gray-600" />
                    <button
                      onClick={() => copy(bot.public_key, `key-${bot.id}`)}
                      className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap"
                    >
                      {copied === `key-${bot.id}` ? "Copied!" : "Copy"}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide block mb-1">Embed snippet</label>
                  <div className="flex items-start gap-2">
                    <pre className="text-[10px] font-mono bg-gray-50 border border-gray-200 rounded-lg p-2 flex-1 overflow-x-auto whitespace-pre-wrap break-all text-gray-700">
                      {bot.embed_snippet}
                    </pre>
                    <button
                      onClick={() => copy(bot.embed_snippet, `snippet-${bot.id}`)}
                      className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap flex-shrink-0"
                    >
                      {copied === `snippet-${bot.id}` ? "Copied!" : "Copy"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card p-5">
        <h3 className="section-title mb-2">REST API base URL</h3>
        <div className="flex items-center gap-2">
          <input readOnly value={`${window.location.origin}/api/v1`} className="input flex-1 font-mono text-xs text-gray-600" />
          <button onClick={() => copy(`${window.location.origin}/api/v1`, "base-url")} className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap">
            {copied === "base-url" ? "Copied!" : "Copy"}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Authenticate with <code className="font-mono bg-gray-100 px-1 rounded">Authorization: Bearer &lt;access_token&gt;</code>
        </p>
      </div>
    </div>
  );
}

/* ── Integrations tab ── */
function IntegrationsTab() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    getGoogleStatus()
      .then(setStatus)
      .catch(() => setStatus({ connected: false, email: "" }))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await connectGoogle();
      // navigation away happens inside connectGoogle(); nothing else to do
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start Google connection.");
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await disconnectGoogle();
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to disconnect.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div className="card p-5 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="section-title">Google Calendar</h3>
            <p className="text-xs text-gray-500 mt-1 max-w-sm">
              Connect a Google account so scheduled Virtual Interviews are automatically added to your calendar, with the candidate invited.
            </p>
          </div>
          <svg className="w-8 h-8 flex-shrink-0" viewBox="0 0 48 48">
            <path fill="#4285F4" d="M45 24c0-1.6-.1-2.8-.4-4.1H24v7.5h11.9c-.2 2-1.6 5-4.6 7l7.4 5.7C42.9 35.8 45 30.4 45 24z"/>
            <path fill="#34A853" d="M24 46c6.2 0 11.4-2 15.2-5.5l-7.4-5.7c-2 1.4-4.7 2.3-7.8 2.3-6 0-11.1-4-12.9-9.5l-7.6 5.9C7.4 40.8 15 46 24 46z"/>
            <path fill="#FBBC05" d="M11.1 27.6c-.5-1.4-.7-2.9-.7-4.6s.3-3.2.7-4.6l-7.6-5.9C1.6 15.6 1 19.6 1 23s.6 7.4 2.5 10.5z"/>
            <path fill="#EA4335" d="M24 10.7c3.4 0 5.8 1.5 7.1 2.7l6.5-6.3C33.6 3.5 30.2 2 24 2 15 2 7.4 7.2 3.5 14.5l7.6 5.9c1.8-5.5 6.9-9.7 12.9-9.7z"/>
          </svg>
        </div>

        {loading ? (
          <div className="skeleton h-9 w-40" />
        ) : status?.connected ? (
          <div className="flex items-center justify-between rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-emerald-800">Connected</p>
              {status.email && <p className="text-xs text-emerald-700 mt-0.5">{status.email}</p>}
            </div>
            <button onClick={disconnect} disabled={busy} className="btn-secondary text-xs px-3 py-1.5 h-auto">
              {busy ? "Disconnecting…" : "Disconnect"}
            </button>
          </div>
        ) : (
          <button onClick={connect} disabled={busy} className="btn-primary">
            {busy ? "Redirecting…" : "Connect Google Calendar"}
          </button>
        )}

        {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
      </div>

      <div className="card p-5">
        <h3 className="section-title mb-2">Email delivery (Resend)</h3>
        <p className="text-xs text-gray-500">
          Interview invite emails are sent via Resend, configured with <code className="font-mono bg-gray-100 px-1 rounded">RESEND_API_KEY</code> in
          the server's environment — not here. Without it, scheduling still works; you'll get a link to share manually instead.
        </p>
      </div>
    </div>
  );
}

/* ── Audit log tab ── */
function AuditTab() {
  const [bots,     setBots]     = useState<Chatbot[]>([]);
  const [logs,     setLogs]     = useState<RequestLog[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [selected, setSelected] = useState<string>("");

  useEffect(() => {
    listChatbots()
      .then(async (b) => {
        setBots(b);
        if (b.length > 0) {
          setSelected(b[0].id);
          const r = await getChatbotRequests(b[0].id, 100);
          setLogs(r);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function loadLogs(botId: string) {
    setSelected(botId); setLoading(true);
    try {
      const r = await getChatbotRequests(botId, 100);
      setLogs(r);
    } catch { setLogs([]); }
    finally { setLoading(false); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          className="input w-auto"
          value={selected}
          onChange={(e) => loadLogs(e.target.value)}
        >
          {bots.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <span className="text-xs text-gray-500">{logs.length} requests logged</span>
      </div>

      {loading ? (
        <div className="card p-8 text-center text-sm text-gray-400">Loading audit log…</div>
      ) : logs.length === 0 ? (
        <div className="card p-8 text-center text-sm text-gray-400">No requests logged for this assistant.</div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Query</th>
                  <th>Result</th>
                  <th className="text-right">Score</th>
                  <th className="text-right">Tokens</th>
                  <th className="text-right">Latency</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap text-xs text-gray-500">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="max-w-xs">
                      <span className="truncate block" title={r.error ?? r.answer ?? r.query}>{r.query}</span>
                    </td>
                    <td>
                      {r.status === "error"
                        ? <span className="badge badge-error">error</span>
                        : r.no_context
                        ? <span className="badge badge-paused">no context</span>
                        : r.refused
                        ? <span className="badge badge-paused">refused</span>
                        : <span className="badge badge-live">answered</span>
                      }
                    </td>
                    <td className="text-right tabular-nums">{r.max_score !== null ? r.max_score.toFixed(3) : "—"}</td>
                    <td className="text-right tabular-nums">{r.tokens_used}</td>
                    <td className="text-right tabular-nums text-xs">{r.latency_ms}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main ── */
export default function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") ?? "general") as Tab;

  function setTab(tab: Tab) { setSearchParams({ tab }, { replace: true }); }

  return (
    <div className="page">
      <div className="mb-6">
        <h1 className="page-title">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">Organisation configuration, API access, and platform audit log.</p>
      </div>

      <div className="tab-bar mb-6">
        {TABS.map((t) => (
          <button key={t.id} type="button" onClick={() => setTab(t.id)}
            className={activeTab === t.id ? "tab-item-active" : "tab-item"}>
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "general"      && <GeneralTab />}
      {activeTab === "apikeys"      && <ApiKeysTab />}
      {activeTab === "integrations" && <IntegrationsTab />}
      {activeTab === "audit"        && <AuditTab />}
    </div>
  );
}
