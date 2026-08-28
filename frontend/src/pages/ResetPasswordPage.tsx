// Choose a new password from an emailed reset link.
//
// A successful reset signs the user straight in via `applySession` — the same
// path used after accepting a team invite. Bouncing someone who has just proved
// control of their mailbox back to a login form, to retype the password they
// set two seconds ago, is friction with nothing behind it.
import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, ArrowLeft } from "lucide-react";

import { resetPassword } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../store/auth";
import PasswordInput from "../components/PasswordInput";

const MIN_LENGTH = 8;

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
  const { applySession } = useAuth();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_LENGTH;
  const mismatch = confirm.length > 0 && password !== confirm;
  const canSubmit = password.length >= MIN_LENGTH && password === confirm && !saving;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      applySession(await resetPassword(token, password));
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reset the password.");
      setSaving(false);
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 aurora-shell">
        <div className="card w-full max-w-md p-8 text-center">
          <h1 className="section-title mb-2">This link is incomplete</h1>
          <p className="text-sm text-gray-600 mb-5">
            Open the link from your email directly, or request a new one.
          </p>
          <Link to="/forgot-password" className="btn-primary">
            Request a new link
          </Link>
        </div>
      </div>
    );
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

        <h1 className="section-title">Choose a new password</h1>
        <p className="text-sm text-gray-500 mt-1 mb-5">
          At least {MIN_LENGTH} characters. You'll be signed in once it's saved.
        </p>

        <form onSubmit={submit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="password" className="label">
              New password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              minLength={MIN_LENGTH}
              placeholder={`Min. ${MIN_LENGTH} characters`}
            />
            {tooShort && (
              <p className="text-xs text-amber-700 mt-1">
                {MIN_LENGTH - password.length} more character
                {MIN_LENGTH - password.length === 1 ? "" : "s"} needed.
              </p>
            )}
          </div>

          <div>
            <label htmlFor="confirm" className="label">
              Confirm password
            </label>
            <PasswordInput
              id="confirm"
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
              placeholder="Type it again"
            />
            {mismatch && <p className="text-xs text-red-600 mt-1">These do not match.</p>}
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

          <button type="submit" disabled={!canSubmit} className="btn-primary w-full disabled:opacity-50">
            {saving ? "Saving…" : "Set password and sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
