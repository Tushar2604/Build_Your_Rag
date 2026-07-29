import { api } from "./client";

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  tenant_id: string;
  user_id: string;
  role: string;
}

export function register(
  tenantName: string,
  email: string,
  password: string,
): Promise<TokenResponse> {
  return api.post<TokenResponse>("/auth/register", {
    tenant_name: tenantName,
    email,
    password,
  });
}

export function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return api.post<TokenResponse>("/auth/login", { email, password });
}
