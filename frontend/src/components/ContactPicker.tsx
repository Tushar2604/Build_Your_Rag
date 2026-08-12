// Choosing who a campaign goes to.
//
// Typing numbers by hand is the worst of the three ways to build a list and was
// the only one available. This offers all three — paste, upload a file, or pick
// from the contacts already synced off a linked WhatsApp — and, crucially,
// validates before anything is created. The old flow only reported what failed
// to parse *after* the campaign existed, which meant fixing a malformed export
// by editing recipients on a campaign you had already committed to.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { ContactPreview, previewContacts } from "../api/broadcasts";
import { InboxConversation, listConversations } from "../api/whatsappInbox";
import { WhatsAppWebSession, listWebSessions } from "../api/whatsappWeb";

type Source = "paste" | "upload" | "whatsapp";

const TABS: { key: Source; label: string }[] = [
  { key: "paste", label: "Paste" },
  { key: "upload", label: "Upload file" },
  { key: "whatsapp", label: "From WhatsApp" },
];

/** Accepted for upload. Anything text-shaped is read as CSV by the server
 * parser, which already handles one-per-line, `number, name`, and headers. */
const ACCEPT = ".csv,.txt,.tsv,text/csv,text/plain";
const MAX_FILE_MB = 5;

function toLine(phone: string, name: string): string {
  return name ? `${phone}, ${name}` : phone;
}

export default function ContactPicker({
  value,
  onChange,
  /** Preselects this linked number's contacts in the WhatsApp tab. */
  sessionId,
}: {
  value: string;
  onChange: (next: string) => void;
  sessionId?: string;
}) {
  const [source, setSource] = useState<Source>("paste");
  const [preview, setPreview] = useState<ContactPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // WhatsApp tab
  const [sessions, setSessions] = useState<WhatsAppWebSession[]>([]);
  const [activeSession, setActiveSession] = useState(sessionId ?? "");
  const [contacts, setContacts] = useState<InboxConversation[]>([]);
  const [contactSearch, setContactSearch] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [loadingContacts, setLoadingContacts] = useState(false);

  // Validate as you type, but not on every keystroke — this is a network call
  // and a 5,000-line paste should be parsed once, not per character.
  useEffect(() => {
    if (!value.trim()) {
      setPreview(null);
      return;
    }
    setChecking(true);
    const timer = setTimeout(() => {
      previewContacts(value)
        .then((result) => {
          setPreview(result);
          setError(null);
        })
        .catch((e) => setError(e instanceof ApiError ? e.message : "Could not check the list."))
        .finally(() => setChecking(false));
    }, 400);
    return () => clearTimeout(timer);
  }, [value]);

  useEffect(() => {
    if (source !== "whatsapp" || sessions.length) return;
    listWebSessions()
      .then((all) => {
        const linked = all.filter((s) => s.status === "linked");
        setSessions(linked);
        if (!activeSession && linked[0]) setActiveSession(linked[0].id);
      })
      .catch(() => setSessions([]));
  }, [source, sessions.length, activeSession]);

  const loadContacts = useCallback(async () => {
    if (!activeSession) return;
    setLoadingContacts(true);
    try {
      const page = await listConversations(activeSession, {
        search: contactSearch.trim(),
        pageSize: 100,
      });
      setContacts(page.conversations);
    } catch {
      setContacts([]);
    } finally {
      setLoadingContacts(false);
    }
  }, [activeSession, contactSearch]);

  useEffect(() => {
    if (source === "whatsapp") void loadContacts();
  }, [source, loadContacts]);

  function readFile(file: File) {
    setError(null);
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      setError(`That file is over ${MAX_FILE_MB}MB. Split it, or paste the numbers instead.`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "");
      // Appended, not replaced, so uploading a second file adds to the list
      // rather than silently discarding the first.
      onChange(value.trim() ? `${value.trim()}\n${text}` : text);
    };
    reader.onerror = () => setError("Could not read that file.");
    reader.readAsText(file);
  }

  function addPicked() {
    const lines = contacts
      .filter((c) => picked.has(c.id))
      .map((c) => toLine(c.phone_number, c.display_name))
      .join("\n");
    if (!lines) return;
    onChange(value.trim() ? `${value.trim()}\n${lines}` : lines);
    setPicked(new Set());
  }

  const hasProblems = Boolean(preview && (preview.invalid.length || preview.duplicates.length));

  return (
    <div className="space-y-3">
      <div className="tab-bar">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setSource(tab.key)}
            className={source === tab.key ? "tab-item tab-item-active" : "tab-item"}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {source === "paste" && (
        <textarea
          className="input font-mono text-[13px] min-h-[9rem]"
          placeholder={"+919876543210, Asha Menon\n+14155550123, Sam Rivera"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {source === "upload" && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const file = e.dataTransfer.files?.[0];
            if (file) readFile(file);
          }}
          className={`rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${
            dragging ? "border-brand-500 bg-brand-50" : "border-gray-200"
          }`}
        >
          <p className="text-sm text-gray-700">Drop a CSV here, or</p>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="btn-secondary text-sm mt-2"
          >
            Choose a file
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) readFile(file);
              e.target.value = "";
            }}
          />
          <p className="text-xs text-gray-500 mt-3">
            A header row is detected automatically. Columns can be in any order — the number is
            found by shape, not by position.
          </p>
        </div>
      )}

      {source === "whatsapp" && (
        <div className="rounded-xl border border-gray-200 p-3">
          {sessions.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">
              No linked WhatsApp number yet. Link one under Channels to pick contacts from it.
            </p>
          ) : (
            <>
              <div className="flex gap-2 mb-2">
                {sessions.length > 1 && (
                  <select
                    className="input h-8 text-sm w-44"
                    value={activeSession}
                    onChange={(e) => setActiveSession(e.target.value)}
                  >
                    {sessions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.phone_number || "Linked number"}
                      </option>
                    ))}
                  </select>
                )}
                <input
                  className="input h-8 text-sm flex-1"
                  placeholder="Search name or number…"
                  value={contactSearch}
                  onChange={(e) => setContactSearch(e.target.value)}
                />
              </div>

              <ul className="max-h-52 overflow-y-auto divide-y divide-gray-100">
                {loadingContacts && <li className="skeleton h-8 my-2 rounded" />}
                {!loadingContacts && contacts.length === 0 && (
                  <li className="text-sm text-gray-400 py-6 text-center">
                    No contacts found. They appear here once a WhatsApp number is linked and its
                    contacts have synced.
                  </li>
                )}
                {contacts.map((c) => (
                  <li key={c.id} className="flex items-center gap-2 py-1.5">
                    <input
                      type="checkbox"
                      checked={picked.has(c.id)}
                      onChange={() =>
                        setPicked((prev) => {
                          const next = new Set(prev);
                          if (next.has(c.id)) next.delete(c.id);
                          else next.add(c.id);
                          return next;
                        })
                      }
                    />
                    <span className="text-sm text-gray-900 truncate flex-1">
                      {c.display_name || c.phone_number}
                    </span>
                    <span className="text-xs text-gray-400 tabular-nums">{c.phone_number}</span>
                  </li>
                ))}
              </ul>

              <div className="flex items-center justify-between mt-2">
                <span className="text-xs text-gray-500">{picked.size} selected</span>
                <button
                  type="button"
                  onClick={addPicked}
                  disabled={picked.size === 0}
                  className="btn-secondary text-xs disabled:opacity-40"
                >
                  Add to list
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* --- Validation summary, shared by every source --- */}
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {value.trim() && (
        <div className="rounded-lg border border-gray-200 bg-surface-2 px-3 py-2.5">
          <div className="flex items-center gap-3 text-xs">
            <span className="font-semibold text-emerald-700 tabular-nums">
              {checking ? "Checking…" : `${preview?.total_valid ?? 0} ready to send`}
            </span>
            {!!preview?.duplicates.length && (
              <span className="text-amber-700 tabular-nums">
                {preview.duplicates.length} duplicate
                {preview.duplicates.length === 1 ? "" : "s"} skipped
              </span>
            )}
            {!!preview?.invalid.length && (
              <span className="text-red-700 tabular-nums">
                {preview.invalid.length} unreadable
              </span>
            )}
            <button
              type="button"
              onClick={() => onChange("")}
              className="ml-auto text-gray-400 hover:text-gray-700"
            >
              Clear
            </button>
          </div>

          {hasProblems && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-gray-500">
                Show the rows that need attention
              </summary>
              <div className="mt-1.5 space-y-1">
                {preview?.invalid.map((line, i) => (
                  <p key={`i${i}`} className="font-mono text-[11px] text-red-700 truncate">
                    ✕ {line}
                  </p>
                ))}
                {preview?.duplicates.map((phone, i) => (
                  <p key={`d${i}`} className="font-mono text-[11px] text-amber-700">
                    ⟳ {phone} — listed more than once, sent once
                  </p>
                ))}
              </div>
              <p className="text-[11px] text-gray-500 mt-2">
                Unreadable rows are usually missing a country code. They are skipped rather than
                guessed at, because a wrong guess messages a stranger.
              </p>
            </details>
          )}

          {preview?.truncated && (
            <p className="text-[11px] text-gray-500 mt-1">
              Showing the first 500; all {preview.total_valid} will be added.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
