// One-click OAuth connect, run in a popup.
//
// The whole point is that the user never handles a token: they click Connect,
// approve in their own account, and the popup reports back and closes itself.
// The main window never navigates, so nothing in the page is lost.
import { api } from "./client";

export interface OAuthStatus {
  provider: string;
  connected: boolean;
  account_label: string;
  /** False = no OAuth app registered on the server for this vendor. */
  configured: boolean;
}

interface OAuthPopupMessage {
  source: "oauth";
  provider: string;
  ok: boolean;
}

const POPUP_WIDTH = 560;
const POPUP_HEIGHT = 720;
/** Backstop for the case where the popup is closed without ever reporting. */
const CLOSE_POLL_MS = 500;

export function getOAuthStatus(provider: string): Promise<OAuthStatus> {
  return api.get<OAuthStatus>(`/integrations/oauth/${provider}/status`);
}

export function disconnectOAuth(provider: string): Promise<void> {
  return api.delete<void>(`/integrations/oauth/${provider}`);
}

/**
 * Open the vendor's consent screen and resolve once it reports back.
 *
 * Resolves `true` on success, `false` if the user closed the popup or denied
 * access — a denial is a normal outcome, not an error, so it isn't thrown.
 * A genuinely broken setup (no OAuth app configured) does throw, because that
 * one needs an administrator rather than another click.
 */
export async function connectOAuth(provider: string): Promise<boolean> {
  // Fetched first, and authenticated: a plain navigation to the start endpoint
  // wouldn't carry the bearer token.
  const { authorize_url } = await api.get<{ authorize_url: string }>(
    `/integrations/oauth/${provider}/start`,
  );

  const left = window.screenX + (window.outerWidth - POPUP_WIDTH) / 2;
  const top = window.screenY + (window.outerHeight - POPUP_HEIGHT) / 2;
  const popup = window.open(
    authorize_url,
    `oauth_${provider}`,
    `width=${POPUP_WIDTH},height=${POPUP_HEIGHT},left=${left},top=${top}`,
  );

  if (!popup) {
    // Popup blocked. Falling back to a full-page navigation keeps the flow
    // working rather than dead-ending on a blocker the user may not notice.
    window.location.assign(authorize_url);
    return false;
  }

  return new Promise<boolean>((resolve) => {
    let settled = false;

    function finish(result: boolean) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      clearInterval(closeTimer);
      resolve(result);
    }

    function onMessage(event: MessageEvent) {
      // Only trust our own origin — the callback page posts to it explicitly.
      if (event.origin !== window.location.origin) return;
      const data = event.data as OAuthPopupMessage | null;
      if (!data || data.source !== "oauth" || data.provider !== provider) return;
      finish(data.ok);
    }

    window.addEventListener("message", onMessage);
    // The popup closing without a message means the user dismissed it.
    const closeTimer = setInterval(() => {
      if (popup.closed) finish(false);
    }, CLOSE_POLL_MS);
  });
}
