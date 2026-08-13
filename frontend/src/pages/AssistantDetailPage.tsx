import { useState, useEffect, useCallback } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowDown, ArrowLeft, ArrowUp, Bot, BookOpen, ChevronDown, ClipboardCheck,
  Headphones, History, Loader2, MessageSquare, Phone, Rocket, Sparkles,
  SlidersHorizontal, X, Zap,
} from "lucide-react";
import {
  getChatbot, updateChatbot, rotateChatbotKey, regenerateFlow,
  Chatbot, Channel,
} from "../api/chatbots";
import { getChatbotAnalytics, getChatbotRequests, ChatbotAnalytics, RequestLog } from "../api/analytics";
import { ApiError } from "../api/client";
import PostCallSettings from "../components/PostCallSettings";
import AssistantDetailsTab, { Draft } from "../components/assistant/AssistantDetailsTab";
import KnowledgeBaseTab from "../components/assistant/KnowledgeBaseTab";
import AssistantIntegrationsTab from "../components/assistant/AssistantIntegrationsTab";
import TestModePanel, { TestMode } from "../components/assistant/TestModePanel";
import { VoiceProfile, listVoices } from "../api/voices";

/* ── shared types ── */
type Tab =
  | "details"
  | "config"
  | "knowledge"
  | "integrations"
  | "post-call"
  | "recent-calls";

/* ── helpers ── */
function CopyButton({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap"
    >
      {copied ? "Copied!" : label ?? "Copy"}
    </button>
  );
}

function SectionCard({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="card p-5">
      {title && <h3 className="section-title mb-4">{title}</h3>}
      {children}
    </div>
  );
}

/* ════════════════════════════════════════════
   TAB: CONFIGURATION
════════════════════════════════════════════ */
/** Call-time settings. Name, welcome message, and the Conversational Flow are
 * deliberately absent — they belong to the page header and the Assistant
 * Details tab, and duplicating them here would give each two owners. */
function ConfigTab({ bot, onUpdate }: { bot: Chatbot; onUpdate: (b: Chatbot) => void }) {
  const [channel,       setChannel]       = useState<Channel>(bot.channel);
  const [voiceId,       setVoiceId]       = useState<string | null>(bot.voice_profile_id);
  const [voices,        setVoices]        = useState<VoiceProfile[]>([]);
  const [topK,          setTopK]          = useState(bot.top_k);
  const [isPublic,      setIsPublic]      = useState(bot.is_public);
  const [originsText,   setOriginsText]   = useState(bot.allowed_origins.join("\n"));
  const [displayName,   setDisplayName]   = useState(bot.widget.display_name);
  const [themeColor,    setThemeColor]    = useState(bot.widget.theme_color);
  const [welcome,       setWelcome]       = useState(bot.widget.welcome_message);
  const [position,      setPosition]      = useState(bot.widget.launcher_position);
  const [saving,        setSaving]        = useState(false);
  const [saved,         setSaved]         = useState(false);
  const [error,         setError]         = useState<string | null>(null);
  const [dirty,         setDirty]         = useState(false);

  function mark() { setDirty(true); setSaved(false); }

  // Only `ready` voices can be assigned — the API rejects the rest, so
  // offering them would just produce a confusing save error.
  useEffect(() => {
    listVoices()
      .then((all) => setVoices(all.filter((v) => v.status === "ready")))
      .catch(() => setVoices([]));
  }, []);

  async function save() {
    setSaving(true); setError(null); setSaved(false);
    try {
      const origins = originsText.split("\n").map((o) => o.trim()).filter(Boolean);
      const updated = await updateChatbot(bot.id, {
        channel, top_k: topK, is_public: isPublic,
        allowed_origins: origins,
        voice_profile_id: voiceId,
        voice_profile_id_set: true,
        widget: { display_name: displayName, theme_color: themeColor, welcome_message: welcome, launcher_position: position },
      });
      onUpdate(updated);
      setVoiceId(updated.voice_profile_id);
      setSaved(true); setDirty(false);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save.");
    } finally { setSaving(false); }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Channel */}
      <SectionCard title="Channel">
        <div className="segmented">
          {(["text", "voice"] as const).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => { setChannel(c); mark(); }}
              className={channel === c ? "segmented-item-active" : "segmented-item"}
            >
              {c === "text" ? "💬 Text" : "🎙️ Voice"}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          {channel === "text"
            ? "A standard text chat. Available in the Playground, share link, and embeds."
            : "A phone-call-style experience — continuous listen, auto-reply, auto-speak. Replaces the chat window everywhere this assistant is used."}
        </p>

        {channel === "voice" && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <label className="label">Voice</label>
            <select
              className="input"
              value={voiceId ?? ""}
              onChange={(e) => { setVoiceId(e.target.value || null); mark(); }}
            >
              <option value="">Browser default voice</option>
              {voices.map((v) => (
                <option key={v.id} value={v.id}>{v.name} ({v.language})</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              {voices.length === 0 ? (
                <>No cloned voices yet — <Link to="/clone-voice" className="text-brand-600 hover:underline">create one</Link>.</>
              ) : (
                <>Only voices that finished cloning are listed. <Link to="/clone-voice" className="text-brand-600 hover:underline">Manage voices</Link>.</>
              )}
            </p>
          </div>
        )}
      </SectionCard>

      {/* Retrieval */}
      <SectionCard title="Retrieval settings">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Top-K chunks</label>
            <input
              type="number"
              className="input"
              min={1} max={20}
              value={topK}
              onChange={(e) => { setTopK(Number(e.target.value)); mark(); }}
            />
            <p className="text-xs text-gray-400 mt-1">Chunks retrieved per query. Higher = more context, more cost.</p>
          </div>
        </div>
      </SectionCard>

      {/* Deployment */}
      <SectionCard title="Deployment">
        <div className="space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              className="w-4 h-4 mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
              checked={isPublic}
              onChange={(e) => { setIsPublic(e.target.checked); mark(); }}
            />
            <span>
              <span className="text-sm font-medium text-gray-900">Public access</span>
              <p className="text-xs text-gray-500 mt-0.5">Enable web widget embed and shareable link. Required for production deployment.</p>
            </span>
          </label>

          <div>
            <label className="label">Allowed domains</label>
            <textarea
              className="input resize-none font-mono text-xs"
              rows={3}
              placeholder={"https://example.com\nhttps://app.example.com"}
              value={originsText}
              onChange={(e) => { setOriginsText(e.target.value); mark(); }}
            />
            <p className="text-xs text-gray-400 mt-1">One origin per line. Leave empty to allow all domains.</p>
          </div>
        </div>
      </SectionCard>

      {/* Widget appearance */}
      <SectionCard title="Widget appearance">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Display name</label>
            <input className="input" value={displayName} maxLength={60}
              onChange={(e) => { setDisplayName(e.target.value); mark(); }} />
          </div>
          <div>
            <label className="label">Theme color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={themeColor}
                onChange={(e) => { setThemeColor(e.target.value); mark(); }}
                className="h-9 w-10 rounded border border-gray-200 cursor-pointer p-0.5" />
              <input className="input flex-1" value={themeColor}
                onChange={(e) => { setThemeColor(e.target.value); mark(); }} />
            </div>
          </div>
          <div className="col-span-2">
            <label className="label">Welcome message</label>
            <textarea className="input resize-none" rows={2} maxLength={300}
              value={welcome} onChange={(e) => { setWelcome(e.target.value); mark(); }} />
          </div>
          <div>
            <label className="label">Launcher position</label>
            <select className="input" value={position}
              onChange={(e) => { setPosition(e.target.value as typeof position); mark(); }}>
              <option value="bottom-right">Bottom right</option>
              <option value="bottom-left">Bottom left</option>
            </select>
          </div>
        </div>
      </SectionCard>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* Save bar */}
      {dirty && (
        <div className="sticky bottom-4 flex items-center justify-between rounded-xl bg-ink-900 text-white px-5 py-3 shadow-pop">
          <span className="text-sm text-white/70">You have unsaved changes.</span>
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => { setDirty(false); /* TODO: reset */ }} className="text-sm text-white/70 hover:text-white">Discard</button>
            <button type="button" onClick={save} disabled={saving} className="btn-primary py-1.5 text-xs">
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      )}
      {saved && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
          Changes saved successfully.
        </div>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════
   TAB: DEPLOYMENTS
════════════════════════════════════════════ */
type IntegMethod = "widget" | "inline" | "iframe" | "react" | "api";

interface IntegMethodDef {
  id: IntegMethod;
  label: string;
  sub: string;
  badge?: string;
  intro: string;
}

const INTEG_METHODS: IntegMethodDef[] = [
  { id: "widget", label: "Script embed",  sub: "Floating bubble",   badge: "Recommended",
    intro: "Adds a floating chat bubble to any page. Paste before </body> — two minutes to integrate." },
  { id: "inline", label: "Inline embed",  sub: "Inside a container",
    intro: "Renders the chat directly inside a <div> you control. Set a fixed height on the container." },
  { id: "iframe", label: "iFrame",        sub: "CMS / no-code",
    intro: "Works anywhere iFrames are supported: WordPress, Webflow, Notion, Wix, Squarespace." },
  { id: "react",  label: "React",         sub: "Native component",
    intro: "A self-contained component for React or Next.js. Zero external dependencies — uses native fetch." },
  { id: "api",    label: "REST API",      sub: "Build a custom UI",
    intro: "Full control. Build your own interface on top of the streaming API — no widget required." },
];

function DeploymentsTab({ bot, onUpdate }: { bot: Chatbot; onUpdate: (b: Chatbot) => void }) {
  const [method,   setMethod]   = useState<IntegMethod>("widget");
  const [rotating, setRotating] = useState(false);
  const [rotErr,   setRotErr]   = useState<string | null>(null);

  const origin   = window.location.origin;
  const pk       = bot.public_key;
  const theme    = bot.widget.theme_color;
  const embedUrl = `${origin}/embed/${pk}`;

  const widgetSnippet = `<!-- Paste before </body> on any page -->
<script
  src="${origin}/widget.js"
  data-chatbot-key="${pk}"
  async
></script>`;

  const inlineSnippet = `<!-- Container — adjust height to fit your layout -->
<div id="evara-chat" style="height:600px;border-radius:12px;overflow:hidden;"></div>

<!-- Widget script — place after the container -->
<script
  src="${origin}/widget.js"
  data-chatbot-key="${pk}"
  data-mode="inline"
  data-container="#evara-chat"
  async
></script>`;

  const iframeSnippet = `<!-- Works in WordPress, Webflow, Notion, Wix, and any CMS -->
<iframe
  src="${embedUrl}"
  style="width:100%;height:600px;border:none;border-radius:12px;"
  title="${bot.name}"
  allow="clipboard-write"
></iframe>`;

  const reactSnippet = [
    '"use client"; // Remove this line if not using Next.js App Router',
    '',
    'import { useState, useRef, FormEvent } from "react";',
    '',
    `const API = "${origin}/api/v1/public/chatbots/${pk}";`,
    '',
    'interface Msg { role: "user" | "bot"; text: string }',
    '',
    'export function EvaraChat() {',
    '  const [msgs, setMsgs]     = useState<Msg[]>([{ role: "bot", text: "Hi! How can I help?" }]);',
    '  const [input, setInput]   = useState("");',
    '  const [busy, setBusy]     = useState(false);',
    '  const sessionRef           = useRef<string | null>(null);',
    '',
    '  async function send(e: FormEvent) {',
    '    e.preventDefault();',
    '    const text = input.trim();',
    '    if (!text || busy) return;',
    '    setBusy(true); setInput("");',
    '    setMsgs(m => [...m, { role: "user", text }, { role: "bot", text: "" }]);',
    '',
    '    if (!sessionRef.current) {',
    '      const d = await fetch(API + "/sessions", { method: "POST" }).then(r => r.json());',
    '      sessionRef.current = d.session_id;',
    '    }',
    '    const res = await fetch(`${API}/sessions/${sessionRef.current}/stream`, {',
    '      method: "POST", headers: { "Content-Type": "application/json" },',
    '      body: JSON.stringify({ message: text }),',
    '    });',
    '    const reader = res.body!.getReader(); const dec = new TextDecoder();',
    '    let buf = "", evt = "";',
    '    while (true) {',
    '      const { done, value } = await reader.read(); if (done) break;',
    '      buf += dec.decode(value, { stream: true });',
    '      const lines = buf.split("\\n"); buf = lines.pop()!;',
    '      for (const line of lines) {',
    '        if (line.startsWith("event:")) evt = line.slice(6).trim();',
    '        else if (line.startsWith("data:") && evt === "token") {',
    '          const tok = line.slice(5).trim();',
    '          setMsgs(m => { const c=[...m]; c[c.length-1]={...c[c.length-1],text:c[c.length-1].text+tok}; return c; });',
    '        }',
    '      }',
    '    }',
    '    setBusy(false);',
    '  }',
    '',
    '  const userBg = "' + theme + '";',
    '',
    '  return (',
    '    <div style={{ display:"flex", flexDirection:"column", height:"100%", fontFamily:"sans-serif" }}>',
    '      <div style={{ flex:1, overflowY:"auto", padding:16, display:"flex", flexDirection:"column", gap:12 }}>',
    '        {msgs.map((m, i) => (',
    '          <div key={i} style={{',
    '            alignSelf: m.role==="user" ? "flex-end" : "flex-start",',
    '            background: m.role==="user" ? userBg : "#f3f4f6",',
    '            color: m.role==="user" ? "#fff" : "#1f2937",',
    '            padding:"10px 14px", borderRadius:12, maxWidth:"80%", fontSize:14',
    '          }}>',
    '            {m.text || (busy && i===msgs.length-1 ? "…" : "")}',
    '          </div>',
    '        ))}',
    '      </div>',
    '      <form onSubmit={send} style={{ display:"flex", gap:8, padding:12, borderTop:"1px solid #e5e7eb" }}>',
    '        <input value={input} onChange={e=>setInput(e.target.value)}',
    '          placeholder="Type a message…" disabled={busy}',
    '          style={{ flex:1, padding:"8px 12px", border:"1px solid #d1d5db", borderRadius:8, fontSize:14 }} />',
    '        <button type="submit" disabled={busy||!input.trim()}',
    '          style={{ padding:"8px 16px", background:userBg, color:"#fff", border:"none", borderRadius:8, cursor:"pointer" }}>',
    '          Send',
    '        </button>',
    '      </form>',
    '    </div>',
    '  );',
    '}',
  ].join('\n');

  const apiSnippet = [
    '# ── Step 1: Create a session (once per conversation) ─────────────────',
    `curl -s -X POST "${origin}/api/v1/public/chatbots/${pk}/sessions"`,
    '# → { "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" }',
    '',
    '# ── Step 2: Stream a response ─────────────────────────────────────────',
    'SESSION_ID="paste-your-session-id-here"',
    `curl -s -N -X POST \\`,
    `  "${origin}/api/v1/public/chatbots/${pk}/sessions/$SESSION_ID/stream" \\`,
    '  -H "Content-Type: application/json" \\',
    '  -d \'{"message": "What is your return policy?"}\'',
    '',
    '# SSE event types:',
    '#   event: citations  →  data: [{snippet, score, ordinal}]',
    '#   event: token      →  data: <partial text>',
    '#   event: done       →  stream finished',
    '#   event: error      →  data: error message',
    '',
    '# ── Node.js / browser fetch ───────────────────────────────────────────',
    `const API = "${origin}/api/v1/public/chatbots/${pk}";`,
    '',
    '// 1. Create session',
    'const { session_id } = await fetch(API + "/sessions", { method: "POST" }).then(r => r.json());',
    '',
    '// 2. Stream',
    'const res = await fetch(`${API}/sessions/${session_id}/stream`, {',
    '  method: "POST",',
    '  headers: { "Content-Type": "application/json" },',
    '  body: JSON.stringify({ message: "What is your return policy?" }),',
    '});',
    'const reader = res.body.getReader(); const dec = new TextDecoder();',
    'let buf = "", evt = "";',
    'while (true) {',
    '  const { done, value } = await reader.read(); if (done) break;',
    '  buf += dec.decode(value, { stream: true });',
    '  const lines = buf.split("\\n"); buf = lines.pop();',
    '  for (const line of lines) {',
    '    if (line.startsWith("event:")) evt = line.slice(6).trim();',
    '    else if (line.startsWith("data:") && evt === "token")',
    '      process.stdout.write(line.slice(5).trim()); // or update state',
    '  }',
    '}',
  ].join('\n');

  const snippets: Record<IntegMethod, string> = {
    widget: widgetSnippet, inline: inlineSnippet,
    iframe: iframeSnippet, react:  reactSnippet, api: apiSnippet,
  };

  async function rotateKey() {
    if (!window.confirm("Rotate key? All deployed embeds with the old key will stop working immediately.")) return;
    setRotating(true); setRotErr(null);
    try {
      const updated = await rotateChatbotKey(bot.id);
      onUpdate(updated);
    } catch (e) {
      setRotErr(e instanceof ApiError ? e.message : "Failed to rotate key.");
    } finally { setRotating(false); }
  }

  const active = INTEG_METHODS.find((m) => m.id === method)!;

  return (
    <div className="space-y-5 max-w-3xl">

      {/* ── Go-live checklist ── */}
      <SectionCard title="Go-live checklist">
        <div className="divide-y divide-gray-50">
          <div className="flex items-start gap-3 py-2 first:pt-0">
            <span className={`text-base font-bold flex-shrink-0 mt-px ${bot.is_public ? "text-emerald-500" : "text-red-500"}`}>
              {bot.is_public ? "✓" : "✗"}
            </span>
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-800">Public access</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {bot.is_public
                  ? "Enabled — the widget, iFrame, and public link are all live."
                  : "Disabled — enable in the Configuration tab to make this assistant accessible."}
              </p>
            </div>
            {!bot.is_public && <Link to="?tab=config" className="btn-secondary text-xs px-3 py-1.5 h-auto flex-shrink-0">Configure →</Link>}
          </div>
          <div className="flex items-start gap-3 py-2 last:pb-0">
            <span className={`text-base font-bold flex-shrink-0 mt-px ${bot.allowed_origins.length > 0 ? "text-emerald-500" : "text-amber-500"}`}>
              {bot.allowed_origins.length > 0 ? "✓" : "⚠"}
            </span>
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-800">Allowed domains</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {bot.allowed_origins.length > 0
                  ? `${bot.allowed_origins.length} domain(s) allowlisted — only those can embed this assistant.`
                  : "Open to all origins — restrict to your production domain before launch."}
              </p>
            </div>
            <Link to="?tab=config" className="btn-ghost text-xs px-3 py-1.5 h-auto flex-shrink-0">Edit →</Link>
          </div>
        </div>
      </SectionCard>

      {/* ── Publishable key ── */}
      <SectionCard title="Publishable key">
        <div className="flex items-center gap-2">
          <input readOnly value={pk} className="input flex-1 text-xs font-mono" />
          <CopyButton value={pk} />
          <button type="button" onClick={rotateKey} disabled={rotating}
            className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap">
            {rotating ? "Rotating…" : "Rotate key"}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Safe to expose in public HTML and client-side code — no server secret needed.
          Rotate immediately if compromised.
        </p>
        {rotErr && <p role="alert" className="text-xs text-red-600 mt-2">{rotErr}</p>}
      </SectionCard>

      {/* ── Integration methods ── */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="section-title">Integrate into your product</h3>
          <p className="text-xs text-gray-500 mt-1">Choose the method that fits your stack. All use the same publishable key above.</p>
        </div>

        {/* Method selector */}
        <div className="flex border-b border-gray-100 overflow-x-auto">
          {INTEG_METHODS.map((m) => {
            const isActive = method === m.id;
            return (
              <button key={m.id} type="button" onClick={() => setMethod(m.id)}
                className={`flex-shrink-0 px-4 py-3 text-left transition-colors border-r border-gray-100 last:border-r-0 relative
                  ${isActive ? "bg-brand-50" : "hover:bg-gray-50"}`}>
                {isActive && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-600" />}
                <p className={`text-xs font-semibold ${isActive ? "text-brand-700" : "text-gray-700"}`}>{m.label}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{m.sub}</p>
                {m.badge && (
                  <span className="inline-block text-[9px] bg-brand-100 text-brand-600 px-1.5 py-0.5 rounded-full font-medium mt-1">
                    {m.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Method body */}
        <div className="p-5 space-y-4">
          <p className="text-xs text-gray-600">{active.intro}</p>

          {/* Method-specific callouts */}
          {method === "widget" && (
            <div className="flex flex-wrap gap-3 text-[11px] text-gray-500">
              <span className="flex items-center gap-1"><span className="text-brand-500">✦</span> Theme &amp; position — set in Configuration</span>
              <span className="flex items-center gap-1"><span className="text-brand-500">✦</span> Open on load — add <code className="font-mono bg-gray-100 px-1 rounded">data-open="true"</code></span>
            </div>
          )}
          {method === "inline" && (
            <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-xs text-amber-800">
              The container needs a fixed height. The widget stretches to fill whatever space you give it.
            </div>
          )}
          {method === "iframe" && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500 flex-shrink-0">Direct URL:</span>
              <code className="font-mono bg-gray-100 px-2 py-0.5 rounded text-gray-700 flex-1 truncate min-w-0">{embedUrl}</code>
              <CopyButton value={embedUrl} label="Copy URL" />
              {bot.is_public && (
                <a href={embedUrl} target="_blank" rel="noreferrer" className="btn-secondary text-xs px-3 py-1.5 h-auto flex-shrink-0">
                  Preview ↗
                </a>
              )}
            </div>
          )}
          {method === "react" && (
            <p className="text-xs text-gray-500">
              Paste the component into any <code className="font-mono bg-gray-100 px-1 rounded">.tsx</code> file.
              The theme color and API URL are pre-filled with your assistant's values.
            </p>
          )}
          {method === "api" && (
            <p className="text-xs text-gray-500">
              No auth token required — only the publishable key in the URL path.
              Rate limited to 60 requests/minute per IP and subject to your daily token quota.
            </p>
          )}

          {/* Code block with copy */}
          <div className="relative group">
            <pre className="code-block text-[11.5px] leading-relaxed overflow-x-auto whitespace-pre">
              {snippets[method]}
            </pre>
            <div className="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton value={snippets[method]} />
            </div>
          </div>
        </div>
      </div>

      {/* ── Public share link ── */}
      <SectionCard title="Public share link">
        <p className="text-xs text-gray-500 mb-3">
          A hosted full-page chat anyone can open — no embed code needed. Share with teammates, clients, or in support emails.
        </p>
        <div className="flex items-center gap-2">
          <input readOnly value={bot.public_url} className="input flex-1 text-xs font-mono" />
          <CopyButton value={bot.public_url} />
          {bot.is_public && (
            <a href={bot.public_url} target="_blank" rel="noreferrer" className="btn-secondary text-xs px-3 py-1.5 h-auto">
              Open ↗
            </a>
          )}
        </div>
      </SectionCard>

    </div>
  );
}

/* ════════════════════════════════════════════
   TAB: ANALYTICS
════════════════════════════════════════════ */
function AnalyticsTab({ bot }: { bot: Chatbot }) {
  const [days,     setDays]     = useState(30);
  const [data,     setData]     = useState<ChatbotAnalytics | null>(null);
  const [requests, setRequests] = useState<RequestLog[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    setLoading(true); setError(null);
    Promise.all([getChatbotAnalytics(bot.id, days), getChatbotRequests(bot.id, 50)])
      .then(([a, r]) => { setData(a); setRequests(r); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load analytics."))
      .finally(() => setLoading(false));
  }, [bot.id, days]);

  const total     = data?.daily.reduce((s, d) => s + d.answers, 0) ?? 0;
  const scored    = data?.daily.filter((d) => d.avg_top_score !== null) ?? [];
  const avgScore  = scored.length ? scored.reduce((s, d) => s + (d.avg_top_score ?? 0), 0) / scored.length : null;
  const noCtx     = total > 0 && data ? data.daily.reduce((s, d) => s + d.no_context_rate * d.answers, 0) / total : 0;
  const refusal   = total > 0 && data ? data.daily.reduce((s, d) => s + d.refusal_rate * d.answers, 0) / total : 0;

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center gap-2">
        <div className="segmented">
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={days === d ? "segmented-item-active" : "segmented-item"}>
              {d} days
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="py-12 text-center text-sm text-gray-400">Loading analytics…</div>
      ) : error ? (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      ) : (
        <>
          {/* Summary metrics */}
          <div className="grid grid-cols-4 gap-4">
            <div className="metric-card">
              <p className="metric-card-label">Answers</p>
              <p className="metric-card-value">{total.toLocaleString()}</p>
              <p className="metric-card-hint">last {days} days</p>
            </div>
            <div className="metric-card">
              <p className="metric-card-label">Avg top score</p>
              <p className={`metric-card-value ${avgScore !== null && avgScore >= 0.7 ? "text-emerald-700" : "text-amber-700"}`}>
                {avgScore !== null ? avgScore.toFixed(3) : "—"}
              </p>
              <p className="metric-card-hint">retrieval strength</p>
            </div>
            <div className="metric-card">
              <p className="metric-card-label">No-context rate</p>
              <p className={`metric-card-value ${noCtx > 0.2 ? "text-amber-700" : ""}`}>
                {Math.round(noCtx * 100)}%
              </p>
              <p className="metric-card-hint">retrieval misses</p>
            </div>
            <div className="metric-card">
              <p className="metric-card-label">Refusal rate</p>
              <p className={`metric-card-value ${refusal > 0.3 ? "text-amber-700" : ""}`}>
                {Math.round(refusal * 100)}%
              </p>
              <p className="metric-card-hint">answered "not in docs"</p>
            </div>
          </div>

          {/* Bar chart */}
          {data && data.daily.length > 0 && (
            <SectionCard title="Daily answers">
              <div className="flex items-end gap-0.5 h-24" role="img" aria-label="Daily answers chart">
                {data.daily.map((d) => {
                  const max = Math.max(...data.daily.map((x) => x.answers), 1);
                  const h   = Math.max(2, Math.round((d.answers / max) * 100));
                  return (
                    <div key={d.day} className="flex-1 rounded-t bg-brand-200 hover:bg-brand-500 transition-colors"
                      style={{ height: `${h}%` }} title={`${d.day}: ${d.answers}`} />
                  );
                })}
              </div>
            </SectionCard>
          )}

          {/* Request log */}
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <p className="section-title">Recent requests</p>
              <span className="text-xs text-gray-400">{requests.length} logged</span>
            </div>
            {requests.length === 0 ? (
              <p className="px-5 py-8 text-sm text-gray-400 text-center">No requests yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Query</th>
                      <th>Status</th>
                      <th className="text-right">Score</th>
                      <th className="text-right">Latency</th>
                      <th className="text-right">Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((r) => (
                      <tr key={r.id}>
                        <td className="text-gray-500 whitespace-nowrap text-xs">
                          {new Date(r.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        </td>
                        <td className="max-w-xs">
                          <span className="truncate block" title={r.query}>{r.query}</span>
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
                        <td className="text-right tabular-nums text-xs">{r.latency_ms}ms</td>
                        <td className="text-right tabular-nums">{r.tokens_used}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════
   ROOT: AssistantDetailPage
════════════════════════════════════════════ */
const TABS: { id: Tab; label: string; icon: typeof Bot }[] = [
  { id: "details",     label: "Assistant Details",  icon: Bot },
  { id: "config",      label: "Call Configuration", icon: SlidersHorizontal },
  { id: "knowledge",   label: "Knowledge Base",     icon: BookOpen },
  { id: "integrations",label: "Integrations",       icon: Zap },
  { id: "post-call",   label: "Post-Call",          icon: ClipboardCheck },
  { id: "recent-calls",label: "Recent Calls",       icon: History },
];

/** Placeholders the welcome message can use, filled from call context at dial
 * time. Surfaced by the `{ }` button so nobody has to guess the spelling. */
const WELCOME_VARIABLES: { token: string; description: string }[] = [
  { token: "user_name",   description: "The contact's name, from your call list." },
  { token: "first_name",  description: "First name only." },
  { token: "company",     description: "Your workspace name." },
  { token: "agent_name",  description: "This assistant's name." },
  { token: "phone",       description: "The number being dialled." },
];

/** "Ask AI" — describe the assistant again and have its flow rewritten. */
function AskAiModal({
  bot,
  onClose,
  onGenerated,
}: {
  bot: Chatbot;
  onClose: () => void;
  onGenerated: (b: Chatbot) => void;
}) {
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (description.trim().length < 10 || busy) return;
    setBusy(true);
    setError(null);
    try {
      onGenerated(await regenerateFlow(bot.id, { description: description.trim() }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not rebuild the flow.");
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="askai-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form onSubmit={submit} className="card w-full max-w-xl p-6 space-y-4 animate-scale-in">
        <div>
          <h2 id="askai-title" className="text-[15px] font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-brand-400" strokeWidth={2} />
            Rebuild this assistant's flow
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Describe what <strong className="text-gray-700">{bot.name}</strong> should do.
            The AI writes a fresh Conversational Flow and welcome message for it.
          </p>
        </div>

        <textarea
          autoFocus
          rows={6}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={4000}
          aria-label="Assistant description"
          placeholder="Call candidates who applied for engineering roles, confirm they're still interested, check their notice period, and book a recruiter callback."
          className="input resize-y text-[13.5px] leading-relaxed bg-surface-2"
        />

        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3.5 py-2.5 text-xs text-amber-800">
          This replaces every section of the current flow. The name, voice, model,
          knowledge base, and publish state are all kept.
        </div>

        {error && (
          <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || description.trim().length < 10}
            className="btn-primary text-sm"
          >
            {busy ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                Writing the flow…
              </>
            ) : (
              "Rebuild flow"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

/** Right-hand slide-over. Used for Test and Deploy, which are both "do a thing
 * to this assistant" rather than "another page of it". */
function SlideOver({
  title,
  onClose,
  wide = false,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className={`h-full bg-canvas border-l border-gray-200 flex flex-col animate-slide-up
                    ${wide ? "w-full max-w-3xl" : "w-full max-w-xl"}`}
      >
        <div className="flex items-center justify-between px-5 h-[58px] border-b border-gray-200 flex-shrink-0">
          <h2 className="text-[15px] font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="icon-btn">
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

/** The Code view: exactly what the model receives, plus the runtime settings. */
function CodeView({ bot, draft }: { bot: Chatbot; draft: Draft }) {
  const composed =
    draft.sections.length > 0
      ? draft.sections
          .filter((s) => s.enabled && s.body.trim())
          .map((s) => `## ${s.title}\n${s.body.trim()}`)
          .join("\n\n")
      : draft.rawPrompt;

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-[14px] font-semibold text-gray-900">Composed system prompt</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              The enabled sections, folded together in order — this exact string is
              what the model is given on every turn.
            </p>
          </div>
          <CopyButton value={composed} />
        </div>
        <pre className="code-block max-h-[420px] overflow-y-auto">{composed || "(empty)"}</pre>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-surface p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[14px] font-semibold text-gray-900">Assistant configuration</h2>
          <CopyButton value={JSON.stringify(draft.assistant, null, 2)} />
        </div>
        <pre className="code-block max-h-64 overflow-y-auto">
          {JSON.stringify({ id: bot.id, name: draft.name, ...draft.assistant }, null, 2)}
        </pre>
      </section>
    </div>
  );
}

export default function AssistantDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") ?? "details") as Tab;

  const [bot, setBot] = useState<Chatbot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Draft of everything the header + Assistant Details tab own. Kept here so
  // the "Saved / Unsaved" indicator has a single thing to look at.
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [codeView, setCodeView] = useState(false);
  const [showVariables, setShowVariables] = useState(false);
  const [showAskAi, setShowAskAi] = useState(false);
  const [showDeploy, setShowDeploy] = useState(false);
  const [testMode, setTestMode] = useState<TestMode | null>(null);
  const [startingTest, setStartingTest] = useState(false);

  /** Reset the draft from a server response — used on load, after Ask AI, and
   * after every save, so the local copy always reflects what was persisted. */
  const adopt = useCallback((next: Chatbot) => {
    setBot(next);
    setDraft({
      name: next.name,
      assistant: next.assistant,
      sections: next.flow_sections,
      rawPrompt: next.system_prompt,
    });
    setDirty(false);
  }, []);

  useEffect(() => {
    getChatbot(id)
      .then(adopt)
      .catch((e) => setError(e.message ?? "Failed to load assistant."))
      .finally(() => setLoading(false));
  }, [id, adopt]);

  function patchDraft(patch: Partial<Draft>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
    setDirty(true);
    setSaveError(null);
  }

  /** Start a test, saving first so it exercises the flow currently on screen.
   *
   * Editing the flow and then testing the *previous* version is the single
   * most confusing thing this page could do — you would tune a section, hear
   * no change, and conclude the section does nothing. So the save is not
   * optional and not a warning banner; it just happens.
   */
  async function startTest(mode: TestMode) {
    if (startingTest) return;
    setStartingTest(true);
    try {
      if (dirty) {
        const saved = await save();
        if (!saved) return; // the error is already on screen
      }
      setTestMode(mode);
    } finally {
      setStartingTest(false);
    }
  }

  async function save(): Promise<boolean> {
    if (!bot || !draft || saving) return false;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateChatbot(bot.id, {
        name: draft.name,
        assistant: draft.assistant,
        // The API rejects both prompt forms together, so send whichever one
        // this assistant is actually authored in.
        ...(draft.sections.length > 0
          ? { flow_sections: draft.sections }
          : { system_prompt: draft.rawPrompt }),
      });
      // The server recomposes and may substitute the stock flow, so take its
      // answer rather than trusting the local draft.
      adopt(updated);
      return true;
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Failed to save.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  // ⌘S saves — this page is edited in long sittings and hunting for the button
  // every time gets old.
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty) save();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function setTab(tab: Tab) {
    setSearchParams({ tab }, { replace: true });
  }

  if (loading) {
    return (
      <div className="px-6 py-6">
        <div className="skeleton h-8 w-64 mb-3" />
        <div className="skeleton h-4 w-40" />
      </div>
    );
  }

  if (error || !bot || !draft) {
    return (
      <div className="px-6 py-6">
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error ?? "Assistant not found."}
        </div>
      </div>
    );
  }

  const outgoing = draft.assistant.direction === "outgoing";
  const testing = testMode !== null;

  return (
    // Two columns: the builder, and the test panel docked beside it. Docked
    // rather than overlaid so you can read a reply and edit the section that
    // caused it without dismissing anything.
    <div className="flex h-full min-h-0 animate-fade-in">
      <div className="flex-1 min-w-0 overflow-y-auto">
      {showAskAi && (
        <AskAiModal
          bot={bot}
          onClose={() => setShowAskAi(false)}
          onGenerated={(b) => {
            adopt(b);
            setShowAskAi(false);
            setTab("details");
          }}
        />
      )}

      {showDeploy && (
        <SlideOver title="Deploy" wide onClose={() => setShowDeploy(false)}>
          <DeploymentsTab bot={bot} onUpdate={setBot} />
        </SlideOver>
      )}

      {/* ── Header ── */}
      <header className="sticky top-0 z-30 glass-chrome border-b">
        <div className="flex items-center gap-3 px-5 h-[58px] flex-wrap">
          <Link
            to="/assistants"
            aria-label="Back to assistants"
            className="chrome-control inline-flex items-center justify-center w-8 h-8 rounded-lg
                       flex-shrink-0"
          >
            <ArrowLeft className="w-[18px] h-[18px]" strokeWidth={2} />
          </Link>

          <input
            value={draft.name}
            onChange={(e) => patchDraft({ name: e.target.value })}
            maxLength={120}
            disabled={testing}
            aria-label="Assistant name"
            className="chrome-btn w-[260px] rounded-lg px-3 py-1.5 text-[14px] font-semibold
                       focus:border-brand-500/60 focus:outline-none"
          />

          {/* Direction */}
          <button
            type="button"
            onClick={() =>
              patchDraft({
                assistant: {
                  ...draft.assistant,
                  direction: outgoing ? "incoming" : "outgoing",
                },
              })
            }
            title={
              outgoing
                ? "Outgoing — the platform dials the contact. Click to switch to incoming."
                : "Incoming — a contact dials in. Click to switch to outgoing."
            }
            disabled={testing}
            className="chrome-btn inline-flex items-center gap-2 rounded-lg px-3 py-1.5
                       text-[13px] font-medium flex-shrink-0"
          >
            {outgoing ? "Outgoing" : "Incoming"}
            <span className="w-5 h-5 rounded-full bg-brand-500/20 flex items-center justify-center">
              {outgoing ? (
                <ArrowUp className="w-3 h-3 text-brand-400" strokeWidth={2.5} />
              ) : (
                <ArrowDown className="w-3 h-3 text-brand-400" strokeWidth={2.5} />
              )}
            </span>
          </button>

          {/* Variables reference */}
          <div className="relative flex-shrink-0">
            <button
              type="button"
              onClick={() => setShowVariables((v) => !v)}
              aria-expanded={showVariables}
              title="Variables you can use in the welcome message"
              className="chrome-btn inline-flex items-center justify-center w-9 h-8 rounded-lg
                         text-[13px] font-mono"
            >
              {"{ }"}
            </button>
            {showVariables && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowVariables(false)} aria-hidden="true" />
                <div className="absolute z-20 left-0 top-full mt-1.5 w-72 rounded-lg border border-gray-200
                                bg-surface shadow-modal p-3">
                  <p className="text-xs text-gray-500 mb-2">
                    Use these in the welcome message — they're replaced with call data
                    when the assistant dials.
                  </p>
                  <ul className="space-y-1.5">
                    {WELCOME_VARIABLES.map((v) => (
                      <li key={v.token} className="text-xs">
                        <code className="code-inline">[{v.token}]</code>
                        <span className="text-gray-500 ml-1.5">{v.description}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </div>

          {/* Save state */}
          <div className="flex items-center gap-2 flex-shrink-0 ml-1">
            {saving ? (
              <span className="text-[13px] text-gray-400 flex items-center gap-1.5">
                <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} />
                Saving…
              </span>
            ) : dirty ? (
              <button onClick={save} disabled={testing} className="btn-primary btn-sm">
                Save changes
              </button>
            ) : (
              <span className="text-[13px] text-gray-500">Saved</span>
            )}
          </div>

          <div className="flex-1" />

          {testing ? (
            <div className="flex items-center gap-3 flex-shrink-0">
              <span className="inline-flex items-center gap-2 rounded-lg bg-cta-500/15 px-3 py-2
                               text-[13px] font-semibold text-cta-400">
                <span className="w-1.5 h-1.5 rounded-full bg-cta-500 animate-pulse" />
                Testing Mode Active
              </span>
              <span className="text-[12.5px] text-gray-500 hidden xl:inline">
                &mdash; Agent configuration is locked during testing
              </span>
            </div>
          ) : (
            <>
              <button
                onClick={() => setShowAskAi(true)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-cta-500 px-3.5 py-2 text-[13px]
                           font-semibold text-white transition-colors hover:bg-cta-600 flex-shrink-0"
              >
                <Sparkles className="w-4 h-4" strokeWidth={2} />
                Ask AI
              </button>

              {/* Test with — saves the draft first; see startTest(). */}
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-[13px] font-semibold text-gray-700">Test with</span>
                <div className="flex items-center rounded-lg overflow-hidden border chrome-rule">
                  <button
                    onClick={() => startTest("chat")}
                    disabled={startingTest}
                    className="inline-flex items-center gap-1.5 bg-brand-600/20 px-3 py-2 text-[13px]
                               font-medium text-brand-300 transition-colors hover:bg-brand-600/30
                               disabled:opacity-50"
                  >
                    {startingTest ? (
                      <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                    ) : (
                      <MessageSquare className="w-4 h-4" strokeWidth={1.75} />
                    )}
                    Chat
                  </button>
                  <button
                    onClick={() => startTest("web-call")}
                    disabled={startingTest}
                    className="inline-flex items-center gap-1.5 bg-brand-600/20 px-3 py-2 text-[13px]
                               font-medium text-brand-300 transition-colors hover:bg-brand-600/30
                               border-l chrome-rule disabled:opacity-50"
                  >
                    <Headphones className="w-4 h-4" strokeWidth={1.75} />
                    Web Call
                  </button>
                  <Link
                    to="/channels"
                    title="Phone calls run through a connected number — set one up under Phone Numbers."
                    className="inline-flex items-center gap-1.5 bg-brand-600/20 px-3 py-2 text-[13px]
                               font-medium text-brand-300 transition-colors hover:bg-brand-600/30
                               border-l chrome-rule"
                  >
                    <Phone className="w-4 h-4" strokeWidth={1.75} />
                    Phone Call
                  </Link>
                </div>
              </div>

              <button
                onClick={() => setShowDeploy(true)}
                className="chrome-btn inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2
                           text-[13px] font-medium flex-shrink-0"
              >
                <Rocket className="w-4 h-4" strokeWidth={1.75} />
                Deploy
                <ChevronDown className="w-3.5 h-3.5" strokeWidth={2} />
              </button>
            </>
          )}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-3 px-5 pb-3 flex-wrap">
          <nav className="flex items-center gap-1 flex-wrap" aria-label="Assistant sections">
            {TABS.map((t) => {
              const Icon = t.icon;
              const active = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-[13.5px]
                              font-medium transition-colors ${
                                active ? "chrome-tab-active" : "chrome-tab"
                              }`}
                >
                  <Icon className="w-4 h-4" strokeWidth={1.75} />
                  {t.label}
                </button>
              );
            })}
          </nav>

          <div className="flex-1" />

          {/* UI ⇄ Code */}
          <div className="chrome-btn flex items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-transparent">
            <span className={`text-[13px] font-semibold ${codeView ? "text-gray-500" : "text-brand-400"}`}>UI</span>
            <button
              type="button"
              role="switch"
              aria-checked={codeView}
              aria-label="Show the composed prompt as code"
              onClick={() => setCodeView((c) => !c)}
              className={`block w-9 h-5 rounded-full relative transition-colors ${
                codeView ? "bg-brand-500" : "bg-gray-300"
              }`}
            >
              <span
                className={`absolute top-[3px] w-3.5 h-3.5 rounded-full bg-white transition-all ${
                  codeView ? "left-[19px]" : "left-[3px]"
                }`}
              />
            </button>
            <span className={`text-[13px] font-semibold ${codeView ? "text-brand-400" : "text-gray-500"}`}>Code</span>
          </div>
        </div>
      </header>

        {/* ── Body ── */}
        <div className="max-w-6xl mx-auto px-6 py-6">
        {saveError && (
          <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {saveError}
          </div>
        )}

        {codeView ? (
          <CodeView bot={bot} draft={draft} />
        ) : (
          <>
            {activeTab === "details" && (
              <AssistantDetailsTab
                bot={bot}
                draft={draft}
                onDraftChange={patchDraft}
                onReplaceBot={adopt}
              />
            )}
            {activeTab === "config" && <ConfigTab bot={bot} onUpdate={setBot} />}
            {activeTab === "knowledge" && <KnowledgeBaseTab chatbotId={bot.id} />}
            {activeTab === "integrations" && <AssistantIntegrationsTab />}
            {activeTab === "post-call" && <PostCallSettings chatbotId={bot.id} />}
            {activeTab === "recent-calls" && <AnalyticsTab bot={bot} />}
          </>
        )}
        </div>
      </div>

      {testMode && (
        <TestModePanel bot={bot} mode={testMode} onClose={() => setTestMode(null)} />
      )}
    </div>
  );
}
