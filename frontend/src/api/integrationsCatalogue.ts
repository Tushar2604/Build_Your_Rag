import { api } from "./client";

export type IntegrationCategory =
  | "calendar_crm"
  | "messaging"
  | "data_sheets"
  | "custom_tools";

export type IntegrationTiming = "during_call" | "post_call";

export interface CredentialField {
  key: string;
  label: string;
  placeholder: string;
  secret: boolean;
  required: boolean;
  help_text: string;
}

export interface IntegrationCard {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategory;
  category_label: string;
  timing: IntegrationTiming;
  auth: "oauth" | "fields";
  credential_fields: CredentialField[];
  /** False = the card renders but Connect is disabled; see unavailable_reason. */
  wired: boolean;
  unavailable_reason: string;
  oauth_start_path: string;
  connected: boolean;
  enabled: boolean;
  /** Secret values arrive masked — never the real credential. */
  config: Record<string, string>;
  connected_at: string | null;
}

export interface IntegrationCatalogue {
  integrations: IntegrationCard[];
  counts: Record<string, number>;
  connected_count: number;
}

export interface IntegrationTestResult {
  ok: boolean;
  message: string;
}

export const CATEGORY_ORDER: { value: IntegrationCategory | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "calendar_crm", label: "Calendar & CRM" },
  { value: "messaging", label: "Messaging" },
  { value: "data_sheets", label: "Data & Sheets" },
  { value: "custom_tools", label: "Custom & Tools" },
];

export function getIntegrationCatalogue(): Promise<IntegrationCatalogue> {
  return api.get<IntegrationCatalogue>("/integrations-catalogue");
}

export function connectIntegration(
  id: string,
  config: Record<string, string>,
): Promise<IntegrationCard> {
  return api.post<IntegrationCard>(`/integrations-catalogue/${id}/connect`, { config });
}

export function testIntegration(id: string): Promise<IntegrationTestResult> {
  return api.post<IntegrationTestResult>(`/integrations-catalogue/${id}/test`);
}

export function disconnectIntegration(id: string): Promise<void> {
  return api.delete<void>(`/integrations-catalogue/${id}`);
}
