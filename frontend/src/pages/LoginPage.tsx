import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, Check, AlertCircle } from "lucide-react";
import { useAuth } from "../store/auth";
import { ApiError } from "../api/client";

const FEATURES = [
  "RAG-powered assistants grounded in your data",
  "Real-time streaming with citation transparency",
  "Knowledge gaps analytics — know what to add next",
  "Web widget, public link, and REST API deployment",
];

export default function LoginPage() {
  const { login }   = useAuth();
  const navigate    = useNavigate();
  const [email,     setEmail]    = useState("");
  const [password,  setPassword] = useState("");
  const [error,     setError]    = useState<string | null>(null);
  const [loading,   setLoading]  = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null); setLoading(true);
    try {
      await login(email, password);
      navigate("/home");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid email or password.");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex bg-surface">
      {/* Left panel — animated gradient mesh branding */}
      <div className="relative hidden lg:flex flex-col w-[480px] flex-shrink-0 mesh-bg-navy px-12 py-14 overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_100%,rgba(255,255,255,0.06),transparent_55%)]" />

        {/* Logo */}
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

        {/* Headline */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
          className="relative mt-auto mb-auto"
        >
          <h1 className="text-4xl font-extrabold text-white leading-[1.1] tracking-tight">
            Deploy AI assistants<br />powered by your<br />knowledge.
          </h1>
          <p className="text-gray-400 text-sm mt-4 leading-relaxed max-w-xs">
            Production-ready AI for enterprise teams. Connect your docs, configure behavior, ship in minutes.
          </p>

          {/* Feature list */}
          <ul className="mt-8 space-y-3">
            {FEATURES.map((f, i) => (
              <motion.li
                key={f}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: 0.2 + i * 0.06, ease: "easeOut" }}
                className="flex items-start gap-2.5 text-sm text-gray-400"
              >
                <Check className="w-4 h-4 text-brand-400 mt-0.5 flex-shrink-0" strokeWidth={2.5} />
                {f}
              </motion.li>
            ))}
          </ul>
        </motion.div>

        <p className="relative text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Kore AI · All rights reserved</p>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 mesh-bg lg:bg-none lg:bg-canvas">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-sm"
        >
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={2} />
            </div>
            <span className="font-semibold text-gray-900 text-sm">Kore AI</span>
          </div>

          <h2 className="text-2xl font-bold text-gray-900 tracking-tight">Sign in to your workspace</h2>
          <p className="text-sm text-gray-500 mt-1">
            Don't have an account?{" "}
            <Link to="/register" className="link">
              Create one free
            </Link>
          </p>

          <div className="card shadow-modal p-6 mt-6">
            <form onSubmit={handleSubmit} noValidate className="space-y-4">
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
                  id="password" type="password" name="password" autoComplete="current-password"
                  required
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className="input" placeholder="••••••••"
                />
              </div>

              {error && (
                <div role="alert" aria-live="polite" className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
                  {error}
                </div>
              )}

              <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-2.5">
                {loading ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </div>

          <p className="text-[11px] text-gray-400 text-center mt-6">
            By continuing, you agree to our Terms of Service and Privacy Policy.
          </p>
        </motion.div>
      </div>
    </div>
  );
}
