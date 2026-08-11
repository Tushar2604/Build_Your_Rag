// The OAuth popup handshake, shared by "Connect an integration" and "Sign in
// with Google".
//
// The whole point is that the user never handles a token: they click, approve in
// their own account, and the popup reports back and closes itself. The main
// window never navigates, so nothing on the page is lost — and for sign-in, the
// session arrives by postMessage rather than in a URL, keeping it out of browser
// history, referrer headers, and proxy logs.
import { api } from "./client";
import { TokenResponse } from "./auth";

export interface OAuthStatus {
  provider: string;
  connected: boolean;
  account_label: string;
  /** False = no OAuth app registered on the server for this vendor. */
  configured: boolean;
}

/** What the callback page posts back. Extra fields vary by flow. */
interface OAuthPopupMessage {
  source: "oauth";
  provider: string;
  ok: boolean;
  session?: TokenResponse;
  email?: string;
}

const POPUP_WIDTH = 560;
const POPUP_HEIGHT = 720;
/** Backstop for the case where the popup is closed without ever reporting. */
const CLOSE_POLL_MS = 500;

/**
 * Open a consent screen and resolve with whatever the callback posts back.
 *
 * Resolves `null` if the user closed the popup or denied access — both are
 * ordinary outcomes, not errors, so neither throws. A popup blocked by the
 * browser falls back to a full-page navigation rather than dead-ending.
 */
function runPopup(
  authorizeUrl: string,
  provider: string,
): Promise<OAuthPopupMessage | null> {
  const left = window.screenX + (window.outerWidth - POPUP_WIDTH) / 2;
  const top = window.screenY + (window.outerHeight - POPUP_HEIGHT) / 2;
  const popup = window.open(
    authorizeUrl,
    `oauth_${provider}`,
    `width=${POPUP_WIDTH},height=${POPUP_HEIGHT},left=${left},top=${top}`,
  );

  if (!popup) {
    window.location.assign(authorizeUrl);
    return Promise.resolve(null);
  }

  return new Promise((resolve) => {
    let settled = false;

    function finish(result: OAuthPopupMessage | null) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      clearInterval(closeTimer);
      resolve(result);
    }

    function onMessage(event: MessageEvent) {
      // Only trust our own origin — the callback page posts to it explicitly,
      // after verifying it server-side against the deployment's own origins.
      if (event.origin !== window.location.origin) return;
      const data = event.data as OAuthPopupMessage | null;
      if (!data || data.source !== "oauth" || data.provider !== provider) return;
      finish(data);
    }

    window.addEventListener("message", onMessage);
    // The popup closing without a message means the user dismissed it.
    const closeTimer = setInterval(() => {
      if (popup.closed) finish(null);
    }, CLOSE_POLL_MS);
  });
}

export function getOAuthStatus(provider: string): Promise<OAuthStatus> {
  return api.get<OAuthStatus>(`/integrations/oauth/${provider}/status`);
}

export function disconnectOAuth(provider: string): Promise<void> {
  return api.delete<void>(`/integrations/oauth/${provider}`);
}

/**
 * Connect an integration. Resolves `true` once the vendor consent is stored.
 *
 * A genuinely broken setup (no OAuth app configured) throws, because that one
 * needs an administrator rather than another click.
 */
export async function connectOAuth(provider: string): Promise<boolean> {
  // Fetched first, and authenticated: a plain navigation to the start endpoint
  // wouldn't carry the bearer token.
  const { authorize_url } = await api.get<{ authorize_url: string }>(
    `/integrations/oauth/${provider}/start`,
  );
  const result = await runPopup(authorize_url, provider);
  return result?.ok === true;
}

/**
 * Sign in with Google. Resolves the session, or `null` if the person backed out.
 *
 * Throws only when the server has no Google app registered — the login page
 * hides the button in that case, so it should be unreachable.
 */
export async function signInWithGoogle(): Promise<TokenResponse | null> {
  const { authorize_url } = await api.get<{ authorize_url: string }>(
    "/auth/google/start",
  );
  const result = await runPopup(authorize_url, "google_login");
  return result?.ok ? (result.session ?? null) : null;
}
