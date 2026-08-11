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

/** Sign-in methods this deployment offers beyond email + password. */
export interface AuthProviders {
  google: boolean;
}

export function getAuthProviders(): Promise<AuthProviders> {
  return api.get<AuthProviders>("/auth/providers");
}
