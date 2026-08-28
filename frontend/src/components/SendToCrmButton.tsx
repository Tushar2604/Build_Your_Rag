// "Send to CRM" — one candidate's whole record pushed to whatever CRM this
// workspace runs, from wherever that candidate is on screen.
//
// One component rather than two, because the grid and the profile page must
// not disagree about what the button says: this is an action with a real
// outside effect, and "did that actually go?" is answered by the label.
//
// The destination is a workspace setting, so it is fetched once per *page* and
// handed down — sixty cards each asking the same question would be sixty
// identical requests for one answer that cannot differ between them.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, Check, Loader2, Share2 } from "lucide-react";

import {
  CrmDestination,
  exportCandidateToCrm,
  getCrmDestination,
} from "../api/candidates";
import { ApiError } from "../api/client";

/** Fetches the workspace's CRM destination once. `null` while unknown, so a
 * caller can tell "still loading" from "definitely not connected". */
export function useCrmDestination(): CrmDestination | null {
  const [destination, setDestination] = useState<CrmDestination | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCrmDestination()
      .then((d) => { if (!cancelled) setDestination(d); })
      // A failed lookup is treated as "not connected": the button then points
      // at Integrations, which is where the fix lives either way.
      .catch(() => {
        if (!cancelled) {
          setDestination({ connected: false, endpoint_host: "", settings_path: "/integrations" });
        }
      });
    return () => { cancelled = true; };
  }, []);

  return destination;
}

type Phase = "idle" | "sending" | "sent" | "failed";

interface Props {
  candidateId: string;
  candidateName: string;
  destination: CrmDestination | null;
  /** "sm" is the grid card's inline action; "md" the profile header's. */
  size?: "sm" | "md";
  className?: string;
}

export default function SendToCrmButton({
  candidateId, candidateName, destination, size = "md", className = "",
}: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [detail, setDetail] = useState("");

  const send = useCallback(
    async (e: React.MouseEvent) => {
      // The grid card is a link; this button sits on top of it and must not
      // navigate on its way to sending.
      e.preventDefault();
      e.stopPropagation();
      if (phase === "sending") return;

      setPhase("sending");
      setDetail("");
      try {
        const result = await exportCandidateToCrm(candidateId);
        setPhase(result.delivered ? "sent" : "failed");
        setDetail(result.message);
      } catch (err) {
        setPhase("failed");
        setDetail(err instanceof ApiError ? err.message : "Could not reach the server.");
      }
    },
    [candidateId, phase],
  );

  const base =
    size === "sm"
      ? "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors"
      : "btn btn-sm";

  // Not connected yet — a Connect link rather than a button that would only
  // ever return the same 400. It stays visible so the capability is
  // discoverable from the candidate, which is where you want it.
  if (destination && !destination.connected) {
    return (
      <Link
        to={destination.settings_path}
        onClick={(e) => e.stopPropagation()}
        title="Connect your CRM to send candidates to it"
        className={`${base} ${
          size === "sm"
            ? "bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-800"
            : "btn-secondary"
        } ${className}`}
      >
        <Share2 className="h-3.5 w-3.5 flex-shrink-0" strokeWidth={2} />
        Connect CRM
      </Link>
    );
  }

  const label =
    phase === "sending" ? "Sending…"
    : phase === "sent" ? "Sent to CRM"
    : phase === "failed" ? "Retry send"
    : "Send to CRM";

  const Icon =
    phase === "sending" ? Loader2
    : phase === "sent" ? Check
    : phase === "failed" ? AlertCircle
    : Share2;

  const tone =
    size === "sm"
      ? phase === "sent"
        ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
        : phase === "failed"
          ? "bg-red-50 text-red-700 hover:bg-red-100"
          : "bg-brand-500/10 text-brand-600 hover:bg-brand-500/20"
      : phase === "sent"
        ? "btn-secondary !text-emerald-700"
        : phase === "failed"
          ? "btn-secondary !text-red-700"
          : "btn-primary";

  return (
    <button
      type="button"
      onClick={send}
      disabled={destination === null || phase === "sending"}
      // The outcome message is the CRM's own words on failure ("HTTP 422:
      // missing field"), which is the only thing that makes it fixable.
      title={detail || `Push ${candidateName || "this candidate"} into your CRM`}
      aria-live="polite"
      className={`${base} ${tone} disabled:opacity-50 disabled:pointer-events-none ${className}`}
    >
      <Icon
        className={`h-3.5 w-3.5 flex-shrink-0 ${phase === "sending" ? "animate-spin" : ""}`}
        strokeWidth={2}
      />
      {label}
    </button>
  );
}
