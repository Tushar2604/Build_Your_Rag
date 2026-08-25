// Integrations catalogue: browse everything the platform can connect to, filter
// by category, and connect the ones that are wired.
//
// Two connect paths, decided by the integration rather than by the user:
// consent-based vendors (Google Calendar, Google Sheets, Cal.com) open a popup
// and are connected in one click; the rest open a small credentials form,
// because a webhook URL genuinely is the credential and there is nothing to
// consent to.
//
// Cards for integrations that aren't wired yet still render — hiding them would
// misrepresent the roadmap — but their Connect button is disabled and says why.
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Search } from "lucide-react";
import { ApiError } from "../api/client";
import {
  CATEGORY_ORDER,
  IntegrationCard,
  IntegrationCategory,
  connectIntegration,
  getIntegrationCatalogue,
} from "../api/integrationsCatalogue";
import IntegrationCardTile from "../components/IntegrationCardTile";

/** Credentials form — only for integrations with no consent flow to run. */
function ConnectModal({
  card,
  onClose,
  onConnected,
}: {
  card: IntegrationCard;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await connectIntegration(card.id, values);
      onConnected();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect.");
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-title"
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form onSubmit={submit} className="card w-full max-w-lg p-6 space-y-4 animate-scale-in">
        <div>
          <h2 id="connect-title" className="text-[15px] font-semibold text-gray-900">
            Connect {card.name}
          </h2>
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
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
            />
            {field.help_text && <p className="text-xs text-gray-400 mt-1">{field.help_text}</p>}
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

export default function IntegrationsPage() {
  const [cards, setCards] = useState<IntegrationCard[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [connectedCount, setConnectedCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<IntegrationCategory | "all">("all");
  const [query, setQuery] = useState("");
  const [credentialCard, setCredentialCard] = useState<IntegrationCard | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getIntegrationCatalogue();
      setCards(data.integrations);
      setCounts(data.counts);
      setConnectedCount(data.connected_count);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load integrations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cards.filter((c) => {
      if (category !== "all" && c.category !== category) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q)
      );
    });
  }, [cards, category, query]);

  const oneClickCount = cards.filter((c) => c.auth === "oauth" && c.wired).length;

  return (
    <div className="page">
      {credentialCard && (
        <ConnectModal
          card={credentialCard}
          onClose={() => setCredentialCard(null)}
          onConnected={() => {
            setCredentialCard(null);
            load();
          }}
        />
      )}

      <header className="page-header">
        <div>
          <h1 className="page-title">Integrations</h1>
          <p className="page-subtitle">
          Connect the tools your assistants act through.{" "}
          {oneClickCount > 0 && (
            <span className="text-gray-400">
              {oneClickCount} connect in one click — you approve them in your own
              account, no keys to copy.
            </span>
          )}
          </p>
        </div>
      </header>

      {/* Summary + search */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 border border-emerald-200
                         px-3 py-1.5 text-[13px] font-medium text-emerald-700">
          <CheckCircle2 className="w-3.5 h-3.5" strokeWidth={2} />
          {connectedCount} connected
        </span>
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" strokeWidth={1.75} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search integrations…"
            aria-label="Search integrations"
            className="input pl-9"
          />
        </div>
      </div>

      {/* Category filter */}
      <div className="flex flex-wrap gap-2 mb-6">
        {CATEGORY_ORDER.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => setCategory(c.value)}
            aria-pressed={category === c.value}
            className={`rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition-colors ${
              category === c.value
                ? "bg-brand-500/15 text-brand-400 ring-1 ring-inset ring-brand-500/40"
                : "bg-surface-2 text-gray-500 hover:text-gray-900"
            }`}
          >
            {c.label}
            {counts[c.value] !== undefined && (
              <span className="ml-1.5 text-gray-500">{counts[c.value]}</span>
            )}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="mb-5 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500 py-14 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
          Loading integrations…
        </div>
      ) : visible.length === 0 ? (
        <p className="text-sm text-gray-500 py-14 text-center">
          Nothing matches that search.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((card) => (
            <IntegrationCardTile
              key={card.id}
              card={card}
              onChanged={load}
              onRequestCredentials={setCredentialCard}
            />
          ))}
        </div>
      )}
    </div>
  );
}
