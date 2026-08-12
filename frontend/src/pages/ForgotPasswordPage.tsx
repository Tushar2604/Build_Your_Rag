// Request a password reset link.
//
// The response is intentionally identical whether or not the address has an
// account — the server will not confirm which emails are registered, and this
// page must not either. So the success copy says "if that email has an
// account", not "check your inbox".
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowLeft, MailCheck } from "lucide-react";

import { forgotPassword } from "../api/auth";
import { ApiError } from "../api/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<{ detail: string; emailSent: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (sending || !email.trim()) return;
    setSending(true);
    setError(null);
    try {
      const result = await forgotPassword(email.trim());
      setSent({ detail: result.detail, emailSent: result.email_sent });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the reset link.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 aurora-shell">
      <div className="card w-full max-w-md p-8">
        <Link
          to="/login"
          className="inline-flex items-center gap-1.5 text-[13px] text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="w-4 h-4" strokeWidth={2} />
          Back to sign in
        </Link>

        {sent ? (
          <div className="text-center py-4">
            <MailCheck className="w-10 h-10 mx-auto text-emerald-600 mb-3" strokeWidth={1.5} />
            <h1 className="section-title mb-2">Check your email</h1>
            <p className="text-sm text-gray-600">{sent.detail}</p>
            {!sent.emailSent && (
              <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                This server has no email provider configured, so the link could not actually be
                delivered. An administrator needs to set <code>RESEND_API_KEY</code>.
              </p>
            )}
          </div>
        ) : (
          <>
            <h1 className="section-title">Forgot your password?</h1>
            <p className="text-sm text-gray-500 mt-1 mb-5">
              Enter your email and we'll send a link to choose a new one.
            </p>
            <form onSubmit={submit} className="space-y-4" noValidate>
              <div>
                <label htmlFor="email" className="label">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  spellCheck={false}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input"
                  placeholder="you@company.com"
                />
              </div>

              {error && (
                <div
                  role="alert"
                  className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-start gap-2"
                >
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" strokeWidth={2} />
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={sending || !email.trim()}
                className="btn-primary w-full disabled:opacity-50"
              >
                {sending ? "Sending…" : "Send reset link"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
