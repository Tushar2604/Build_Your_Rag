import { useState, useEffect, FormEvent } from "react";
import { getTeam, inviteTeammate, Team, TeamRole, TenantInvite } from "../api/team";
import { ApiError } from "../api/client";

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

function InviteModal({
  onCreate,
  onClose,
}: {
  onCreate: (invite: TenantInvite) => void;
  onClose: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>("member");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TenantInvite | null>(null);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!email) return;
    setLoading(true);
    setError(null);
    try {
      const invite = await inviteTeammate(email, role);
      setResult(invite);
      onCreate(invite);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send invite.");
    } finally {
      setLoading(false);
    }
  }

  function copy(val: string) {
    navigator.clipboard.writeText(val);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="card shadow-modal w-full max-w-md max-h-[90vh] overflow-y-auto animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">
            {result ? "Invite sent" : "Invite a teammate"}
          </h2>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {result ? (
          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-gray-600">
              {result.email_sent
                ? `An invite email was sent to ${result.email}.`
                : "No email provider is configured — share this link with them directly."}
            </p>
            <div>
              <label className="label">Invite link</label>
              <div className="flex items-center gap-2">
                <input readOnly value={result.invite_url} className="input flex-1 text-xs font-mono" />
                <button type="button" onClick={() => copy(result.invite_url)} className="btn-secondary text-xs px-3 py-1.5 h-auto whitespace-nowrap">
                  Copy
                </button>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <button type="button" onClick={onClose} className="btn-primary">Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreate}>
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="label">Email *</label>
                <input type="email" required className="input" value={email}
                  onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" />
              </div>
              <div>
                <label className="label">Role *</label>
                <select className="input" value={role} onChange={(e) => setRole(e.target.value as TeamRole)}>
                  <option value="admin">Admin — full access, incl. inviting others</option>
                  <option value="member">Member — assistants &amp; knowledge base</option>
                  <option value="viewer">Viewer — read-only</option>
                </select>
                <p className="text-xs text-gray-400 mt-1">
                  Admins can schedule interviews, run the Hiring Agent, manage channels, and invite teammates.
                </p>
              </div>
              {error && (
                <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50/60">
              <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={loading || !email} className="btn-primary">
                {loading ? "Sending…" : "Send invite →"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function TeamPage() {
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [showInvite, setShowInvite] = useState(false);

  useEffect(() => {
    getTeam().then(setTeam).finally(() => setLoading(false));
  }, []);

  function handleInvited(invite: TenantInvite) {
    setTeam((prev) => prev ? { ...prev, pending_invites: [invite, ...prev.pending_invites] } : prev);
  }

  return (
    <div className="page">
      {showInvite && <InviteModal onCreate={handleInvited} onClose={() => setShowInvite(false)} />}

      <div className="page-header">
        <div>
          <h1 className="page-title">Team</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? "Loading…" : `${team?.members.length ?? 0} member${team?.members.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <button onClick={() => setShowInvite(true)} className="btn-primary">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Invite teammate
        </button>
      </div>

      <div className="card overflow-hidden mb-6">
        <div className="px-5 py-3 border-b border-gray-100">
          <p className="text-sm font-semibold text-gray-900">Members</p>
        </div>
        <table className="data-table">
          <thead><tr><th>Email</th><th>Role</th><th>Status</th></tr></thead>
          <tbody>
            {loading ? (
              [...Array(2)].map((_, i) => (
                <tr key={i}><td colSpan={3}><div className="skeleton h-5 w-full" /></td></tr>
              ))
            ) : (
              team?.members.map((m) => (
                <tr key={m.id}>
                  <td className="font-medium text-gray-900">{m.email}</td>
                  <td className="text-gray-600">{ROLE_LABEL[m.role] || m.role}</td>
                  <td>
                    <span className={`badge ${m.is_active ? "badge-live" : "badge-paused"}`}>
                      {m.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {!loading && team && team.pending_invites.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Pending invites</p>
          </div>
          <table className="data-table">
            <thead><tr><th>Email</th><th>Role</th><th>Expires</th></tr></thead>
            <tbody>
              {team.pending_invites.map((i) => (
                <tr key={i.id}>
                  <td className="font-medium text-gray-900">{i.email}</td>
                  <td className="text-gray-600">{ROLE_LABEL[i.role] || i.role}</td>
                  <td className="text-gray-500 text-xs">
                    {new Date(i.expires_at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
