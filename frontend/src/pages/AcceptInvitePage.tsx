import { useState, useEffect, FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../store/auth";
import { getInviteBootstrap, acceptInvite, InviteBootstrap } from "../api/team";
import PasswordInput from "../components/PasswordInput";

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin", member: "Member", viewer: "Viewer",
};

export default function AcceptInvitePage() {
  const { token = "" } = useParams();
  const { applySession } = useAuth();
  const navigate = useNavigate();

  const [bootstrap, setBootstrap] = useState<InviteBootstrap | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getInviteBootstrap(token)
      .then(setBootstrap)
      .catch((e) => setLoadErr(e.message || "This invite link is invalid."));
  }, [token]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await acceptInvite(token, password);
      applySession(resp);
      navigate("/dashboard");
    } catch (err) {
      setError((err as Error).message || "Could not accept this invite. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex aurora-shell">
      <div className="hidden lg:flex flex-col w-[480px] flex-shrink-0 bg-ink-950 px-12 py-14">
        <div className="flex items-center gap-2.5 mb-auto">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center flex-shrink-0">
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <span className="font-semibold text-white text-sm tracking-tight">Evara AI</span>
        </div>
        <div className="mt-auto mb-auto">
          <h1 className="text-3xl font-semibold text-white leading-snug tracking-tight">
            You've been invited{bootstrap ? <> to<br />{bootstrap.tenant_name}</> : "."}
          </h1>
          <p className="text-gray-400 text-sm mt-4 leading-relaxed max-w-xs">
            Set your password to join the team.
          </p>
        </div>
        <p className="text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Evara AI · All rights reserved</p>
      </div>

      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-canvas">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-7 h-7 rounded-lg bg-brand-600 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <span className="font-semibold text-gray-900 text-sm">Evara AI</span>
          </div>

          {loadErr ? (
            <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {loadErr}
            </div>
          ) : !bootstrap ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : !bootstrap.valid ? (
            <div role="alert" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              This invite has expired or was already used. Ask whoever invited you to send a new one.
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-gray-900 tracking-tight">Join {bootstrap.tenant_name}</h2>
              <p className="text-sm text-gray-500 mt-1">
                {bootstrap.email} · {ROLE_LABEL[bootstrap.role] || bootstrap.role}
              </p>

              <div className="card p-6 mt-6">
                <form onSubmit={handleSubmit} noValidate className="space-y-4">
                  <div>
                    <label htmlFor="password" className="label">Set a password</label>
                    <PasswordInput
                      id="password"
                      value={password}
                      onChange={setPassword}
                      autoComplete="new-password"
                      minLength={8}
                      placeholder="Min. 8 characters"
                    />
                  </div>

                  {error && (
                    <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                      {error}
                    </div>
                  )}

                  <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-2.5">
                    {loading ? "Joining…" : "Join workspace"}
                  </button>
                </form>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
