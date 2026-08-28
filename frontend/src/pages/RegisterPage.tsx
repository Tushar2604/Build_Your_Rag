import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, AlertCircle } from "lucide-react";
import { useAuth } from "../store/auth";
import GoogleSignInButton from "../components/GoogleSignInButton";
import PasswordInput from "../components/PasswordInput";
import { ApiError } from "../api/client";

const STATS = [
  { label: "< 15 min",  desc: "to your first assistant" },
  { label: "100%",      desc: "grounded in your data"  },
  { label: "SOC2",      desc: "compliance ready"        },
  { label: "Open API",  desc: "integrate anywhere"      },
];

export default function RegisterPage() {
  const { register, applySession } = useAuth();
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
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed. Please try again.");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex aurora-shell">
      {/* Left branding panel */}
      <div className="relative hidden lg:flex flex-col w-[520px] flex-shrink-0 px-14 py-14">
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="relative flex items-center gap-2.5 mb-auto"
        >
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 flex items-center justify-center flex-shrink-0 shadow-[0_6px_20px_-6px_rgba(139,92,246,0.8)]">
            <Sparkles className="w-[18px] h-[18px] text-white" strokeWidth={2} />
          </div>
          <span className="font-display font-bold text-white text-[15px] tracking-tight">
            Evara<span className="text-aurora">AI</span>
          </span>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
          className="relative mt-auto mb-auto"
        >
          <span className="pill-glow mb-6">Free to start</span>

          <h1 className="font-display text-[44px] font-light text-gray-500 leading-[1.1] tracking-[-0.03em]">
            Your knowledge.<br />
            <span className="font-semibold text-white">Your assistants.</span><br />
            Production-ready.
          </h1>
          <p className="text-gray-400 text-sm mt-5 leading-relaxed max-w-sm">
            Set up your workspace in minutes. No credit card required.
          </p>
          <div className="mt-10 grid grid-cols-2 gap-4">
            {STATS.map((s, i) => (
              <motion.div
                key={s.label}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.2 + i * 0.06, ease: "easeOut" }}
                className="rounded-2xl bg-white/[0.05] border border-white/10 px-4 py-3.5 backdrop-blur-md transition-all duration-300 hover:bg-white/[0.09] hover:border-brand-400/40 hover:-translate-y-0.5"
              >
                <p className="font-display text-white font-semibold text-base">{s.label}</p>
                <p className="text-gray-500 text-xs mt-0.5">{s.desc}</p>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <p className="relative text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Evara AI · All rights reserved</p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-sm"
        >
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={2} />
            </div>
            <span className="font-display font-bold text-gray-900 text-sm">Evara AI</span>
          </div>

          <h2 className="font-display text-[26px] font-semibold text-gray-900 tracking-tight">Create your workspace</h2>
          <p className="text-sm text-gray-500 mt-1.5">
            Already have an account?{" "}
            <Link to="/login" className="link">Sign in</Link>
          </p>

          <div className="card shadow-modal p-7 mt-7">
            <GoogleSignInButton
              intent="signup"
              onSignedIn={(session) => {
                applySession(session);
                navigate("/dashboard", { replace: true });
              }}
            />

            <form onSubmit={handleSubmit} noValidate className="space-y-4 mt-4">
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
                <div role="alert" aria-live="polite" className="rounded-xl bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-600 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
                  {error}
                </div>
              )}

              <div className="glow-ring">
                <button type="submit" disabled={loading} className="btn-cta w-full justify-center py-3">
                  {loading ? "Creating workspace…" : "Create workspace"}
                </button>
              </div>
            </form>
          </div>

          <p className="text-[11px] text-gray-400 text-center mt-6">
            By creating an account, you agree to our Terms of Service and Privacy Policy.
          </p>
        </motion.div>
      </div>
    </div>
  );
}
