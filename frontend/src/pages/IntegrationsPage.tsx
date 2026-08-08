// Integrations catalogue: browse everything the platform can connect to, filter
// by category, and connect the ones that are wired.
//
// Cards for integrations that aren't wired yet still render — hiding them would
// misrepresent the roadmap — but their Connect button is disabled and says why.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  CATEGORY_ORDER,
  IntegrationCard,
  IntegrationCategory,
  connectIntegration,
  disconnectIntegration,
  getIntegrationCatalogue,
  testIntegration,
} from "../api/integrationsCatalogue";
import { connectGoogle } from "../api/integrations";

function TimingBadge({ timing }: { timing: IntegrationCard["timing"] }) {
  const during = timing === "during_call";
  return (
    <span
      title={
        during
          ? "The assistant can call this while a conversation is happening."
          : "Runs after a conversation ends, as part of post-call delivery."
      }
      className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${
        during
          ? "border-emerald-300 text-emerald-700 bg-emerald-50"
          : "border-blue-300 text-blue-700 bg-blue-50"
      }`}
    >
      {during ? "During Call" : "Post Call"}
    </span>
  );
}

function ConnectModal({
  card,
  onClose,
  onConnected,
}: {
  card: IntegrationCard;
  onClose: () => void;
  onConnected: (c: IntegrationCard) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onConnected(await connectIntegration(card.id, values));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="card w-full max-w-lg p-6 space-y-4">
        <div>
          <h2 className="section-title">Connect {card.name}</h2>
          <p className="text-xs text-gray-500 mt-1">{card.description}</p>
        </div>

        {card.credential_fields.map((field) => (
          <div key={field.key}>
            <label className="label">
              {field.label} {field.required && "*"}
            </label>
            <input
              className="input font-mono text-xs"
              type={field.secret ? "password" : "text"}
              placeholder={field.placeholder}
              required={field.required}
              value={values[field.key] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.key]: e.target.value }))
              }
            />
            {field.help_text && (
              <p className="text-xs text-gray-400 mt-1">{field.help_text}</p>
            )}
          </div>
        ))}

        {card.connected && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            {card.name} is already connected. Saving replaces the stored
            credentials — use this to rotate a leaked value.
          </p>
        )}

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="btn-primary text-sm">
            {saving ? "Connecting…" : "Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Card({
  card,
  onChanged,
  onConnectClick,
}: {
  card: IntegrationCard;
  onChanged: () => void;
  onConnectClick: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  async function startOAuth() {
    setBusy(true);
    try {
      // Navigates the whole page to the consent screen on success, so nothing
      // after this runs unless it threw.
      await connectGoogle();
    } catch (e) {
      setNote({
        ok: false,
        text: e instanceof ApiError ? e.message : "Could not start authorization.",
      });
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setNote(null);
    try {
      const result = await testIntegration(card.id);
      setNote({ ok: result.ok, text: result.message });
    } catch (e) {
      setNote({ ok: false, text: e instanceof ApiError ? e.message : "Test failed." });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await disconnectIntegration(card.id);
      onChanged();
    } catch (e) {
      setNote({ ok: false, text: e instanceof ApiError ? e.message : "Could not disconnect." });
    } finally {
      setBusy(false);
    }
  }

  // WhatsApp is connected per-chatbot under Channels, not tenant-wide here.
  const managedElsewhere = card.id === "whatsapp_twilio";

  return (
    <div className="card p-5 flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-gray-900">{card.name}</h3>
            {card.connected && (
              <span className="rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5 text-[10px] font-semibold">
                Connected
              </span>
            )}
          </div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 mt-1">
            {card.category_label}
          </p>
        </div>
        <TimingBadge timing={card.timing} />
      </div>

      <p className="text-sm text-gray-600 mt-3 flex-1">{card.description}</p>

      {card.connected && Object.keys(card.config).length > 0 && (
        <dl className="mt-3 space-y-1">
          {Object.entries(card.config).map(([key, value]) => (
            <div key={key} className="flex gap-2 text-xs">
              <dt className="text-gray-400">{key}</dt>
              <dd className="font-mono text-gray-600 truncate">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {!card.wired && card.unavailable_reason && (
        <p className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {card.unavailable_reason}
        </p>
      )}

      {note && (
        <p
          role="status"
          className={`mt-3 text-xs rounded-lg px-3 py-2 border ${
            note.ok
              ? "text-emerald-800 bg-emerald-50 border-emerald-200"
              : "text-red-700 bg-red-50 border-red-200"
          }`}
        >
          {note.text}
        </p>
      )}

      <div className="mt-4 pt-4 border-t border-gray-100 flex items-center gap-2 flex-wrap">
        {managedElsewhere ? (
          <Link to="/channels" className="btn-secondary text-xs px-3 py-1.5 h-auto">
            Manage in Channels →
          </Link>
        ) : card.auth === "oauth" ? (
          <button
            type="button"
            onClick={startOAuth}
            disabled={busy}
            className="btn-secondary text-xs px-3 py-1.5 h-auto"
          >
            {card.connected ? "Reconnect" : "Connect"}
          </button>
        ) : (
          <button
            type="button"
            onClick={onConnectClick}
            disabled={!card.wired || busy}
            title={card.wired ? undefined : card.unavailable_reason}
            className="btn-secondary text-xs px-3 py-1.5 h-auto disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {card.connected ? "Update credentials" : "Connect"}
          </button>
        )}

        {card.connected && card.wired && !managedElsewhere && card.auth !== "oauth" && (
          <>
            <button
              type="button"
              onClick={runTest}
              disabled={busy}
              className="btn-secondary text-xs px-3 py-1.5 h-auto"
            >
              {busy ? "Testing…" : "Send test"}
            </button>
            <button
              type="button"
              onClick={remove}
              disabled={busy}
              className="text-xs text-gray-400 hover:text-red-600 px-2"
            >
              Disconnect
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function IntegrationsPage() {
  const [cards, setCards] = useState<IntegrationCard[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [connectedCount, setConnectedCount] = useState(0);
  const [category, setCategory] = useState<IntegrationCategory | "all">("all");
  const [search, setSearch] = useState("");
  const [onlyConnected, setOnlyConnected] = useState(false);
  const [modalFor, setModalFor] = useState<IntegrationCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const data = await getIntegrationCatalogue();
      setCards(data.integrations);
      setCounts(data.counts);
      setConnectedCount(data.connected_count);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load integrations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return cards.filter((c) => {
      if (onlyConnected && !c.connected) return false;
      if (category !== "all" && c.category !== category) return false;
      if (!term) return true;
      return (
        c.name.toLowerCase().includes(term) ||
        c.description.toLowerCase().includes(term) ||
        c.category_label.toLowerCase().includes(term)
      );
    });
  }, [cards, category, search, onlyConnected]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="page-title">Integrations</h1>
        <p className="text-sm text-gray-500 mt-1">
          Connect your account with other services to extend what your assistants
          can do.
        </p>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex flex-wrap gap-2">
          {CATEGORY_ORDER.map((c) => (
            <button
              key={c.value}
              type="button"
              aria-pressed={category === c.value}
              onClick={() => setCategory(c.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                category === c.value
                  ? "bg-brand-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {c.label}{" "}
              <span className="tabular-nums opacity-75">{counts[c.value] ?? 0}</span>
            </button>
          ))}
        </div>
        <input
          className="input h-8 text-sm max-w-xs ml-auto"
          placeholder="Search integrations…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="segmented mb-6 inline-flex">
        <button
          type="button"
          onClick={() => setOnlyConnected(false)}
          className={!onlyConnected ? "segmented-item-active" : "segmented-item"}
        >
          All Integrations
        </button>
        <button
          type="button"
          onClick={() => setOnlyConnected(true)}
          className={onlyConnected ? "segmented-item-active" : "segmented-item"}
        >
          Connected {connectedCount > 0 && `(${connectedCount})`}
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : visible.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="text-sm text-gray-500">
            {onlyConnected ? "Nothing connected yet." : "No integrations match that filter."}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((card) => (
            <Card
              key={card.id}
              card={card}
              onChanged={load}
              onConnectClick={() => setModalFor(card)}
            />
          ))}
        </div>
      )}

      {modalFor && (
        <ConnectModal
          card={modalFor}
          onClose={() => setModalFor(null)}
          onConnected={() => {
            setModalFor(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
