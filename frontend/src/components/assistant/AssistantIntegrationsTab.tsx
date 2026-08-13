// Integrations, seen from inside one assistant.
//
// Connections are held per workspace, not per assistant — one Google Calendar
// consent serves every assistant you build. This tab exists so you can connect
// what an assistant needs without leaving it, and it says plainly that the
// connection is shared, so nobody expects two assistants to hold two calendars.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Info, Loader2 } from "lucide-react";
import {
  IntegrationCard,
  IntegrationCategory,
  CATEGORY_ORDER,
  getIntegrationCatalogue,
} from "../../api/integrationsCatalogue";
import { ApiError } from "../../api/client";
import IntegrationCardTile from "../IntegrationCardTile";

export default function AssistantIntegrationsTab() {
  const [cards, setCards] = useState<IntegrationCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<IntegrationCategory | "all">("all");

  const load = useCallback(async () => {
    try {
      setCards((await getIntegrationCatalogue()).integrations);
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

  const visible = category === "all" ? cards : cards.filter((c) => c.category === category);
  const connected = cards.filter((c) => c.connected).length;

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 py-10 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
        Loading integrations…
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3.5 flex items-start gap-3">
        <Info className="w-4 h-4 mt-0.5 flex-shrink-0 text-blue-700" strokeWidth={2} />
        <p className="text-[13px] leading-relaxed text-blue-900">
          Integrations are connected once for the whole workspace and are then
          available to every assistant — including this one. {connected} of{" "}
          {cards.length} connected. Manage them all on the{" "}
          <Link to="/integrations" className="underline font-medium">
            Integrations
          </Link>{" "}
          page.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
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
          </button>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {visible.map((card) => (
          <IntegrationCardTile key={card.id} card={card} onChanged={load} />
        ))}
      </div>
    </div>
  );
}
