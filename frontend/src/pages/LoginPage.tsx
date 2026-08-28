import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, Check, AlertCircle } from "lucide-react";
import { useAuth } from "../store/auth";
import GoogleSignInButton from "../components/GoogleSignInButton";
import PasswordInput from "../components/PasswordInput";
import { ApiError } from "../api/client";

const FEATURES = [
  "RAG-powered assistants grounded in your data",
  "Real-time streaming with citation transparency",
  "Knowledge gaps analytics — know what to add next",
  "Web widget, public link, and REST API deployment",
];

export default function LoginPage() {
  const { login, applySession } = useAuth();
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
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid email or password.");
    } finally { setLoading(false); }
  }

  return (
    // The whole page is the aurora frame; both columns float on it as glass.
    <div className="min-h-screen flex aurora-shell">
      {/* Left panel — brand hero */}
      <div className="relative hidden lg:flex flex-col w-[520px] flex-shrink-0 px-14 py-14">
        {/* Logo */}
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

        {/* Headline */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
          className="relative mt-auto mb-auto"
        >
          <span className="pill-glow mb-6">Enterprise-grade RAG</span>

          {/* Weight and colour do the emphasis here, not size — the light
              surrounding text is what makes the accent span land. */}
          <h1 className="font-display text-[44px] font-light text-gray-500 leading-[1.1] tracking-[-0.03em]">
            Deploy <span className="font-semibold text-white">AI assistants</span> powered by your knowledge.
          </h1>
          <p className="text-gray-400 text-sm mt-5 leading-relaxed max-w-sm">
            Production-ready AI for enterprise teams. Connect your docs, configure behavior, ship in minutes.
          </p>

          {/* Feature list */}
          <ul className="mt-9 space-y-3.5">
            {FEATURES.map((f, i) => (
              <motion.li
                key={f}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: 0.2 + i * 0.06, ease: "easeOut" }}
                className="flex items-start gap-3 text-sm text-gray-400"
              >
                <span className="mt-0.5 flex-shrink-0 w-5 h-5 rounded-full bg-brand-500/15 border border-brand-400/30 flex items-center justify-center">
                  <Check className="w-3 h-3 text-brand-400" strokeWidth={3} />
                </span>
                {f}
              </motion.li>
            ))}
          </ul>
        </motion.div>

        <p className="relative text-[11px] text-gray-600 mt-auto">&copy; {new Date().getFullYear()} Evara AI · All rights reserved</p>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="w-full max-w-sm"
        >
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-cta-400 via-brand-500 to-brand-700 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" strokeWidth={2} />
            </div>
            <span className="font-display font-bold text-gray-900 text-sm">Evara AI</span>
          </div>

          <h2 className="font-display text-[26px] font-semibold text-gray-900 tracking-tight">Sign in to your workspace</h2>
          <p className="text-sm text-gray-500 mt-1.5">
            Don't have an account?{" "}
            <Link to="/register" className="link">
              Create one free
            </Link>
          </p>

          <div className="card shadow-modal p-7 mt-7">
            <GoogleSignInButton
              intent="signin"
              onSignedIn={(session) => {
                applySession(session);
                navigate("/dashboard", { replace: true });
              }}
            />

            <form onSubmit={handleSubmit} noValidate className="space-y-4 mt-4">
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
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="password" className="label mb-0">Password</label>
                  <Link to="/forgot-password" className="text-xs text-brand-600 hover:underline">
                    Forgot password?
                  </Link>
                </div>
                <PasswordInput
                  id="password"
                  value={password}
                  onChange={setPassword}
                  autoComplete="current-password"
                />
              </div>

              {error && (
                <div role="alert" aria-live="polite" className="rounded-xl bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-600 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
                  {error}
                </div>
              )}

              {/* The halo is the reference's signature CTA treatment — reserved
                  for the one button that completes the page's purpose. */}
              <div className="glow-ring">
                <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-3">
                  {loading ? "Signing in…" : "Sign in"}
                </button>
              </div>
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
