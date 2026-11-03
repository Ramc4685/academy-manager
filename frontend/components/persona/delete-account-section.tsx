"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { requestAccountDeletion } from "@/lib/api/me";
import { toAuthErrorMessage } from "@/lib/auth/auth-error";
import {
  reauthMethods,
  reauthenticate,
  signOutCurrent,
  type ReauthMethod,
} from "@/lib/auth/firebase";
import { clearPersistedQueryCache } from "@/lib/query/persistence";

const CONFIRM_WORD = "DELETE";

const METHOD_LABEL: Record<Exclude<ReauthMethod, "password">, string> = {
  google: "Confirm with Google",
  apple: "Confirm with Apple",
};

/** Turn a failed deletion into a sentence the person can act on. */
export function deletionErrorMessage(err: unknown): string {
  const code = (err as { code?: unknown } | null)?.code;
  if (code === "Identity.RecentSignInRequired") {
    return "For your security, sign out, sign back in, and delete your account within 5 minutes.";
  }
  if (code === "Identity.CannotRemoveLastOwner" || code === "Identity.CoachHasFutureSessions") {
    return err instanceof Error && err.message ? err.message : "This account cannot be deleted yet.";
  }
  return toAuthErrorMessage(err, "Your account could not be deleted. Please try again.");
}

/**
 * In-app account deletion (Apple 5.1.1(v), Google Play). Shared by every
 * persona's profile. The person signs in again, types DELETE, and is signed
 * out on success; the backend locks the account everywhere at once.
 */
export function DeleteAccountSection() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [methods, setMethods] = useState<ReauthMethod[]>([]);
  const [password, setPassword] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setMethods(reauthMethods());
  }, [open]);

  const confirmed = typed.trim().toUpperCase() === CONFIRM_WORD;
  const usesPassword = methods.includes("password");

  async function handleDelete(method: ReauthMethod | null) {
    if (busy || !confirmed) return;
    setBusy(true);
    setError(null);
    try {
      // No method we can offer here (e.g. an Apple-only account in a browser):
      // a recent sign-in still passes the backend's check on its own.
      if (method) await reauthenticate(method, password);
      await requestAccountDeletion();
      await signOutCurrent();
      queryClient.clear();
      clearPersistedQueryCache();
      // Full load: the persona guard's soft redirect to bare /login on sign-out
      // otherwise wins the race and drops the notice.
      window.location.replace("/login?deleted=1");
    } catch (err) {
      setError(deletionErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="delete-account"
      className="rounded-2xl border border-status-red-200 bg-white p-4"
    >
      <h2 className="font-semibold text-rally-ink">Delete account</h2>
      {!open ? (
        <>
          <p className="mt-1 text-sm text-rally-muted">
            Permanently close your account in every academy you belong to.
          </p>
          <button
            type="button"
            data-testid="delete-account-open"
            onClick={() => setOpen(true)}
            className="mt-3 min-h-touch rounded-lg border border-status-red-200 px-4 text-sm font-semibold text-status-red-800 hover:bg-status-red-50"
          >
            Delete my account
          </button>
        </>
      ) : (
        <div className="mt-2 space-y-3 text-sm text-rally-ink">
          <ul className="list-disc space-y-1 pl-5">
            <li>You are signed out right away and cannot sign in again, in any academy.</li>
            <li>
              After 14 days your personal details are removed. Until then, the academy can restore
              the account if you ask them.
            </li>
            <li>
              Invoices and payment records are kept for 7 years, as tax law requires. Any balance
              you owe stays with the academy.
            </li>
          </ul>

          {usesPassword && (
            <div>
              <label htmlFor="delete-account-password" className="block text-xs font-semibold text-rally-muted">
                Your password
              </label>
              <input
                id="delete-account-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-lg border border-rally-line px-3 py-2 text-sm"
              />
            </div>
          )}

          <div>
            <label htmlFor="delete-account-confirm" className="block text-xs font-semibold text-rally-muted">
              Type {CONFIRM_WORD} to confirm
            </label>
            <input
              id="delete-account-confirm"
              data-testid="delete-account-confirm"
              type="text"
              autoCapitalize="characters"
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="mt-1 w-full rounded-lg border border-rally-line px-3 py-2 text-sm"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-status-red-600">
              {error}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {usesPassword || methods.length === 0 ? (
              <button
                type="button"
                data-testid="delete-account-submit"
                disabled={!confirmed || busy || (usesPassword && !password)}
                onClick={() => void handleDelete(usesPassword ? "password" : null)}
                className="min-h-touch rounded-lg bg-status-red-600 px-4 text-sm font-semibold text-white hover:bg-status-red-800 disabled:opacity-50"
              >
                {busy ? "Deleting…" : "Delete my account"}
              </button>
            ) : (
              methods.map((method) => (
                <button
                  key={method}
                  type="button"
                  data-testid={`delete-account-${method}`}
                  disabled={!confirmed || busy}
                  onClick={() => void handleDelete(method)}
                  className="min-h-touch rounded-lg bg-status-red-600 px-4 text-sm font-semibold text-white hover:bg-status-red-800 disabled:opacity-50"
                >
                  {busy ? "Deleting…" : METHOD_LABEL[method as Exclude<ReauthMethod, "password">]}
                </button>
              ))
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                setTyped("");
                setPassword("");
                setError(null);
              }}
              className="min-h-touch rounded-lg border border-rally-line px-4 text-sm font-medium text-rally-ink disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
