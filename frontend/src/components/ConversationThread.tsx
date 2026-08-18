// Shared read-side rendering for a WhatsApp message thread: message bubbles,
// day separators, inline attachments, and the small helpers around them.
//
// Used by both the live two-way inbox (WhatsAppInboxPage, one number at a
// time, with a composer and polling) and the read-oriented Candidates
// profile view (every number, no composer). The two pages differ in what
// surrounds the thread, not in how a thread itself renders — that part lived
// duplicated in WhatsAppInboxPage until the Candidates page needed the same
// rendering for a conversation it never fetches through the per-number inbox
// endpoints.
import { RefObject, useEffect, useMemo, useState } from "react";
import {
  Bot, Check, CheckCheck, FileText, Image as ImageIcon, Mic, Paperclip, Sparkles, Video,
} from "lucide-react";

import { InboxMessage, MessageAuthor, fetchMediaObjectUrl } from "../api/whatsappInbox";

export function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso);
  const sameDay = new Date().toDateString() === then.toDateString();
  return sameDay
    ? then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : then.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function clockLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** "Today" / "Yesterday" / a date — the separator between days in a thread. */
export function dayLabel(iso: string): string {
  const then = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (then.toDateString() === today.toDateString()) return "Today";
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  return then.toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
}

export function sizeLabel(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const KIND_ICON = {
  image: ImageIcon,
  video: Video,
  audio: Mic,
  document: FileText,
  sticker: Sparkles,
} as const;

export function MediaIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = KIND_ICON[kind as keyof typeof KIND_ICON] || Paperclip;
  return <Icon className={className} strokeWidth={1.75} />;
}

/** Deterministic avatar tint, so the same contact is the same colour every
 * time the list loads. Nine hues, keyed off the number rather than the name —
 * a contact can be renamed, their number cannot. */
const AVATAR_TINTS = [
  "from-violet-500 to-purple-600",
  "from-sky-500 to-blue-600",
  "from-emerald-500 to-teal-600",
  "from-amber-500 to-orange-600",
  "from-rose-500 to-pink-600",
  "from-indigo-500 to-violet-600",
  "from-cyan-500 to-sky-600",
  "from-fuchsia-500 to-purple-600",
  "from-lime-500 to-emerald-600",
];

function tintFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return AVATAR_TINTS[Math.abs(hash) % AVATAR_TINTS.length];
}

function initialsFor(name: string, phone: string): string {
  const source = name.trim() || phone.replace(/[^0-9]/g, "");
  if (!source) return "?";
  const words = source.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export function Avatar({
  name,
  phone,
  size = 44,
}: {
  name: string;
  phone: string;
  size?: number;
}) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.34 }}
      className={`flex-shrink-0 inline-flex items-center justify-center rounded-full
                  bg-gradient-to-br ${tintFor(phone)} font-semibold text-white
                  tracking-tight select-none`}
    >
      {initialsFor(name, phone)}
    </span>
  );
}

/** Renders an attachment. Images are fetched as object URLs because the media
 * endpoint needs an Authorization header that `<img src>` cannot send. */
export function Attachment({
  conversationId,
  message,
  outgoing,
}: {
  conversationId: string;
  message: InboxMessage;
  outgoing: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const isImage = message.media_kind === "image" || message.media_kind === "sticker";
  // On the green outgoing bubble a neutral tint disappears; on the light
  // incoming one a white one does.
  const chip = outgoing ? "bg-black/15 hover:bg-black/25" : "bg-gray-900/[0.06] hover:bg-gray-900/[0.12]";

  useEffect(() => {
    if (!isImage || !message.media_available) return;
    let revoked: string | null = null;
    let active = true;
    fetchMediaObjectUrl(conversationId, message.id)
      .then((objectUrl) => {
        if (!active) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        revoked = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => setFailed(true));
    return () => {
      active = false;
      // Without this every image scrolled past stays in memory for the tab's life.
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [conversationId, message.id, message.media_available, isImage]);

  if (!message.media_available) {
    return (
      <div className={`flex items-center gap-2 rounded-xl ${chip} px-3 py-2 text-[11px] italic opacity-80`}>
        <MediaIcon kind={message.media_kind} className="w-3.5 h-3.5" />
        {message.media_kind || "attachment"} — not stored
      </div>
    );
  }

  if (isImage) {
    if (failed) return <div className="text-[11px] italic opacity-80">Image unavailable</div>;
    if (!url) return <div className="skeleton h-44 w-60 rounded-xl" />;
    return (
      <a href={url} target="_blank" rel="noreferrer" className="block">
        <img
          src={url}
          alt={message.media_filename || "Attachment"}
          className="max-h-72 rounded-xl object-cover"
        />
      </a>
    );
  }

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          const objectUrl = await fetchMediaObjectUrl(conversationId, message.id);
          const a = document.createElement("a");
          a.href = objectUrl;
          a.download = message.media_filename || `${message.media_kind}-${message.id}`;
          a.click();
          URL.revokeObjectURL(objectUrl);
        } catch {
          setFailed(true);
        }
      }}
      className={`flex w-full items-center gap-2.5 rounded-xl ${chip} px-3 py-2.5 text-left
                  text-[12px] transition-colors`}
    >
      <MediaIcon kind={message.media_kind} className="w-4 h-4 flex-shrink-0" />
      <span className="truncate max-w-[14rem] font-medium">
        {message.media_filename || message.media_kind}
      </span>
      <span className="opacity-70 tabular-nums ml-auto">{sizeLabel(message.media_size_bytes)}</span>
      {failed && <span className="text-red-200">failed</span>}
    </button>
  );
}

/** The small tag on an outgoing bubble saying who wrote it. Only shown for the
 * assistant: a reader looking at their own thread knows which ones they
 * typed, but "did the agent actually answer?" is the question this exists to
 * settle. */
function AuthorTag({ author }: { author: MessageAuthor }) {
  if (author !== "assistant") return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-black/15 px-1.5 py-0.5
                     text-[9.5px] font-semibold uppercase tracking-wide">
      <Bot className="w-2.5 h-2.5" strokeWidth={2.5} />
      AI
    </span>
  );
}

/** The scrollable message ground: day separators over a dot-textured
 * background, each turn as a bubble with its attachment (if any) inline. */
export function ConversationThread({
  conversationId,
  messages,
  scrollRef,
  emptyLabel = "No messages yet.",
}: {
  conversationId: string;
  messages: InboxMessage[];
  scrollRef?: RefObject<HTMLDivElement>;
  emptyLabel?: string;
}) {
  // Day separators are decided once per render rather than inside the map, so
  // the comparison is always against the previous *rendered* message.
  const withDays = useMemo(
    () =>
      messages.map((msg, i) => ({
        msg,
        day:
          i === 0 ||
          new Date(msg.created_at).toDateString() !==
            new Date(messages[i - 1].created_at).toDateString()
            ? dayLabel(msg.created_at)
            : null,
      })),
    [messages],
  );

  return (
    <div
      ref={scrollRef}
      className="min-h-0 flex-1 overflow-y-auto bg-dot-grid bg-dot-md px-5 py-5"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
        {messages.length === 0 && (
          <p className="py-10 text-center text-sm text-gray-500">{emptyLabel}</p>
        )}
        {withDays.map(({ msg, day }) => {
          const outgoing = msg.direction === "out";
          return (
            <div key={msg.id}>
              {day && (
                <div className="my-4 flex justify-center">
                  <span className="rounded-full bg-surface px-3 py-1 text-[11px] font-semibold text-gray-500 shadow-xs">
                    {day}
                  </span>
                </div>
              )}
              <div className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
                <div
                  className={`relative max-w-[78%] px-3 py-2 text-[14px] leading-snug shadow-xs sm:max-w-[68%] ${
                    outgoing
                      ? "rounded-2xl rounded-br-md bg-emerald-600 text-white"
                      : "rounded-2xl rounded-bl-md bg-surface text-gray-900"
                  }`}
                >
                  {msg.media_kind && (
                    <div className="mb-1.5">
                      <Attachment
                        conversationId={conversationId}
                        message={msg}
                        outgoing={outgoing}
                      />
                    </div>
                  )}
                  {msg.content && (
                    <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                  )}
                  <span
                    className={`mt-1 flex items-center justify-end gap-1.5 text-[10px] tabular-nums ${
                      outgoing ? "text-white/70" : "text-gray-400"
                    }`}
                  >
                    <AuthorTag author={msg.author} />
                    {clockLabel(msg.created_at)}
                    {outgoing &&
                      (msg.author === "assistant" ? (
                        <CheckCheck className="w-3.5 h-3.5" strokeWidth={2.5} />
                      ) : (
                        <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
                      ))}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
