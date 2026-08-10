// One integration card, shared by the Integrations page and the per-assistant
// Integrations tab so the two can never disagree about how a connection is made.
//
// The connect path branches on `auth`: OAuth integrations open a consent popup
// and are done; credential integrations open a form. Everything else about the
// card — status, disconnect, test — is identical either way.
import { useState } from "react";
import { Check, ExternalLink, Loader2, Plug, Trash2, Zap } from "lucide-react";
import { IntegrationCard, disconnectIntegration, testIntegration } from "../api/integrationsCatalogue";
import { connectOAuth } from "../api/oauth";
import { ApiError } from "../api/client";

interface Props {
  card: IntegrationCard;
  /** Called after any change so the parent can refetch the catalogue. */
  onChanged: () => void;
  /** Opens the credential form. Omitted where field-based connect isn't offered. */
  onRequestCredentials?: (card: IntegrationCard) => void;
}

function TimingBadge({ timing }: { timing: IntegrationCard["timing"] }) {
  const during = timing === "during_call";
  return (
    <span
      title={
        during
          ? "The assistant can call this while a conversation is happening."
          : "Runs after a conversation ends, as part of post-call delivery."
      }
      className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${
        during
          ? "border-emerald-300 text-emerald-700 bg-emerald-50"
          : "border-blue-300 text-blue-700 bg-blue-50"
      }`}
    >
      {during ? "During Call" : "Post Call"}
    </span>
  );
}

export default function IntegrationCardTile({ card, onChanged, onRequestCredentials }: Props) {
  const [busy, setBusy] = useState<"connect" | "test" | "disconnect" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function connect() {
    if (card.auth === "oauth") {
      setBusy("connect");
      setMessage(null);
      try {
        const ok = await connectOAuth(card.id);
        if (ok) {
          onChanged();
        } else {
          // Dismissing the consent screen is a choice, not a failure — say so
          // plainly and leave the card exactly as it was.
          setMessage({ ok: false, text: "Not connected — access wasn't granted." });
        }
      } catch (e) {
        setMessage({
          ok: false,
          text: e instanceof ApiError ? e.message : "Could not start the connection.",
        });
      } finally {
        setBusy(null);
      }
      return;
    }
    onRequestCredentials?.(card);
  }

  async function test() {
    setBusy("test");
    setMessage(null);
    try {
      const result = await testIntegration(card.id);
      setMessage({ ok: result.ok, text: result.message });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : "Test failed." });
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    setBusy("disconnect");
    setMessage(null);
    try {
      await disconnectIntegration(card.id);
      onChanged();
    } catch (e) {
      setMessage({
        ok: false,
        text: e instanceof ApiError ? e.message : "Could not disconnect.",
      });
    } finally {
      setBusy(null);
    }
  }

  const account = card.config.account || "";

  return (
    <div className="rounded-xl border border-gray-200 bg-surface p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <span className="flex-shrink-0 w-9 h-9 rounded-lg bg-brand-500/10 flex items-center justify-center">
          <Plug className="w-4 h-4 text-brand-400" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[14px] font-semibold text-gray-900">{card.name}</h3>
            {card.connected && (
              <span className="badge badge-live">
                <Check className="w-3 h-3 mr-0.5" strokeWidth={2.5} />
                Connected
              </span>
            )}
            <TimingBadge timing={card.timing} />
            {card.auth === "oauth" && (
              <span
                title="Connects with one click — you approve it in your own account, and no key is ever typed here."
                className="rounded-full border border-brand-500/40 bg-brand-500/10 px-2 py-0.5
                           text-[10px] font-semibold text-brand-400 whitespace-nowrap"
              >
                1-click
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-1 leading-relaxed">{card.description}</p>
          {card.connected && account && (
            <p className="text-xs text-gray-500 mt-1.5">
              Connected as <span className="text-gray-700 font-medium">{account}</span>
            </p>
          )}
        </div>
      </div>

      {!card.wired && card.unavailable_reason && (
        <p className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 leading-relaxed">
          {card.unavailable_reason}
        </p>
      )}

      {message && (
        <p
          role="status"
          className={`text-[11px] rounded-lg px-3 py-2 border leading-relaxed ${
            message.ok
              ? "text-emerald-700 bg-emerald-50 border-emerald-200"
              : "text-red-700 bg-red-50 border-red-200"
          }`}
        >
          {message.text}
        </p>
      )}

      <div className="flex items-center gap-2 mt-auto pt-1">
        {card.connected ? (
          <>
            <button onClick={test} disabled={busy !== null} className="btn-secondary btn-sm">
              {busy === "test" ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} />
              ) : (
                <Zap className="w-3.5 h-3.5" strokeWidth={2} />
              )}
              Test
            </button>
            <button
              onClick={connect}
              disabled={busy !== null || !card.wired}
              className="btn-secondary btn-sm"
            >
              Reconnect
            </button>
            <button
              onClick={disconnect}
              disabled={busy !== null}
              className="btn-ghost btn-sm text-red-600 hover:text-red-700 ml-auto"
            >
              {busy === "disconnect" ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} />
              ) : (
                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
              )}
              Disconnect
            </button>
          </>
        ) : (
          <button
            onClick={connect}
            disabled={busy !== null || !card.wired}
            title={card.wired ? undefined : card.unavailable_reason}
            className="btn-primary btn-sm"
          >
            {busy === "connect" ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} />
                Waiting for approval…
              </>
            ) : (
              <>
                Connect
                {card.auth === "oauth" && <ExternalLink className="w-3.5 h-3.5" strokeWidth={2} />}
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
