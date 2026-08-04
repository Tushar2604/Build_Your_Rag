import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, AlertCircle } from "lucide-react";
import { useAuth } from "../store/auth";
import { ApiError } from "../api/client";

const STATS = [
  { label: "< 15 min",  desc: "to your first assistant" },
  { label: "100%",      desc: "grounded in your data"  },
  { label: "SOC2",      desc: "compliance ready"        },
  { label: "Open API",  desc: "integrate anywhere"      },
];

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
      <div className="relative hidden lg:flex flex-col w-[480px] flex-shrink-0 mesh-bg-navy px-12 py-14 overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_100%,rgba(255,255,255,0.06),transparent_55%)]" />

        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="relative flex items-center gap-2.5 mb-auto"
        >
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-brand-900/40">
            <Sparkles className="w-[18px] h-[18px] text-white" strokeWidth={2} />
          </div>
          <span className="font-semibold text-white text-sm tracking-tight">Kore AI</span>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
          className="relative mt-auto mb-auto"
        >
          <h1 className="text-4xl font-extrabold text-white leading-[1.1] tracking-tight">
            Your knowledge.<br />Your assistants.<br />Production-ready.
          </h1>
          <p className="text-gray-400 text-sm mt-4 leading-relaxed max-w-xs">
            Set up your workspace in minutes. No credit card required.
          </p>
          <div className="mt-10 grid grid-cols-2 gap-4">
            {STATS.map((s, i) => (
              <motion.div
                key={s.label}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.2 + i * 0.06, ease: "easeOut" }}
                className="rounded-xl bg-white/[0.05] border border-white/10 px-4 py-3 transition-colors hover:bg-white/[0.08] hover:border-brand-400/30"
              >
                <p className="text-white font-semibold text-base">{s.label}</p>
                <p className="text-gray-500 text-xs mt-0.5">{s.desc}</p>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <p className="relative text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Kore AI · All rights reserved</p>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 mesh-bg lg:bg-none lg:bg-canvas">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-sm"
        >
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={2} />
            </div>
            <span className="font-semibold text-gray-900 text-sm">Kore AI</span>
          </div>

          <h2 className="text-2xl font-bold text-gray-900 tracking-tight">Create your workspace</h2>
          <p className="text-sm text-gray-500 mt-1">
            Already have an account?{" "}
            <Link to="/login" className="link">Sign in</Link>
          </p>

          <div className="card shadow-modal backdrop-blur-sm bg-white/90 p-6 mt-6">
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
                <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
                  {error}
                </div>
              )}

              <button type="submit" disabled={loading} className="btn-cta w-full justify-center py-2.5">
                {loading ? "Creating workspace…" : "Create workspace"}
              </button>
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
