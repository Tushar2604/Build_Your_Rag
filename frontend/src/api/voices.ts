import { api } from "./client";

export type VoiceGender = "female" | "male" | "neutral";
export type VoiceStatus = "pending" | "ready" | "failed";

export interface VoiceProfile {
  id: string;
  name: string;
  gender: VoiceGender;
  language: string;
  description: string;
  duration_seconds: number;
  sample_bytes: number;
  provider: string;
  status: VoiceStatus;
  error: string;
  created_at: string;
}

export interface VoiceOptions {
  languages: { value: string; label: string }[];
  genders: { value: string; label: string }[];
  min_seconds: number;
  max_seconds: number;
  max_mb: number;
  /** False = samples still record and store, but cloning is unavailable. */
  cloning_enabled: boolean;
  provider: string;
}

export function getVoiceOptions(): Promise<VoiceOptions> {
  return api.get<VoiceOptions>("/voices/options");
}

export function listVoices(): Promise<VoiceProfile[]> {
  return api.get<VoiceProfile[]>("/voices");
}

export interface CreateVoiceInput {
  sample: Blob;
  filename: string;
  name: string;
  gender: VoiceGender;
  language: string;
  description: string;
  durationSeconds: number;
}

/**
 * Multipart upload — the one endpoint that doesn't go through `api`, because
 * the shared client forces a JSON content-type. Letting fetch set its own
 * multipart boundary is required for the server to parse the parts.
 */
export async function createVoice(input: CreateVoiceInput): Promise<VoiceProfile> {
  const form = new FormData();
  form.append("sample", input.sample, input.filename);
  form.append("name", input.name);
  form.append("gender", input.gender);
  form.append("language", input.language);
  form.append("description", input.description);
  form.append("duration_seconds", String(input.durationSeconds));

  const token = localStorage.getItem("access_token");
  const res = await fetch("/api/v1/voices", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // keep the status text
    }
    throw new Error(detail);
  }
  return res.json() as Promise<VoiceProfile>;
}

export function retryClone(id: string): Promise<VoiceProfile> {
  return api.post<VoiceProfile>(`/voices/${id}/retry`);
}

export function deleteVoice(id: string): Promise<void> {
  return api.delete<void>(`/voices/${id}`);
}

/** Object URL for the original recording. Caller must revoke it. */
export async function fetchSampleUrl(id: string): Promise<string> {
  const token = localStorage.getItem("access_token");
  const res = await fetch(`/api/v1/voices/${id}/sample`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Could not load the sample.");
  return URL.createObjectURL(await res.blob());
}

/** Synthesize text in a cloned voice. Returns an object URL the caller revokes. */
export async function speakUrl(id: string, text: string): Promise<string> {
  const token = localStorage.getItem("access_token");
  const res = await fetch(`/api/v1/voices/${id}/speak`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    let detail = "Preview failed.";
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // keep the default
    }
    throw new Error(detail);
  }
  return URL.createObjectURL(await res.blob());
}
