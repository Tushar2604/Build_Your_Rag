// "Continue with Google" — shared by sign-in and sign-up.
//
// One button for both, because the flow genuinely is one thing: Google tells us
// who you are, and the server either finds your account or creates one. Asking
// someone to pick "sign in" vs "sign up" before they have told us who they are
// is a choice they cannot yet answer.
//
// The button renders only where the server says Google is configured — a visible
// button that 400s is worse than no button at all.
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { TokenResponse, getAuthProviders } from "../api/auth";
import { signInWithGoogle } from "../api/oauth";
import { ApiError } from "../api/client";

interface Props {
  onSignedIn: (session: TokenResponse) => void;
  /** "signin" | "signup" — wording only; the flow behind it is identical. */
  intent?: "signin" | "signup";
  disabled?: boolean;
}

/** Google's mark, inlined so the button never waits on a network request. */
function GoogleMark() {
  return (
    <svg className="w-[18px] h-[18px]" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.96 10.71a5.41 5.41 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

export default function GoogleSignInButton({
  onSignedIn,
  intent = "signin",
  disabled = false,
}: Props) {
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // A failure here just hides the button — the password form still works, so
    // it is not worth an error message.
    getAuthProviders()
      .then((p) => setAvailable(p.google))
      .catch(() => setAvailable(false));
  }, []);

  if (!available) return null;

  async function handleClick() {
    setBusy(true);
    setError(null);
    try {
      const session = await signInWithGoogle();
      // `null` means they closed the popup or declined — an ordinary choice,
      // so the form is simply left as it was.
      if (session) onSignedIn(session);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start Google sign-in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy || disabled}
        className="w-full inline-flex items-center justify-center gap-2.5 rounded-lg border
                   border-gray-200 bg-surface px-4 py-2.5 text-sm font-medium text-gray-800
                   transition-colors hover:bg-surface-2 disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="w-[18px] h-[18px] animate-spin" strokeWidth={2} />
        ) : (
          <GoogleMark />
        )}
        {busy
          ? "Waiting for Google…"
          : intent === "signup"
            ? "Sign up with Google"
            : "Continue with Google"}
      </button>

      {error && (
        <p role="alert" className="text-xs text-red-600 text-center">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-gray-200" />
        <span className="text-[11px] uppercase tracking-wider text-gray-400">or</span>
        <span className="h-px flex-1 bg-gray-200" />
      </div>
    </div>
  );
}
