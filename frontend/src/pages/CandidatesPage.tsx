// Candidates — every WhatsApp contact this workspace has talked to, as a
// browsable grid of profile cards.
//
// A grid rather than a mail-style thread rail: this is not an inbox to work
// through in order, it is a roster to search and pick from, and the questions
// asked of it ("who sent a resume?", "who went quiet?") are answered by
// scanning many contacts at once rather than reading one deeply. Opening a
// card goes to that candidate's own page, so a profile can be linked and
// shared rather than living inside this page's transient selection.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, MessageSquare, Paperclip, Search, Users } from "lucide-react";

import { Candidate, listCandidates } from "../api/candidates";
import { ApiError } from "../api/client";
import { Avatar, timeLabel } from "../components/ConversationThread";

type FilterKey = "all" | "unread" | "documents";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "documents", label: "Has documents" },
];

function filterParams(key: FilterKey) {
  switch (key) {
    case "unread":
      return { unreadOnly: true };
    case "documents":
      return { hasAttachment: true };
    default:
      return {};
  }
}

/** The one-line status that decides how a card reads at a glance. Ordered by
 * what an HR user needs to act on first: an unanswered reply beats every
 * automated state behind it. */
function statusFor(c: Candidate): { label: string; className: string } {
  if (c.unread_count > 0) {
    return {
      label: `${c.unread_count} new repl${c.unread_count === 1 ? "y" : "ies"}`,
      className: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    };
  }
  if (!c.auto_reply) {
    return { label: "Handled by you", className: "bg-amber-50 text-amber-700 ring-amber-200" };
  }
  if (c.followups_sent > 2) {
    return { label: "No response", className: "bg-gray-100 text-gray-600 ring-gray-200" };
  }
  if (c.followups_sent > 0) {
    return {
      label: `Chased ${c.followups_sent}×`,
      className: "bg-sky-50 text-sky-700 ring-sky-200",
    };
  }
  if (c.awaiting_reply) {
    return { label: "Awaiting reply", className: "bg-sky-50 text-sky-700 ring-sky-200" };
  }
  return { label: "Assistant replying", className: "bg-brand-500/10 text-brand-600 ring-brand-500/20" };
}

function CandidateCard({ candidate }: { candidate: Candidate }) {
  const status = statusFor(candidate);
  return (
    <Link
      to={`/candidates/${candidate.id}`}
      className="group flex flex-col rounded-2xl border border-gray-200 bg-surface p-4
                 shadow-xs transition-all hover:-translate-y-0.5 hover:border-brand-500/40
                 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
    >
      <div className="flex items-start gap-3">
        <Avatar name={candidate.display_name} phone={candidate.phone_number} size={48} emoji />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14.5px] font-semibold text-gray-900">
            {candidate.display_name || candidate.phone_number}
          </p>
          {/* The number stays visible even once a name is known: it is the
              identity the operator cross-references against their phone. */}
          {candidate.display_name && (
            <p className="truncate text-[11.5px] tabular-nums text-gray-500">
              {candidate.phone_number}
            </p>
          )}
          <p className="mt-0.5 truncate text-[10.5px] text-gray-400">{candidate.channel_label}</p>
        </div>
        <span className="flex-shrink-0 text-[10.5px] tabular-nums text-gray-400">
          {timeLabel(candidate.last_message_at)}
        </span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.4em] text-[12.5px] leading-snug text-gray-500">
        {candidate.last_message_preview || "No messages yet."}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-gray-100 pt-3">
        <span
          className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ring-1 ring-inset ${status.className}`}
        >
          {status.label}
        </span>
        <span className="ml-auto flex items-center gap-2.5 text-[11px] tabular-nums text-gray-400">
          <span className="inline-flex items-center gap-1" title="Messages">
            <MessageSquare className="w-3.5 h-3.5" strokeWidth={2} />
            {candidate.message_count}
          </span>
          {candidate.document_count > 0 && (
            <span
              className="inline-flex items-center gap-1 font-semibold text-brand-600"
              title="Documents shared"
            >
              <Paperclip className="w-3.5 h-3.5" strokeWidth={2} />
              {candidate.document_count}
            </span>
          )}
        </span>
      </div>
    </Link>
  );
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await listCandidates({
        search: search.trim(),
        ...filterParams(filter),
        pageSize: 60,
      });
      setCandidates(page.candidates);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load candidates.");
    } finally {
      setLoading(false);
    }
  }, [search, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="page">
      <header className="mb-6">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-brand-500/10 text-brand-600">
            <Users className="w-5 h-5" strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h1 className="page-title">Candidates</h1>
            <p className="page-subtitle">
              {total} conversation{total === 1 ? "" : "s"} across every WhatsApp number
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[240px] flex-1 sm:max-w-sm">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              strokeWidth={1.75}
            />
            <input
              className="input h-9 rounded-full pl-9 text-[13px]"
              placeholder="Search name, number or message…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {FILTERS.map((chip) => (
            <button
              key={chip.key}
              type="button"
              aria-pressed={filter === chip.key}
              onClick={() => setFilter(chip.key)}
              className={`rounded-full px-3 py-1.5 text-[11.5px] font-semibold transition-colors ${
                filter === chip.key
                  ? "bg-brand-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900"
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="skeleton h-44 rounded-2xl" />
          ))}
        </div>
      ) : candidates.length === 0 ? (
        <div className="empty-state">
          <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-500/10 text-brand-600">
            <FileText className="h-8 w-8" strokeWidth={1.5} />
          </span>
          <p className="empty-state-title">
            {search || filter !== "all" ? "No candidates match this filter" : "No conversations yet"}
          </p>
          <p className="empty-state-desc">
            {search || filter !== "all"
              ? "Try a different search, or clear the filter."
              : "Once someone messages any of your WhatsApp numbers, they'll appear here as a profile."}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {candidates.map((c) => (
            <CandidateCard key={c.id} candidate={c} />
          ))}
        </div>
      )}
    </div>
  );
}
