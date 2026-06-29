import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  getChatbot,
  updateChatbot,
  rotateChatbotKey,
  Chatbot,
} from "../api/chatbots";
import { ApiError } from "../api/client";

function CopyButton({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="btn-secondary h-8 px-3 text-xs whitespace-nowrap"
    >
      {copied ? "Copied!" : label || "Copy"}
    </button>
  );
}

export default function ChatbotSettingsPage() {
  const { chatbotId = "" } = useParams();
  const [bot, setBot] = useState<Chatbot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // editable fields
  const [isPublic, setIsPublic] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [themeColor, setThemeColor] = useState("#4f46e5");
  const [welcome, setWelcome] = useState("");
  const [position, setPosition] = useState<"bottom-right" | "bottom-left">("bottom-right");
  const [originsText, setOriginsText] = useState("");

  useEffect(() => {
    getChatbot(chatbotId)
      .then((b) => {
        setBot(b);
        setIsPublic(b.is_public);
        setDisplayName(b.widget.display_name);
        setThemeColor(b.widget.theme_color);
        setWelcome(b.widget.welcome_message);
        setPosition(b.widget.launcher_position);
        setOriginsText(b.allowed_origins.join("\n"));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load chatbot."));
  }, [chatbotId]);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const origins = originsText
        .split("\n")
        .map((o) => o.trim())
        .filter(Boolean);
      const updated = await updateChatbot(chatbotId, {
        is_public: isPublic,
        allowed_origins: origins,
        widget: {
          display_name: displayName,
          theme_color: themeColor,
          welcome_message: welcome,
          launcher_position: position,
        },
      });
      setBot(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function rotate() {
    if (!confirm("Rotate the publishable key? Any snippet already deployed with the old key will stop working.")) return;
    try {
      const updated = await rotateChatbotKey(chatbotId);
      setBot(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to rotate key.");
    }
  }

  if (error && !bot) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }
  if (!bot) {
    return <div className="text-center py-16 text-sm text-gray-400">Loading…</div>;
  }

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 sm:px-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to={`/chatbots/${chatbotId}`} className="text-xs text-brand-600 hover:underline">
            ← Back to chat
          </Link>
          <h1 className="text-xl font-semibold text-gray-900 mt-1">Embed &amp; Share</h1>
          <p className="text-sm text-gray-500">Deploy “{bot.name}” to any website.</p>
        </div>
      </div>

      {/* Publish toggle */}
      <div className="card p-5">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={isPublic}
            onChange={(e) => setIsPublic(e.target.checked)}
            className="w-4 h-4 mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
          />
          <span>
            <span className="text-sm font-medium text-gray-900">Public</span>
            <p className="text-xs text-gray-500 mt-0.5">
              When on, this chatbot can be embedded and shared via the link below. When off, only
              you (signed in) can use it.
            </p>
          </span>
        </label>
      </div>

      {/* Appearance */}
      <div className="card p-5 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Appearance</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Display name</label>
            <input className="input" value={displayName} maxLength={60}
              onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div>
            <label className="label">Theme color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={themeColor}
                onChange={(e) => setThemeColor(e.target.value)}
                className="h-10 w-12 rounded border border-gray-300 cursor-pointer" />
              <input className="input flex-1" value={themeColor}
                onChange={(e) => setThemeColor(e.target.value)} />
            </div>
          </div>
        </div>
        <div>
          <label className="label">Welcome message</label>
          <textarea className="input resize-none" rows={2} maxLength={300}
            value={welcome} onChange={(e) => setWelcome(e.target.value)} />
        </div>
        <div>
          <label className="label">Launcher position</label>
          <select className="input" value={position}
            onChange={(e) => setPosition(e.target.value as "bottom-right" | "bottom-left")}>
            <option value="bottom-right">Bottom right</option>
            <option value="bottom-left">Bottom left</option>
          </select>
        </div>
      </div>

      {/* Allowed origins */}
      <div className="card p-5 space-y-2">
        <h2 className="text-sm font-semibold text-gray-900">Allowed domains</h2>
        <p className="text-xs text-gray-500">
          One origin per line (e.g. <code>https://example.com</code> or <code>*.example.com</code>).
          Leave empty to allow embedding on any site.
        </p>
        <textarea className="input resize-none font-mono text-xs" rows={3}
          placeholder="https://example.com"
          value={originsText} onChange={(e) => setOriginsText(e.target.value)} />
      </div>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? "Saving…" : "Save changes"}
        </button>
        {saved && <span className="text-sm text-green-600">Saved.</span>}
      </div>

      {/* Integration — only meaningful when public */}
      <div className={`card p-5 space-y-5 ${isPublic ? "" : "opacity-60"}`}>
        <div>
          <h2 className="text-sm font-semibold text-gray-900">1. Embed on your website</h2>
          <p className="text-xs text-gray-500 mt-0.5 mb-2">
            Paste this snippet before <code>&lt;/body&gt;</code> on any page.
          </p>
          <div className="flex items-start gap-2">
            <pre className="flex-1 overflow-x-auto rounded-lg bg-gray-900 text-gray-100 text-xs p-3 whitespace-pre-wrap break-all">
              {bot.embed_snippet}
            </pre>
            <CopyButton value={bot.embed_snippet} label="Copy snippet" />
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold text-gray-900">2. Or share a link</h2>
          <p className="text-xs text-gray-500 mt-0.5 mb-2">
            A full-page chat anyone can open — no code required.
          </p>
          <div className="flex items-center gap-2">
            <input readOnly value={bot.public_url} className="input flex-1 text-xs font-mono" />
            <CopyButton value={bot.public_url} />
            <a href={bot.public_url} target="_blank" rel="noreferrer" className="btn-secondary h-8 px-3 text-xs">
              Open
            </a>
          </div>
        </div>

        <div className="pt-2 border-t border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Publishable key</h2>
          <div className="flex items-center gap-2 mt-2">
            <input readOnly value={bot.public_key} className="input flex-1 text-xs font-mono" />
            <button onClick={rotate} className="btn-secondary h-8 px-3 text-xs whitespace-nowrap">
              Rotate
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Safe to expose publicly. Rotate it if it’s abused — the old snippet then stops working.
          </p>
        </div>
      </div>
    </div>
  );
}
