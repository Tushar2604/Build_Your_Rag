import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { ApiError } from "../api/client";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate     = useNavigate();
  const [tenantName, setTenantName] = useState("");
  const [email,      setEmail]      = useState("");
  const [password,   setPassword]   = useState("");
  const [error,      setError]      = useState<string | null>(null);
  const [loading,    setLoading]    = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null); setLoading(true);
    try {
      await register(tenantName, email, password);
      navigate("/home");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed. Please try again.");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex bg-white">
      {/* Left branding panel */}
      <div className="hidden lg:flex flex-col w-[480px] flex-shrink-0 bg-gray-950 px-12 py-14">
        <div className="flex items-center gap-2.5 mb-auto">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center flex-shrink-0">
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <span className="font-semibold text-white text-sm tracking-tight">Kore AI</span>
        </div>
        <div className="mt-auto mb-auto">
          <h1 className="text-3xl font-semibold text-white leading-snug tracking-tight">
            Your knowledge.<br />Your assistants.<br />Production-ready.
          </h1>
          <p className="text-gray-400 text-sm mt-4 leading-relaxed max-w-xs">
            Set up your workspace in minutes. No credit card required.
          </p>
          <div className="mt-10 grid grid-cols-2 gap-4">
            {[
              { label: "< 15 min",    desc: "to your first assistant" },
              { label: "100%",        desc: "grounded in your data"  },
              { label: "SOC2",        desc: "compliance ready"        },
              { label: "Open API",    desc: "integrate anywhere"      },
            ].map((s) => (
              <div key={s.label} className="rounded-xl bg-white/5 border border-white/10 px-4 py-3">
                <p className="text-white font-semibold text-base">{s.label}</p>
                <p className="text-gray-500 text-xs mt-0.5">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Kore AI · All rights reserved</p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-gray-50">
        <div className="w-full max-w-sm">
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-7 h-7 rounded-lg bg-brand-600 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <span className="font-semibold text-gray-900 text-sm">Kore AI</span>
          </div>

          <h2 className="text-xl font-semibold text-gray-900 tracking-tight">Create your workspace</h2>
          <p className="text-sm text-gray-500 mt-1">
            Already have an account?{" "}
            <Link to="/login" className="text-brand-600 font-medium hover:text-brand-700">Sign in</Link>
          </p>

          <div className="card p-6 mt-6">
            <form onSubmit={handleSubmit} noValidate className="space-y-4">
              <div>
                <label htmlFor="tenantName" className="label">Organisation name</label>
                <input
                  id="tenantName" type="text" name="organization" autoComplete="organization"
                  required minLength={2} maxLength={120}
                  value={tenantName} onChange={(e) => setTenantName(e.target.value)}
                  className="input" placeholder="Acme Corp"
                />
              </div>
              <div>
                <label htmlFor="email" className="label">Work email</label>
                <input
                  id="email" type="email" name="email" autoComplete="email"
                  required spellCheck={false}
                  value={email} onChange={(e) => setEmail(e.target.value)}
                  className="input" placeholder="you@company.com"
                />
              </div>
              <div>
                <label htmlFor="password" className="label">Password</label>
                <input
                  id="password" type="password" name="new-password" autoComplete="new-password"
                  required minLength={8}
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="input" placeholder="Min. 8 characters"
                />
              </div>

              {error && (
                <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-2.5">
                {loading ? "Creating workspace…" : "Create workspace"}
              </button>
            </form>
          </div>

          <p className="text-[11px] text-gray-400 text-center mt-6">
            By creating an account, you agree to our Terms of Service and Privacy Policy.
          </p>
        </div>
      </div>
    </div>
  );
}
