import { api } from "./client";
import { TokenResponse } from "./auth";

export type TeamRole = "admin" | "member" | "viewer";

export interface TeamMember {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TenantInvite {
  id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  invite_url: string;
  email_sent: boolean;
}

export interface Team {
  members: TeamMember[];
  pending_invites: TenantInvite[];
}

export interface InviteBootstrap {
  tenant_name: string;
  email: string;
  role: string;
  valid: boolean;
}

export function getTeam(): Promise<Team> {
  return api.get<Team>("/team");
}

export function inviteTeammate(email: string, role: TeamRole): Promise<TenantInvite> {
  return api.post<TenantInvite>("/team/invites", { email, role });
}

const BASE = "/api/v1";

export async function getInviteBootstrap(token: string): Promise<InviteBootstrap> {
  const res = await fetch(`${BASE}/team/invites/${encodeURIComponent(token)}`);
  if (!res.ok) throw new Error(res.status === 404 ? "Invite not found" : `HTTP ${res.status}`);
  return res.json();
}

export async function acceptInvite(token: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${BASE}/team/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
