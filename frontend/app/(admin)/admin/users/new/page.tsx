import { redirect } from "next/navigation";

/**
 * Adding a user happens in the Users directory's own dialog.
 *
 * Issue #839: this page was a second add-user form with different fields and a
 * different flow from the dialog sitting one click away, so "Add user" meant
 * two different things depending on how you got here. `/admin/users/new` is
 * forwarded by `RETIRED_ROUTE_REDIRECTS` in `next.config.ts`, which is matched
 * before route resolution (the `(admin)` layout never renders — see #689 and
 * #827). This file stays as the fallback for any request that reaches route
 * resolution anyway, and so the route-manifest equality test still passes.
 */
export default function NewAdminUserPage() {
  redirect("/admin/users?add=1");
}
