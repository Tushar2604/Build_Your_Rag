// One candidate's profile: who they are, what they sent, and the whole
// conversation.
//
// Its own route rather than a pane inside the grid, so a profile can be
// refreshed, bookmarked and shared — the thing an HR user actually does with
// "the candidate who sent their marksheet last Tuesday".
//
// Read-oriented on purpose. Replying lives in the per-number inbox, which
// already owns polling, takeover and the composer; this page links there
// instead of growing a second copy of it.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Download, ExternalLink, Link2, MessageCircle, MessageSquare, Paperclip,
  Phone,
} from "lucide-react";

import { Candidate, getCandidate } from "../api/candidates";
import { ApiError } from "../api/client";
import SendToCrmButton, { useCrmDestination } from "../components/SendToCrmButton";
import { InboxMessage, fetchMediaObjectUrl, listMessages } from "../api/whatsappInbox";
import {
  Avatar, ConversationThread, MediaIcon, sizeLabel,
} from "../components/ConversationThread";

/** Bare-eyed URL match. Deliberately loose about what it accepts and strict
 * about what it trims: trailing punctuation is almost always sentence
 * grammar rather than part of the address. */
const URL_RE = /\bhttps?:\/\/[^\s<>"']+/gi;

interface SharedLink {
  url: string;
  at: string;
  outgoing: boolean;
}

function extractLinks(messages: InboxMessage[]): SharedLink[] {
  const seen = new Set<string>();
  const links: SharedLink[] = [];
  for (const msg of messages) {
    for (const raw of msg.content?.match(URL_RE) || []) {
      const url = raw.replace(/[.,;:!?)\]}>]+$/, "");
      if (seen.has(url)) continue;
      seen.add(url);
      links.push({ url, at: msg.created_at, outgoing: msg.direction === "out" });
    }
  }
  return links;
}

/** Strips a URL down to something readable in a narrow card. */
function prettyUrl(url: string): string {
  try {
    const u = new URL(url);
    const tail = `${u.pathname}${u.search}`.replace(/\/$/, "");
    return u.hostname.replace(/^www\./, "") + (tail.length > 1 ? tail : "");
  } catch {
    return url;
  }
}

function DocumentCard({ candidateId, message }: { candidateId: string; message: InboxMessage }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function download() {
    if (!message.media_available || busy) return;
    setBusy(true);
    try {
      const objectUrl = await fetchMediaObjectUrl(candidateId, message.id);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = message.media_filename || `${message.media_kind}-${message.id}`;
      a.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={download}
      disabled={!message.media_available || busy}
      className="flex items-center gap-3 rounded-xl border border-gray-200 bg-surface px-3 py-2.5
                 text-left shadow-xs transition-colors hover:bg-gray-50
                 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
        <MediaIcon kind={message.media_kind} className="w-[18px] h-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-medium text-gray-900">
          {message.media_filename || message.media_kind || "Attachment"}
        </span>
        <span className="block text-[11px] text-gray-500">
          {failed
            ? "Download failed"
            : message.media_available
              ? sizeLabel(message.media_size_bytes) || message.media_kind
              : "Not stored"}
        </span>
      </span>
      {message.media_available && (
        <Download className="w-4 h-4 flex-shrink-0 text-gray-400" strokeWidth={2} />
      )}
    </button>
  );
}

function Stat({ icon: Icon, value, label }: { icon: typeof MessageSquare; value: number; label: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-gray-200 bg-surface px-3.5 py-2.5">
      <Icon className="w-4 h-4 flex-shrink-0 text-gray-400" strokeWidth={2} />
      <div className="min-w-0">
        <p className="text-[15px] font-semibold tabular-nums leading-none text-gray-900">{value}</p>
        <p className="mt-1 truncate text-[10.5px] text-gray-500">{label}</p>
      </div>
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-5">
      <h2 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        {title}
        {count !== undefined && <span className="ml-1.5 text-gray-400">({count})</span>}
      </h2>
      {children}
    </section>
  );
}

export default function CandidateProfilePage() {
  const { candidateId = "" } = useParams();
  const navigate = useNavigate();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const crm = useCrmDestination();

  useEffect(() => {
    if (!candidateId) return;
    setLoading(true);
    // The profile and its thread are independent reads; failing either one
    // should say so rather than leaving a half-rendered page.
    Promise.all([getCandidate(candidateId), listMessages(candidateId, 500)])
      .then(([profile, thread]) => {
        setCandidate(profile);
        setMessages(thread);
        setError(null);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Could not load this candidate."),
      )
      .finally(() => setLoading(false));
  }, [candidateId]);

  const documents = useMemo(() => messages.filter((m) => m.media_kind), [messages]);
  const links = useMemo(() => extractLinks(messages), [messages]);

  if (loading) {
    return (
      <div className="page">
        <div className="skeleton h-28 rounded-2xl" />
        <div className="skeleton mt-4 h-20 rounded-2xl" />
        <div className="skeleton mt-4 h-96 rounded-2xl" />
      </div>
    );
  }

  if (error || !candidate) {
    return (
      <div className="page">
        <Link to="/candidates" className="btn-sm btn-secondary">
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2} />
          All candidates
        </Link>
        <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error || "This candidate could not be found."}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <Link
        to="/candidates"
        className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-gray-500 hover:text-gray-900"
      >
        <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2} />
        All candidates
      </Link>

      {/* --- Identity --- */}
      <header className="mt-3 flex flex-wrap items-start gap-4 rounded-2xl border border-gray-200 bg-surface p-5 shadow-xs">
        <Avatar name={candidate.display_name} phone={candidate.phone_number} size={64} emoji />
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-[20px] font-semibold text-gray-900">
            {candidate.display_name || candidate.phone_number}
          </h1>
          <p className="mt-0.5 truncate text-[13px] tabular-nums text-gray-600">
            {candidate.phone_number}
          </p>
          {/* Which WhatsApp number this conversation is on — and, when the
              same person has also written to another of them, the switch
              between the two. They are one candidate with two conversations;
              merging them would splice together threads the contact kept
              separate, and hiding one would lose it. */}
          {candidate.threads.length > 1 ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Phone className="h-3.5 w-3.5 flex-shrink-0 text-gray-400" strokeWidth={2} />
              {candidate.threads.map((t) => {
                const active = t.conversation_id === candidate.id;
                return (
                  <button
                    key={t.conversation_id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => navigate(`/candidates/${t.conversation_id}`)}
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1
                                text-[11px] font-semibold transition-colors ${
                                  active
                                    ? "bg-gray-900 text-white"
                                    : "bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900"
                                }`}
                  >
                    {t.channel_label}
                    <span className="tabular-nums opacity-60">{t.message_count}</span>
                    {t.unread_count > 0 && (
                      <span className="rounded-full bg-emerald-500 px-1.5 text-[10px] font-bold text-white">
                        {t.unread_count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="mt-0.5 truncate text-[11.5px] text-gray-400">
              {candidate.channel_label}
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
                candidate.auto_reply
                  ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                  : "bg-amber-50 text-amber-700 ring-amber-200"
              }`}
            >
              {candidate.auto_reply ? "Assistant replying" : "Handled by you"}
            </span>
            {candidate.followups_sent > 0 && (
              <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-[11px] font-semibold text-sky-700 ring-1 ring-inset ring-sky-200">
                {candidate.followups_sent > 2
                  ? "Followed up — no response"
                  : `Followed up ${candidate.followups_sent}×`}
              </span>
            )}
            {candidate.unread_count > 0 && (
              <span className="rounded-full bg-emerald-500 px-2.5 py-0.5 text-[11px] font-semibold text-white">
                {candidate.unread_count} unread
              </span>
            )}
          </div>
        </div>
        {/* The two things you do *with* a candidate once you have read them:
            keep talking, or hand them to the system that tracks the hire. */}
        <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
          <SendToCrmButton
            candidateId={candidate.id}
            candidateName={candidate.display_name || candidate.phone_number}
            destination={crm}
          />
          {candidate.channel_kind === "personal" && candidate.session_id && (
            <Link
              to={`/channels/whatsapp/${candidate.session_id}/inbox`}
              className="btn-sm btn-secondary"
            >
              <MessageCircle className="w-3.5 h-3.5" strokeWidth={2} />
              Reply in inbox
            </Link>
          )}
        </div>
      </header>

      {/* --- At a glance --- */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat icon={MessageSquare} value={messages.length} label="Messages" />
        <Stat icon={Paperclip} value={documents.length} label="Documents" />
        <Stat icon={Link2} value={links.length} label="Links shared" />
      </div>

      {documents.length > 0 && (
        <Section title="Documents" count={documents.length}>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {documents.map((m) => (
              <DocumentCard key={m.id} candidateId={candidate.id} message={m} />
            ))}
          </div>
        </Section>
      )}

      {links.length > 0 && (
        <Section title="Links shared" count={links.length}>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {links.map((link) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-3 rounded-xl border border-gray-200 bg-surface px-3 py-2.5
                           shadow-xs transition-colors hover:bg-gray-50"
              >
                <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                  <Link2 className="w-[18px] h-[18px]" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] font-medium text-gray-900">
                    {prettyUrl(link.url)}
                  </span>
                  <span className="block text-[11px] text-gray-500">
                    {link.outgoing ? "Sent to them" : "They sent this"}
                  </span>
                </span>
                <ExternalLink className="w-4 h-4 flex-shrink-0 text-gray-400" strokeWidth={2} />
              </a>
            ))}
          </div>
        </Section>
      )}

      <Section title="Conversation">
        <div className="flex h-[560px] flex-col overflow-hidden rounded-2xl border border-gray-200">
          <ConversationThread
            conversationId={candidate.id}
            messages={messages}
            emptyLabel="No messages in this conversation yet."
          />
        </div>
      </Section>
    </div>
  );
}
