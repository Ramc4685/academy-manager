"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { consumeMagicLink } from "@/lib/api/magic-link";
import { signInWithCustomTokenValue } from "@/lib/auth/firebase";
import type { ApiError } from "@/lib/api/client";
import { brand } from "@/lib/brand";

type Status = "loading" | "expired" | "invalid" | "error";

function isSameSitePath(path: string): boolean {
  // Mirror the backend's open-redirect guard: only a single-slash absolute path.
  return path.startsWith("/") && !path.startsWith("//");
}

function MagicLinkContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<Status>("loading");
  // A magic link is single-use, so the consume call must fire exactly once even
  // if React re-runs the effect (dev strict mode). Without this guard a second
  // POST would 401 and wrongly show "invalid" after a successful first redeem.
  const consumed = useRef(false);

  useEffect(() => {
    if (consumed.current) return;
    consumed.current = true;

    const token = searchParams.get("t");
    if (!token) {
      setStatus("invalid");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const { custom_token, next_path } = await consumeMagicLink(token);
        await signInWithCustomTokenValue(custom_token);
        if (cancelled) return;
        const target = isSameSitePath(next_path) ? next_path : "/parent/dashboard";
        router.replace(target as Parameters<typeof router.replace>[0]);
      } catch (err) {
        if (cancelled) return;
        const status_code = (err as ApiError).status;
        if (status_code === 410) setStatus("expired");
        else if (status_code === 401) setStatus("invalid");
        else setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, searchParams]);

  return (
    <main className="grid min-h-dvh place-items-center bg-slate-50 p-6 font-body text-slate-950">
      <div className="w-full max-w-md text-center">
        <p className="font-display text-sm font-semibold uppercase tracking-wide text-slate-500">
          {brand.productName}
        </p>

        {status === "loading" ? (
          <div className="mt-6" role="status" aria-live="polite">
            <span
              aria-hidden="true"
              className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900"
            />
            <h1 className="mt-6 font-display text-2xl font-bold text-slate-900">
              Signing you in&hellip;
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              Hold on while we open your parent portal.
            </p>
          </div>
        ) : null}

        {status === "expired" ? (
          <div className="mt-6" role="alert">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              This link has expired
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              Magic links are valid for a limited time. Sign in and use{" "}
              <span className="font-medium">Forgot password</span> to get back into your
              account.
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Go to sign in
            </Link>
          </div>
        ) : null}

        {status === "invalid" ? (
          <div className="mt-6" role="alert">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              This link isn&rsquo;t valid
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              It may have already been used or isn&rsquo;t recognized. Sign in to continue.
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Go to sign in
            </Link>
          </div>
        ) : null}

        {status === "error" ? (
          <div className="mt-6" role="alert">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              Something went wrong
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              We couldn&rsquo;t sign you in just now. Please try again, or sign in with your
              email.
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Go to sign in
            </Link>
          </div>
        ) : null}
      </div>
    </main>
  );
}

export default function MagicLinkPage() {
  return (
    <Suspense fallback={null}>
      <MagicLinkContent />
    </Suspense>
  );
}
