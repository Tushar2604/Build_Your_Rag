// Post-Call Delivery Settings: N independent rules, each choosing a
// destination, the conversation outcomes that trigger it, and which payload
// blocks to compute.
//
// Each rule is edited locally and saved explicitly, rather than auto-saving on
// every keystroke — a half-typed webhook URL should not become live config.
import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import {
  CALL_STATUSES,
  CallStatus,
  DeliveryMethod,
  PostCallConfig,
  PostCallConfigInput,
  PostCallDelivery,
  createPostCallConfig,
  deletePostCallConfig,
  listPostCallConfigs,
  listPostCallDeliveries,
  updatePostCallConfig,
} from "../api/postCall";

const INCLUDE_FIELDS: {
  key: keyof Pick<
    PostCallConfigInput,
    "include_summary" | "include_transcript" | "include_sentiment" | "include_extracted"
  >;
  label: string;
  hint: string;
}[] = [
  {
    key: "include_summary",
    label: "Call Summary",
    hint: "A brief overview of the conversation including key points and outcomes",
  },
  {
    key: "include_transcript",
    label: "Full Conversation",
    hint: "Complete transcript of the entire conversation with timestamps",
  },
  {
    key: "include_sentiment",
    label: "Sentiment Analysis",
    hint: "Analysis of the contact's mood and emotional responses throughout",
  },
  {
    key: "include_extracted",
    label: "Extracted Information",
    hint: "Key data points (name, email, experience, notice period) pulled from the conversation",
  },
];

function toInput(config: PostCallConfig): PostCallConfigInput {
  const { id, chatbot_id, created_at, ...rest } = config;
  return rest;
}

function blankInput(): PostCallConfigInput {
  return {
    delivery_method: "webhook",
    webhook_url: "",
    email_to: "",
    trigger_statuses: ["completed"],
    include_summary: true,
    include_transcript: true,
    include_sentiment: false,
    include_extracted: false,
    enabled: true,
  };
}

interface RowProps {
  chatbotId: string;
  config: PostCallConfig | null; // null = an unsaved new rule
  onSaved: (config: PostCallConfig) => void;
  onRemoved: () => void;
}

function ConfigRow({ chatbotId, config, onSaved, onRemoved }: RowProps) {
  const [draft, setDraft] = useState<PostCallConfigInput>(
    config ? toInput(config) : blankInput(),
  );
  const [dirty, setDirty] = useState(config === null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function patch(changes: Partial<PostCallConfigInput>) {
    setDraft((d) => ({ ...d, ...changes }));
    setDirty(true);
    setError(null);
  }

  function toggleStatus(status: CallStatus) {
    const next = draft.trigger_statuses.includes(status)
      ? draft.trigger_statuses.filter((s) => s !== status)
      : [...draft.trigger_statuses, status];
    patch({ trigger_statuses: next });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const saved = config
        ? await updatePostCallConfig(chatbotId, config.id, draft)
        : await createPostCallConfig(chatbotId, draft);
      onSaved(saved);
      setDirty(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save this configuration.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (config) {
      try {
        await deletePostCallConfig(chatbotId, config.id);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to remove.");
        return;
      }
    }
    onRemoved();
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <label className="label">Delivery Method</label>
          <select
            className="input max-w-xs"
            value={draft.delivery_method}
            onChange={(e) =>
              patch({ delivery_method: e.target.value as DeliveryMethod })
            }
          >
            <option value="webhook">Webhook (HTTP POST)</option>
            <option value="email">Email</option>
          </select>
        </div>
        <button
          type="button"
          onClick={remove}
          className="text-xs font-medium text-red-600 hover:text-red-700 px-3 py-1.5"
        >
          🗑 Remove
        </button>
      </div>

      {draft.delivery_method === "webhook" ? (
        <div>
          <label className="label">Webhook URL</label>
          <input
            className="input font-mono text-xs"
            placeholder="https://your-ats.example.com/hooks/post-call"
            value={draft.webhook_url}
            onChange={(e) => patch({ webhook_url: e.target.value })}
          />
          <p className="text-xs text-gray-400 mt-1">
            Signed with HMAC-SHA256. Verify <code>X-Signature</code> against
            <code> timestamp.body</code> using your JWT secret.
          </p>
        </div>
      ) : (
        <div>
          <label className="label">Send to</label>
          <input
            className="input max-w-md"
            type="email"
            placeholder="recruiting@yourcompany.com"
            value={draft.email_to}
            onChange={(e) => patch({ email_to: e.target.value })}
          />
        </div>
      )}

      <div>
        <label className="label">Trigger based on Call Status</label>
        <div className="flex flex-wrap gap-2">
          {CALL_STATUSES.map(({ value, label }) => {
            const on = draft.trigger_statuses.includes(value);
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                onClick={() => toggleStatus(value)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  on
                    ? "bg-brand-600 text-white"
                    : "bg-surface text-gray-600 border border-gray-300 hover:border-gray-400"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label className="label">Including</label>
        <div className="grid gap-3 sm:grid-cols-2">
          {INCLUDE_FIELDS.map(({ key, label, hint }) => (
            <label
              key={key}
              className="flex items-start gap-3 rounded-lg border border-gray-200 p-3 cursor-pointer hover:border-gray-300"
            >
              <input
                type="checkbox"
                className="w-4 h-4 mt-0.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                checked={draft[key]}
                onChange={(e) => patch({ [key]: e.target.checked })}
              />
              <span>
                <span className="text-sm font-medium text-gray-900">{label}</span>
                <p className="text-xs text-gray-500 mt-0.5">{hint}</p>
              </span>
            </label>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Sentiment and Extracted Information each cost one extra LLM call per
          conversation — leave them off unless you use them.
        </p>
      </div>

      <div className="flex items-center justify-between border-t border-gray-100 pt-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
            checked={draft.enabled}
            onChange={(e) => patch({ enabled: e.target.checked })}
          />
          <span className="text-sm text-gray-700">Enabled</span>
        </label>
        {dirty && (
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="btn-primary py-1.5 text-xs"
          >
            {saving ? "Saving…" : config ? "Save changes" : "Create configuration"}
          </button>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}

function DeliveryLog({ deliveries }: { deliveries: PostCallDelivery[] }) {
  if (deliveries.length === 0) {
    return (
      <p className="text-sm text-gray-400">
        Nothing dispatched yet. Deliveries fire when a conversation is closed
        with an outcome one of your rules triggers on.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Outcome</th>
            <th>Destination</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {deliveries.map((d) => (
            <tr key={d.id}>
              <td className="text-xs whitespace-nowrap">
                {new Date(d.created_at).toLocaleString()}
              </td>
              <td className="text-xs">{d.call_status}</td>
              <td className="text-xs font-mono truncate max-w-[18rem]" title={d.destination}>
                {d.destination}
              </td>
              <td>
                <span
                  className={`text-xs font-medium ${
                    d.status === "delivered"
                      ? "text-emerald-700"
                      : d.status === "failed"
                        ? "text-red-600"
                        : "text-gray-500"
                  }`}
                  title={d.error || undefined}
                >
                  {d.status}
                  {d.error ? " — " + d.error.slice(0, 80) : ""}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PostCallSettings({ chatbotId }: { chatbotId: string }) {
  const [configs, setConfigs] = useState<PostCallConfig[]>([]);
  const [deliveries, setDeliveries] = useState<PostCallDelivery[]>([]);
  const [drafts, setDrafts] = useState(0); // count of unsaved new rules
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listPostCallConfigs(chatbotId), listPostCallDeliveries(chatbotId)])
      .then(([c, d]) => {
        if (cancelled) return;
        setConfigs(c);
        setDeliveries(d);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Failed to load post-call settings."),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [chatbotId]);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="section-title">Post-Call Delivery Settings</h3>
          <p className="text-xs text-gray-500 mt-1">
            Send a summary, transcript, or extracted fields to your systems when
            a conversation ends.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDrafts((n) => n + 1)}
          className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap"
        >
          + Add Configuration
        </button>
      </div>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {configs.length === 0 && drafts === 0 && (
        <div className="card p-8 text-center">
          <p className="text-sm text-gray-500">No post-call deliveries configured.</p>
          <p className="text-xs text-gray-400 mt-1">
            Add one to push each finished conversation to a webhook or an inbox.
          </p>
        </div>
      )}

      {configs.map((config) => (
        <ConfigRow
          key={config.id}
          chatbotId={chatbotId}
          config={config}
          onSaved={(saved) =>
            setConfigs((prev) => prev.map((c) => (c.id === saved.id ? saved : c)))
          }
          onRemoved={() => setConfigs((prev) => prev.filter((c) => c.id !== config.id))}
        />
      ))}

      {Array.from({ length: drafts }, (_, i) => (
        <ConfigRow
          key={`draft-${i}`}
          chatbotId={chatbotId}
          config={null}
          onSaved={(saved) => {
            setConfigs((prev) => [...prev, saved]);
            setDrafts((n) => n - 1);
          }}
          onRemoved={() => setDrafts((n) => n - 1)}
        />
      ))}

      <div className="card p-5">
        <h3 className="section-title mb-4">Recent deliveries</h3>
        <DeliveryLog deliveries={deliveries} />
      </div>
    </div>
  );
}
