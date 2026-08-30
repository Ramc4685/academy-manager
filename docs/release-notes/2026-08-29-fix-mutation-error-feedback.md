# mutation-error-feedback

PR: #568

## What changed
There was no global mutation error handler: the QueryClient configured
only query defaults, and 28 `useMutation` sites across admin/coach/
parent neither defined `onError` nor rendered `isError` (`#509`). A
409/500 or the 20s client abort was swallowed and the UI silently
reverted to idle — a failed pause approval, payroll generation, or
session cancel looked like success. This adds a `MutationCache`
`onError` default in `frontend/lib/providers.tsx` that pushes a sticky
error toast through the `ds/toast` ToastProvider (now also mounted in
the admin and coach layouts), skipping mutations that have their own
contextual `onError` and honoring a `meta.suppressGlobalError` opt-out.
The three raw `.then()` calls on the admin session detail page (resume
enrollment, skip/remove waitlist entry) became proper mutations, and
the sessions-list Cancel button now disables while its delete mutation
is pending (the `#467` site). A 12-test vitest suite pins the toast
routing, error-message mapping, and the no-double-toast rule.

## Deploy notes
Frontend-only; no backend, schema, or API changes. Nothing to run —
ships with the normal frontend deploy. Error toasts are sticky by
design (require dismissal), matching existing ToastProvider behavior.

## Risk / rollback
Purely additive feedback path: mutations behave exactly as before, they
just report failures now. The main risk is a duplicate toast if a
future mutation both renders `isError` inline and lacks `onError` —
cosmetic, and suppressible per-mutation via `meta.suppressGlobalError`.
Rollback is a straight revert of the merge; no data or state to unwind.
