"use client";

/**
 * The landing page for the unsubscribe link in every digest and campaign (#555).
 *
 * Login-less on purpose: a recipient who wants out must not have to remember a
 * password first, and CAN-SPAM/CASL want the opt-out reachable from the message
 * itself. The HMAC token in `?t=` is the entire authority.
 *
 * Nothing mutates on load. The page previews the current state with a POST and
 * waits for a click — a GET (or an auto-submit on mount) would let a corporate
 * mail scanner's link prefetch unsubscribe families without anyone asking.
 *
 * Transactional mail — invoices, dunning notices, login links — is deliberately
 * absent from the form. It is not something a recipient can switch off, and the
 * backend rejects the key rather than ignoring it, so nobody can leave here
 * believing they turned off their own invoices.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import type { ApiError } from "@/lib/api/client";
import { brand } from "@/lib/brand";
import { confirmUnsubscribe, previewUnsubscribe } from "@/lib/api/unsubscribe";

type Status = "loading" | "ready" | "saving" | "saved" | "invalid" | "unavailable" | "error";

const CARD =
  "mt-6 rounded-xl border border-slate-200 bg-white p-6 text-left shadow-sm";
const BUTTON =
  "mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 " +
  "text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60";
const LINK =
  "mt-6 inline-flex items-center justify-center rounded-lg bg-slate-900 px-5 py-2.5 " +
  "text-sm font-semibold text-white transition hover:bg-slate-800";

function statusFor(err: unknown): Status {
  const code = (err as ApiError).status;
  // 401 = forged, tampered, or minted for another academy. 400 = the host did
  // not resolve to an academy. 404 = no signing secret on this deployment, so
  // no link we minted could have led here. All three are "this link cannot be
  // used", and the backend deliberately does not say which.
  if (code === 401 || code === 400) return "invalid";
  if (code === 404) return "unavailable";
  return "error";
}

function UnsubscribeContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("t");

  const [status, setStatus] = useState<Status>("loading");
  const [campaigns, setCampaigns] = useState(true);
  const [digests, setDigests] = useState(false);
  const [notifications, setNotifications] = useState(false);

  useEffect(() => {
    if (!token) {
      setStatus("invalid");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const state = await previewUnsubscribe(token);
        if (cancelled) return;
        // Pre-tick "campaigns" only for a recipient who has never switched
        // anything off: they clicked Unsubscribe, so that is the choice they
        // came to make, and one click confirms it. Anyone with an existing
        // choice sees exactly what they already chose — with three categories,
        // inferring from one of them would silently re-tick another.
        const untouched =
          !state.campaigns_opted_out && !state.digests_opted_out && !state.notifications_opted_out;
        setCampaigns(untouched ? true : state.campaigns_opted_out);
        setDigests(state.digests_opted_out);
        setNotifications(state.notifications_opted_out);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setStatus(statusFor(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const save = useCallback(async () => {
    if (!token) return;
    setStatus("saving");
    try {
      const state = await confirmUnsubscribe(token, { campaigns, digests, notifications });
      setCampaigns(state.campaigns_opted_out);
      setDigests(state.digests_opted_out);
      setNotifications(state.notifications_opted_out);
      setStatus("saved");
    } catch (err) {
      setStatus(statusFor(err));
    }
  }, [token, campaigns, digests, notifications]);

  const nothingSelected = !campaigns && !digests && !notifications;

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
              Loading your email preferences&hellip;
            </h1>
          </div>
        ) : null}

        {status === "ready" || status === "saving" ? (
          <div className={CARD}>
            <h1 className="font-display text-2xl font-bold text-slate-900">Email preferences</h1>
            <p className="mt-2 text-sm text-slate-600">
              Choose what you no longer want to receive. You can come back to this link any
              time to turn them back on.
            </p>

            <label className="mt-6 flex items-start gap-3 text-sm text-slate-800">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-slate-300"
                checked={campaigns}
                onChange={(e) => setCampaigns(e.target.checked)}
              />
              <span>
                <span className="font-medium">Announcements and updates</span>
                <span className="block text-slate-600">
                  News, camps, and other messages from your academy.
                </span>
              </span>
            </label>

            <label className="mt-4 flex items-start gap-3 text-sm text-slate-800">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-slate-300"
                checked={digests}
                onChange={(e) => setDigests(e.target.checked)}
              />
              <span>
                <span className="font-medium">Daily summary emails</span>
                <span className="block text-slate-600">
                  The daily rundown of sessions and progress.
                </span>
              </span>
            </label>

            <label className="mt-4 flex items-start gap-3 text-sm text-slate-800">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-slate-300"
                checked={notifications}
                onChange={(e) => setNotifications(e.target.checked)}
              />
              <span>
                <span className="font-medium">Roster change alerts</span>
                <span className="block text-slate-600">
                  Emails to coaches and staff when a student joins, moves, or leaves a class.
                </span>
              </span>
            </label>

            <p className="mt-4 text-xs text-slate-500">
              Receipts, invoices, and account or sign-in emails are always sent — they are
              not marketing, and turning them off would mean missing a payment.
            </p>

            <button type="button" className={BUTTON} onClick={save} disabled={status === "saving"}>
              {status === "saving"
                ? "Saving…"
                : nothingSelected
                  ? "Keep receiving all emails"
                  : "Save my preferences"}
            </button>
          </div>
        ) : null}

        {status === "saved" ? (
          <div className={CARD} role="status" aria-live="polite">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              {campaigns || digests || notifications
                ? "You're unsubscribed"
                : "You're still subscribed"}
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              {campaigns || digests || notifications
                ? "We've saved your choices. It can take a little while for anything already on its way to stop."
                : "No changes — you'll keep receiving these emails."}
            </p>
            <p className="mt-4 text-xs text-slate-500">
              Changed your mind? Reopen this link from any email to adjust it again.
            </p>
          </div>
        ) : null}

        {status === "invalid" ? (
          <div className="mt-6" role="alert">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              This link isn&rsquo;t valid
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              It may have been altered in transit, or it belongs to a different academy. Open
              the link straight from the email, or sign in to change your preferences.
            </p>
            <Link href="/login" className={LINK}>
              Go to sign in
            </Link>
          </div>
        ) : null}

        {status === "unavailable" ? (
          <div className="mt-6" role="alert">
            <h1 className="font-display text-2xl font-bold text-slate-900">
              Email preferences aren&rsquo;t available here
            </h1>
            <p className="mt-2 text-sm text-slate-600">
              Sign in to manage your emails, or reply to any message from your academy and
              ask them to stop.
            </p>
            <Link href="/login" className={LINK}>
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
              We couldn&rsquo;t update your preferences just now. Please try the link again in a
              few minutes.
            </p>
            <Link href="/login" className={LINK}>
              Go to sign in
            </Link>
          </div>
        ) : null}
      </div>
    </main>
  );
}

export default function UnsubscribePage() {
  return (
    <Suspense fallback={null}>
      <UnsubscribeContent />
    </Suspense>
  );
}
