"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import {
  completeGoogleRedirectSignIn,
  sendPasswordReset,
  signInWithEmail,
  signInWithGoogle,
  signOutCurrent,
} from "@/lib/auth/firebase";
import { toAuthErrorMessage } from "@/lib/auth/auth-error";
import { registerPublicParent } from "@/lib/api/registration";
import {
  clearPendingParentRegistration,
  consumePendingParentRegistration,
} from "@/lib/auth/parent-registration-continuation";
import { clearBffIdentityCookie } from "@/lib/api/auth-bridge-cookie";
import { brand } from "@/lib/brand";

const HERO_IMAGE =
  "https://static.prod-images.emergentagent.com/jobs/c735a2b3-2fb1-4fa5-a75c-2007226ca62e/images/1d1cfafe28a9d8df9f22f211189ef097f1bb5d348846857bdee5ba711ec35327.png";

function LoginPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setHydrated(true);
    let cancelled = false;
    clearBffIdentityCookie();

    const prefillEmail = searchParams.get("email");
    if (prefillEmail) {
      setEmail(prefillEmail);
      setNotice("An account already exists for this email. Sign in to continue.");
    }

    completeGoogleRedirectSignIn()
      .then((user) => {
        if (!cancelled && user) {
          router.push("/post-login");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(toAuthErrorMessage(err, "Google sign-in failed. Please try again."));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleEmailSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      clearBffIdentityCookie();
      const user = await signInWithEmail(email, password);
      if (consumePendingParentRegistration(user.email)) {
        if (!user.emailVerified) {
          await signOutCurrent();
          setError("Verify your email, then sign in again to continue registration.");
          return;
        }
        await registerPublicParent();
        clearPendingParentRegistration();
        router.push("/parent/onboarding");
        return;
      }
      router.push("/post-login");
    } catch (err) {
      setError(toAuthErrorMessage(err, "Sign-in failed. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    setGoogleLoading(true);
    setError(null);
    setNotice(null);
    try {
      clearBffIdentityCookie();
      const user = await signInWithGoogle();
      if (user) router.push("/post-login");
    } catch (err) {
      setError(toAuthErrorMessage(err, "Google sign-in failed. Please try again."));
    } finally {
      setGoogleLoading(false);
    }
  }

  async function handlePasswordReset() {
    const trimmedEmail = email.trim();
    setError(null);
    setNotice(null);

    if (!trimmedEmail) {
      setError("Enter your email first, then request a password reset.");
      return;
    }

    setResetLoading(true);
    try {
      await sendPasswordReset(trimmedEmail);
      setNotice("If that email exists, we have sent a reset link.");
    } catch (err) {
      setError(toAuthErrorMessage(err, "Password reset failed. Please try again."));
    } finally {
      setResetLoading(false);
    }
  }

  const busy = !hydrated || loading || googleLoading || resetLoading;

  return (
    <main className="min-h-dvh bg-slate-50 font-body text-slate-950">
      <div className="flex min-h-dvh">
        <section className="relative hidden w-1/2 overflow-hidden bg-slate-900 lg:block">
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${HERO_IMAGE})` }}
          />
          <div className="absolute inset-0 bg-slate-900/55" />

          <div className="relative flex h-full min-h-dvh flex-col justify-between p-12 text-white">
            <BrandLockup tone="dark" />

            <div>
              <h1 className="font-display text-4xl font-bold leading-[1.05] lg:text-5xl">
                Run a premium academy.{" "}
                <span className="text-yellow-400">Powered by precision.</span>
              </h1>
              <p className="mt-4 max-w-md leading-relaxed text-white/80">
                Sessions, students, payments, payouts, attendance, and profit - all in one
                professional dashboard.
              </p>
            </div>
          </div>
        </section>

        <section className="flex flex-1 items-center justify-center bg-slate-50 p-6">
          <div className="w-full max-w-md">
            <div className="mb-8 lg:hidden">
              <BrandLockup tone="light" />
            </div>

            <div>
              <h2 className="font-display text-3xl font-bold leading-none text-slate-900 md:text-4xl">
                Sign in
              </h2>
              <p className="mt-2 text-sm text-slate-600">
                Welcome back. Enter your credentials.
              </p>
            </div>

            <form onSubmit={handleEmailSubmit} className="mt-8 space-y-5" data-testid="login-form">
              <Field
                id="email"
                label="Email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={setEmail}
              />
              <div>
                <Field
                  id="password"
                  label="Password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={setPassword}
                />
                <div className="mt-1.5 text-right">
                  <button
                    type="button"
                    className="text-xs font-medium text-blue-600 transition hover:underline focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={busy}
                    onClick={handlePasswordReset}
                  >
                    {resetLoading ? "Sending reset..." : "Forgot password?"}
                  </button>
                </div>
              </div>

              {notice ? (
                <p
                  role="status"
                  className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800"
                >
                  {notice}
                </p>
              ) : null}

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
                disabled={busy}
                data-testid="login-submit"
                className="flex min-h-touch w-full items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Signing in..." : "Sign in"}
              </button>
            </form>

            <div className="mt-5 flex items-center gap-3 text-xs uppercase text-slate-400">
              <div className="h-px flex-1 bg-slate-200" />
              <span>or</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>

            <button
              type="button"
              disabled={busy}
              onClick={handleGoogle}
              data-testid="login-google"
              className="mt-5 flex min-h-touch w-full items-center justify-center rounded-md border border-slate-200 bg-white px-4 text-sm font-medium text-slate-800 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {googleLoading ? "Connecting..." : "Continue with Google"}
            </button>

            <p className="mt-6 text-center text-sm text-slate-600">
              New parent?{" "}
              <Link
                href="/register"
                className="font-medium text-blue-600 transition hover:underline"
                data-testid="link-register"
              >
                Register your child →
              </Link>
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageContent />
    </Suspense>
  );
}

function BrandLockup({ tone }: { tone: "dark" | "light" }) {
  const text = tone === "dark" ? "text-white" : "text-slate-900";
  const subtext = tone === "dark" ? "text-white/70" : "text-slate-500";

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-yellow-400 font-display text-xl font-bold text-slate-900">
        B
      </div>
      <div>
        <div className={`font-display text-lg font-bold leading-6 ${text}`}>
          {brand.productName}
        </div>
        <div className={`text-[11px] uppercase ${subtext}`}>
          {brand.companyName}
        </div>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  type,
  autoComplete,
  placeholder,
  value,
  onChange,
}: {
  id: string;
  label: string;
  type: string;
  autoComplete: string;
  placeholder: string;
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
        type={type}
        autoComplete={autoComplete}
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-testid={`login-${id}`}
        className="mt-1.5 min-h-touch w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-900 shadow-sm transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"
      />
    </div>
  );
}
