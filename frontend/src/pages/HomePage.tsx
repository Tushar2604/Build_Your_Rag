import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, MessagesSquare, Bot, Database, Sparkles, ArrowRight } from "lucide-react";
import { listChatbots, Chatbot } from "../api/chatbots";
import { listDocuments } from "../api/documents";
import { getChatbotAnalytics, getChatbotRequests, RequestLog, ChatbotAnalytics } from "../api/analytics";

function StatusDot({ live }: { live: boolean }) {
  return (
    <span className={live ? "dot-live" : "dot-draft"} />
  );
}

function MetricCard({
  label, value, sub, icon: Icon, index,
}: { label: string; value: string; sub?: string; icon: typeof MessagesSquare; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.06, ease: "easeOut" }}
      className="metric-card"
    >
      <div className="metric-card-icon">
        <Icon className="w-4 h-4" strokeWidth={1.75} />
      </div>
      <p className="metric-card-label">{label}</p>
      <p className="metric-card-value">{value}</p>
      {sub && <p className="metric-card-hint">{sub}</p>}
    </motion.div>
  );
}

function SkeletonRow() {
  return (
    <tr>
      <td className="px-4 py-3"><div className="skeleton h-4 w-32" /></td>
      <td className="px-4 py-3"><div className="skeleton h-4 w-12" /></td>
      <td className="px-4 py-3"><div className="skeleton h-4 w-16" /></td>
      <td className="px-4 py-3"><div className="skeleton h-4 w-10" /></td>
    </tr>
  );
}

interface AssistantRow {
  bot: Chatbot;
  totalQueries: number;
  avgScore: number | null;
}

export default function HomePage() {
  const [rows, setRows]               = useState<AssistantRow[]>([]);
  const [recentLogs, setRecentLogs]   = useState<RequestLog[]>([]);
  const [docStats, setDocStats]       = useState<{ total: number; ready: number } | null>(null);
  const [loading, setLoading]         = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [bots, docs] = await Promise.all([
          listChatbots(),
          listDocuments().catch(() => []),
        ]);
        setDocStats({ total: docs.length, ready: docs.filter((d) => d.status === "ready").length });
        if (bots.length === 0) { setLoading(false); return; }

        const analyticsResults = await Promise.allSettled(
          bots.map((b) => getChatbotAnalytics(b.id, 7))
        );

        const assembled: AssistantRow[] = bots.map((bot, i) => {
          const res = analyticsResults[i];
          if (res.status !== "fulfilled") return { bot, totalQueries: 0, avgScore: null };
          const data: ChatbotAnalytics = res.value;
          const total = data.daily.reduce((a, d) => a + d.answers, 0);
          const scored = data.daily.filter((d) => d.avg_top_score !== null);
          const avgScore = scored.length > 0
            ? scored.reduce((a, d) => a + (d.avg_top_score ?? 0), 0) / scored.length
            : null;
          return { bot, totalQueries: total, avgScore };
        });

        setRows(assembled);

        // recent logs from the first chatbot only
        try {
          const logs = await getChatbotRequests(bots[0].id, 8);
          setRecentLogs(logs);
        } catch { /* silent */ }
      } catch { /* silent */ }
      finally { setLoading(false); }
    }
    load();
  }, []);

  const totalQueries = rows.reduce((a, r) => a + r.totalQueries, 0);
  const liveCount    = rows.filter((r) => r.bot.is_public).length;

  const hour   = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="page max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{greeting}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading
              ? "Loading platform status…"
              : `${rows.length} assistant${rows.length !== 1 ? "s" : ""} · ${liveCount} live · platform healthy`
            }
          </p>
        </div>
        <Link to="/assistants" className="btn-cta">
          <Plus className="w-4 h-4" strokeWidth={2.25} />
          New assistant
        </Link>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <MetricCard
          index={0}
          icon={MessagesSquare}
          label="Queries (7 days)"
          value={loading ? "—" : totalQueries.toLocaleString()}
          sub="across all assistants"
        />
        <MetricCard
          index={1}
          icon={Bot}
          label="Assistants live"
          value={loading ? "—" : `${liveCount} / ${rows.length}`}
          sub="deployed to production"
        />
        <MetricCard
          index={2}
          icon={Database}
          label="Knowledge sources"
          value={loading || !docStats ? "—" : `${docStats.ready} / ${docStats.total}`}
          sub={docStats && docStats.total > 0 ? "indexed / total" : "connect via Knowledge tab"}
        />
      </div>

      {/* Assistants table */}
      <div className="card card-hover mb-6 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="section-title">Assistants</h2>
          <Link to="/assistants" className="text-xs text-brand-600 hover:text-brand-700 font-medium inline-flex items-center gap-1 group">
            View all <ArrowRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
        {loading ? (
          <table className="data-table">
            <tbody>
              <SkeletonRow /><SkeletonRow /><SkeletonRow />
            </tbody>
          </table>
        ) : rows.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <p className="text-sm text-gray-500">No assistants yet.</p>
            <Link to="/assistants" className="btn-cta mt-4 inline-flex">
              Create your first assistant
            </Link>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th className="text-right">Queries (7d)</th>
                <th className="text-right">Avg score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ bot, totalQueries: q, avgScore }) => (
                <tr key={bot.id}>
                  <td>
                    <Link
                      to={`/assistants/${bot.id}`}
                      className="font-medium text-gray-900 hover:text-brand-700 transition-colors"
                    >
                      {bot.name}
                    </Link>
                  </td>
                  <td>
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${bot.is_public ? "text-emerald-700" : "text-gray-500"}`}>
                      <StatusDot live={bot.is_public} />
                      {bot.is_public ? "Live" : "Draft"}
                    </span>
                  </td>
                  <td className="text-right tabular-nums">
                    {q > 0 ? q.toLocaleString() : <span className="text-gray-400">—</span>}
                  </td>
                  <td className="text-right tabular-nums">
                    {avgScore !== null
                      ? <span className={avgScore >= 0.7 ? "text-emerald-700" : "text-amber-700"}>{avgScore.toFixed(2)}</span>
                      : <span className="text-gray-400">—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent activity */}
      {recentLogs.length > 0 && (
        <div className="card card-hover overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="section-title">Recent queries</h2>
            <Link to="/analytics" className="text-xs text-brand-600 hover:text-brand-700 font-medium inline-flex items-center gap-1 group">
              View analytics <ArrowRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Status</th>
                <th className="text-right">Latency</th>
                <th className="text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {recentLogs.slice(0, 6).map((log) => (
                <tr key={log.id}>
                  <td>
                    <span className="text-gray-700 max-w-xs truncate block" title={log.query}>
                      {log.query}
                    </span>
                  </td>
                  <td>
                    {log.status === "ok" && !log.no_context && !log.refused
                      ? <span className="badge badge-live">answered</span>
                      : log.no_context
                      ? <span className="badge badge-paused">no context</span>
                      : log.refused
                      ? <span className="badge badge-paused">refused</span>
                      : <span className="badge badge-error">error</span>
                    }
                  </td>
                  <td className="text-right tabular-nums text-gray-500 text-xs">{log.latency_ms}ms</td>
                  <td className="text-right text-gray-400 text-xs whitespace-nowrap">
                    {new Date(log.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Empty home when nothing is set up — treated as a mini marketing moment */}
      {!loading && rows.length === 0 && recentLogs.length === 0 && (
        <div className="relative overflow-hidden rounded-2xl mesh-bg border border-gray-200/80 p-12 text-center">
          <div className="relative">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center mx-auto mb-5 shadow-lift">
              <Sparkles className="w-7 h-7 text-white" strokeWidth={1.75} />
            </div>
            <h2 className="hero-title text-2xl md:text-3xl">Welcome to Kore AI</h2>
            <p className="hero-subtitle mx-auto">
              Deploy production-ready AI assistants powered by your knowledge. Start by connecting a knowledge source and creating your first assistant.
            </p>
            <div className="flex items-center gap-3 justify-center mt-6">
              <Link to="/knowledge" className="btn-secondary">Connect knowledge</Link>
              <Link to="/assistants" className="btn-cta">Create assistant</Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
