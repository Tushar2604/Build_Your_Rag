// QR pairing modal for linking a personal WhatsApp account.
//
// Polls the session rather than holding a socket open: WhatsApp rotates the
// pairing code every ~20s, so the client has to re-read it anyway, and polling
// survives the free-tier host sleeping mid-scan.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  WhatsAppWebSession,
  getWebSession,
  refreshWebSessionQr,
} from "../api/whatsappWeb";

const POLL_MS = 2000;

export default function WhatsAppQrModal({
  session,
  onClose,
  onLinked,
}: {
  session: WhatsAppWebSession;
  onClose: () => void;
  onLinked: (s: WhatsAppWebSession) => void;
}) {
  const [current, setCurrent] = useState(session);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tick, setTick] = useState(0);
  // Avoids a stale closure re-triggering onLinked after the modal has handed
  // control back to the page.
  const doneRef = useRef(false);

  const poll = useCallback(async () => {
    if (doneRef.current) return;
    try {
      const fresh = await getWebSession(session.id);
      setCurrent(fresh);
      setError(null);
      if (fresh.status === "linked") {
        doneRef.current = true;
        onLinked(fresh);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Lost contact with the server.");
    }
  }, [session.id, onLinked]);

  useEffect(() => {
    void poll();
    const timer = setInterval(() => {
      setTick((t) => t + 1);
      void poll();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [poll]);

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      await refreshWebSessionQr(session.id);
      await poll();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate a new code.");
    } finally {
      setRefreshing(false);
    }
  }

  const seconds = current.qr_seconds_remaining;
  const hasQr = Boolean(current.qr_data_url);
  const expired = !hasQr && current.status !== "linked" && current.status !== "pending";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="card w-full max-w-md p-6 relative">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 w-8 h-8 rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700"
        >
          ✕
        </button>

        <div className="flex items-center gap-2">
          <span className="text-xl" aria-hidden="true">💬</span>
          <h2 className="section-title">Scan QR Code</h2>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          Open WhatsApp on your phone → Settings → Linked Devices, then scan this
          code.
        </p>

        <div className="mt-5 flex flex-col items-center">
          <div className="w-64 h-64 rounded-xl bg-white border border-gray-200 flex items-center justify-center overflow-hidden">
            {hasQr ? (
              <img
                src={current.qr_data_url}
                alt="WhatsApp pairing QR code"
                className="w-full h-full object-contain"
              />
            ) : current.status === "linked" ? (
              <div className="text-center px-6">
                <div className="text-3xl mb-2">✅</div>
                <p className="text-sm font-medium text-gray-900">Linked</p>
              </div>
            ) : (
              <div className="text-center px-6">
                <p className="text-sm text-gray-500">
                  {expired ? "This code expired." : "Generating a code…"}
                </p>
              </div>
            )}
          </div>

          {hasQr && (
            <p className="text-xs text-gray-500 mt-3 text-center">
              Scan before the countdown ends, or generate a new QR.
              <br />
              <span className="tabular-nums font-medium text-gray-700">
                Expires in {seconds}s
              </span>
            </p>
          )}

          {(expired || current.status === "failed" || current.status === "logged_out") && (
            <button
              type="button"
              onClick={refresh}
              disabled={refreshing}
              className="btn-secondary text-xs px-3 py-1.5 h-auto mt-3"
            >
              {refreshing ? "Generating…" : "Generate a new QR"}
            </button>
          )}
        </div>

        <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs text-amber-900">
            <strong>⚠ Heads up.</strong> Scanning links your personal WhatsApp to
            this platform as a linked device. Once you attach an assistant,
            incoming messages to this number are answered automatically.
          </p>
          <p className="text-xs text-amber-800 mt-2">
            This uses WhatsApp's unofficial multi-device protocol, which is
            against Meta's terms — numbers doing this can be banned. Use a number
            you can afford to lose.
          </p>
        </div>

        {error && (
          <div role="alert" className="mt-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <p className="text-center text-sm font-medium text-brand-700 mt-4" aria-live="polite">
          {current.status === "linked"
            ? "Connected!"
            : `${current.health} · checking again in ${POLL_MS / 1000}s`}
          <span className="sr-only"> (poll {tick})</span>
        </p>
      </div>
    </div>
  );
}
