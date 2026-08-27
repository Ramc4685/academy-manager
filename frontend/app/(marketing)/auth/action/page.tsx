"use client";

/**
 * In-app Firebase auth action handler.
 *
 * Login invites used to send parents to the Firebase project's own hosted page
 * (`https://<project>.firebaseapp.com/__/auth/action?...`): unbranded, and the
 * same host for every academy. The backend now re-hosts that link here on the
 * parent's own academy domain (see
 * `backend/v2/shared/tenancy/firebase_action_link.py`), so this page receives
 * the untouched `mode` / `oobCode` query and redeems the code itself.
 *
 * Completing the reset keeps Firebase's `emailVerified=true` side effect —
 * `confirmPasswordResetValue` calls the same Identity Toolkit endpoint the
 * hosted page did. Password sign-in depends on that flag; see
 * `_require_verified_password_provider_email` in the identity context.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { confirmPasswordResetValue, verifyPasswordResetCodeValue } from "@/lib/auth/firebase";
import { toAuthErrorMessage } from "@/lib/auth/auth-error";
import { safeContinuePath } from "@/lib/auth/continue-url";
import { brand } from "@/lib/brand";

const MIN_PASSWORD_LENGTH = 8;

type Status = "verifying" | "ready" | "submitting" | "done" | "expired" | "invalid" | "unsupported";

function errorCode(err: unknown): string | undefined {
  if (err && typeof err === "object" && "code" in err) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return undefined;
}

function AuthActionContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<Status>("verifying");
  const [email, setEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mode = searchParams.get("mode");
  const oobCode = searchParams.get("oobCode");

  useEffect(() => {
    if (mode !== "resetPassword") {
      setStatus("unsupported");
      return;
    }
    if (!oobCode) {
      setStatus("invalid");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const verifiedEmail = await verifyPasswordResetCodeValue(oobCode);
        if (cancelled) return;
        setEmail(verifiedEmail);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setStatus(errorCode(err) === "auth/expired-action-code" ? "expired" : "invalid");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [mode, oobCode]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirmPassword) {
      setError("Those passwords do not match.");
      return;
    }
    if (!oobCode) {
      setStatus("invalid");
      return;
    }

    setStatus("submitting");
    try {
      await confirmPasswordResetValue(oobCode, password);
      setStatus("done");
      // Firebase stamps `continueUrl` from the ActionCodeSettings the backend
      // sent, which points at this same academy — but validate it anyway.
      const next = safeContinuePath(searchParams.get("continueUrl"), window.location.origin);
      router.replace(next as Parameters<typeof router.replace>[0]);
    } catch (err) {
      const code = errorCode(err);
      if (code === "auth/expired-action-code") {
        setStatus("expired");
        return;
      }
      if (code === "auth/invalid-action-code") {
        setStatus("invalid");
        return;
      }
      setStatus("ready");
      setError(toAuthErrorMessage(err, "We could not set your password. Please try again."));
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-slate-50 p-6 font-body text-slate-950">
      <div className="w-full max-w-md">
        <p className="text-center font-display text-sm font-semibold uppercase tracking-wide text-slate-500">
          {brand.productName}
        </p>

        {status === "verifying" ? (
          <div className="mt-6 text-center" role="status" aria-live="polite">
            <span
              aria-hidden="true"
              className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900"
            />
            <h1 className="mt-6 font-display text-2xl font-bold text-slate-900">
              Checking your link&hellip;
            </h1>
          </div>
        ) : null}

        {status === "ready" || status === "submitting" ? (
          <div className="mt-6">
            <h1 className="font-display text-3xl font-bold text-slate-900">Set your password</h1>
            <p className="mt-2 text-sm text-slate-600">
              {email ? (
                <>
                  Choose a password for <span className="font-medium">{email}</span>.
                </>
              ) : (
                "Choose a password for your account."
              )}
            </p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5" data-testid="reset-form">
              <PasswordField
                id="new-password"
                label="New password"
                autoComplete="new-password"
                value={password}
                onChange={setPassword}
              />
              <PasswordField
                id="confirm-password"
                label="Confirm password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={setConfirmPassword}
              />

              {error ? (
                <p
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700"
                >
                  {error}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={status === "submitting"}
                data-testid="reset-submit"
                className="flex min-h-touch w-full items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {status === "submitting" ? "Saving..." : "Set password and sign in"}
              </button>
            </form>
          </div>
        ) : null}

        {status === "done" ? (
          <div className="mt-6 text-center" role="status" aria-live="polite">
            <h1 className="font-display text-2xl font-bold text-slate-900">Password saved</h1>
            <p className="mt-2 text-sm text-slate-600">Taking you to your portal&hellip;</p>
          </div>
        ) : null}

        {status === "expired" ? (
          <Dead
            title="This link has expired"
            body="Password links are valid for a limited time. Use Forgot password on the sign-in page with your email address to get a new one."
          />
        ) : null}

        {status === "invalid" ? (
          <Dead
            title="This link isn’t valid"
            body="It may have already been used. Use Forgot password on the sign-in page to get a new link."
          />
        ) : null}

        {status === "unsupported" ? (
          <Dead
            title="We can’t handle this link"
            body="This link is not a password link. Sign in to continue, or ask your academy to send a new invite."
          />
        ) : null}
      </div>
    </main>
  );
}

function Dead({ title, body }: { title: string; body: string }) {
  return (
    <div className="mt-6 text-center" role="alert">
      <h1 className="font-display text-2xl font-bold text-slate-900">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
      <Link
        href="/login"
        className="mt-6 inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
      >
        Go to sign in
      </Link>
    </div>
  );
}

function PasswordField({
  id,
  label,
  autoComplete,
  value,
  onChange,
}: {
  id: string;
  label: string;
  autoComplete: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        name={id}
        type="password"
        autoComplete={autoComplete}
        required
        minLength={MIN_PASSWORD_LENGTH}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="••••••••"
        data-testid={id}
        className="mt-1.5 min-h-touch w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-900 shadow-sm transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"
      />
    </div>
  );
}

export default function AuthActionPage() {
  return (
    <Suspense fallback={null}>
      <AuthActionContent />
    </Suspense>
  );
}
