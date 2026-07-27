import { api } from "./client";

export interface GoogleStatus {
  connected: boolean;
  email: string;
}

export function getGoogleStatus(): Promise<GoogleStatus> {
  return api.get<GoogleStatus>("/integrations/google/status");
}

export function disconnectGoogle(): Promise<void> {
  return api.delete<void>("/integrations/google");
}

/** Fetches the Google consent URL (authenticated) then navigates the whole
 * page there — a plain <a href> can't carry the Bearer token, so this has to
 * go through an authenticated fetch first. */
export async function connectGoogle(): Promise<void> {
  const { authorize_url } = await api.get<{ authorize_url: string }>("/integrations/google/connect");
  window.location.assign(authorize_url);
}
