"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { registerPublicParent } from "@/lib/api/registration";
import { rememberPendingParentRegistration } from "@/lib/auth/parent-registration-continuation";
import {
  completeGoogleRedirectSignIn,
  registerWithEmail,
  sendVerificationEmail,
  signInWithGoogle,
  signOutCurrent,
} from "@/lib/auth/firebase";
import type { User } from "@/lib/auth/firebase";
import {
  existingAccountEmailFromCredentialConflict,
  isEmailAlreadyInUseError,
  toAuthErrorMessage,
} from "@/lib/auth/auth-error";
import { brand } from "@/lib/brand";

const HERO_IMAGE =
  "https://static.prod-images.emergentagent.com/jobs/c735a2b3-2fb1-4fa5-a75c-2007226ca62e/images/1d1cfafe28a9d8df9f22f211189ef097f1bb5d348846857bdee5ba711ec35327.png";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingVerificationUser, setPendingVerificationUser] =
    useState<User | null>(null);
  const [verificationLoading, setVerificationLoading] = useState(false);

  useEffect(() => {
    setHydrated(true);
    let cancelled = false;

    completeGoogleRedirectSignIn()
      .then(async (user) => {
        if (!cancelled && user) {
          await registerPublicParent();
          if (!cancelled) {
            router.push("/parent/onboarding");
          }
        }
      })
      .catch((err) => {
        if (!cancelled && !redirectToLoginOnGoogleConflict(err)) {
          setError(toAuthErrorMessage(err, "Google registration failed."));
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function finishParentRegistration() {
    await registerPublicParent();
    router.push("/parent/onboarding");
  }

  /**
   * A Google attempt on an email that already has a password account throws
   * `auth/account-exists-with-different-credential`. Send the parent to
   * sign-in (email prefilled when Firebase provides it) instead of leaving
   * them stuck on the register form.
   */
  function redirectToLoginOnGoogleConflict(err: unknown): boolean {
    const existingEmail = existingAccountEmailFromCredentialConflict(err);
    if (existingEmail === null) return false;
    router.push(existingEmail ? `/login?email=${encodeURIComponent(existingEmail)}` : "/login");
    return true;
  }

  async function handleGoogle() {
    setGoogleLoading(true);
    setError(null);
    setNotice(null);
    setPendingVerificationUser(null);
    try {
      const user = await signInWithGoogle();
      if (user) await finishParentRegistration();
    } catch (err) {
      if (redirectToLoginOnGoogleConflict(err)) return;
      setError(toAuthErrorMessage(err, "Google registration failed."));
    } finally {
      setGoogleLoading(false);
    }
  }

  async function handleEmailSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setNotice(null);
    setPendingVerificationUser(null);
    const trimmedEmail = email.trim();
    try {
      const user = await registerWithEmail(trimmedEmail, password);
      rememberPendingParentRegistration(trimmedEmail);
      setPassword("");
      await sendVerificationAndSignOut(user);
    } catch (err) {
      if (isEmailAlreadyInUseError(err)) {
        router.push(`/login?email=${encodeURIComponent(trimmedEmail)}`);
        return;
      }
      setError(toAuthErrorMessage(err, "Registration failed. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  async function sendVerificationAndSignOut(user: User) {
    try {
      await sendVerificationEmail(user);
    } catch {
      setPendingVerificationUser(user);
      setNotice(
        "Account created, but we could not send the verification email. Try sending it again below."
      );
      return;
    }

    setPendingVerificationUser(null);
    setNotice("Verification email sent. Confirm your email, then sign in to continue registration.");
    try {
      await signOutCurrent();
    } catch {
      // The account and verification email are already complete; sign-out is best effort.
    }
  }

  async function handleResendVerification() {
    if (!pendingVerificationUser) return;
    setVerificationLoading(true);
    setError(null);
    try {
      await sendVerificationAndSignOut(pendingVerificationUser);
    } catch (err) {
      setError(toAuthErrorMessage(err, "Verification email could not be sent. Please try again."));
    } finally {
      setVerificationLoading(false);
    }
  }

  const busy = !hydrated || loading || googleLoading || verificationLoading;

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
                Start your child&apos;s academy journey.{" "}
                <span className="text-yellow-400">Built for serious training.</span>
              </h1>
              <p className="mt-4 max-w-md leading-relaxed text-white/80">
                Register, choose a session, and manage payments from one parent portal.
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
                Register your child
              </h2>
              <p className="mt-2 text-sm text-slate-600">
                Continue with Google for the fastest setup. Email signup requires verification before onboarding.
              </p>
            </div>

            <button
              type="button"
              disabled={busy}
              onClick={handleGoogle}
              data-testid="register-google"
              className="mt-8 flex min-h-touch w-full items-center justify-center gap-3 rounded-md border border-blue-700 bg-blue-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="flex size-6 items-center justify-center rounded-full bg-white text-sm font-bold text-blue-700">
                G
              </span>
              <span>{googleLoading ? "Connecting..." : "Continue with Google"}</span>
              {!googleLoading && (
                <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] uppercase">
                  Recommended
                </span>
              )}
            </button>

            <div className="mt-5 flex items-center gap-3 text-xs uppercase text-slate-400">
              <div className="h-px flex-1 bg-slate-200" />
              <span>Email option</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>

            <form onSubmit={handleEmailSubmit} className="mt-5 space-y-5" data-testid="register-form">
              <Field
                id="email"
                label="Email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={setEmail}
              />
              <Field
                id="password"
                label="Password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={password}
                onChange={setPassword}
                minLength={8}
              />

              {notice ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
                  <p role="status">{notice}</p>
                  {pendingVerificationUser ? (
                    <button
                      type="button"
                      onClick={handleResendVerification}
                      disabled={busy}
                      className="mt-3 rounded-md border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {verificationLoading ? "Sending..." : "Send verification email"}
                    </button>
                  ) : null}
                </div>
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
                data-testid="register-submit"
                className="flex min-h-touch w-full items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Creating account..." : "Create account"}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-slate-600">
              Already registered?{" "}
              <Link
                href="/login"
                className="font-medium text-blue-600 transition hover:underline"
              >
                Sign in
              </Link>
            </p>
          </div>
        </section>
      </div>
    </main>
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
  minLength,
}: {
  id: string;
  label: string;
  type: string;
  autoComplete: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  minLength?: number;
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
        minLength={minLength}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-testid={`register-${id}`}
        className="mt-1.5 min-h-touch w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-900 shadow-sm transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"
      />
    </div>
  );
}
