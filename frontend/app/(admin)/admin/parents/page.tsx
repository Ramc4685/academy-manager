import { redirect } from "next/navigation";

/**
 * Parents live under Families (sidebar regroup PR 3). The Staff directory at
 * `/admin/users` lists coaches and admins only.
 *
 * `/admin/parents` is forwarded by `RETIRED_ROUTE_REDIRECTS` in
 * `next.config.ts`, which is matched before route resolution — rendering the
 * `(admin)` layout just to throw a redirect signal is what tripped the
 * Cloudflare Workers resource ceiling (#689, #827). This file stays as the
 * fallback for any request that reaches route resolution anyway, and so the
 * route-manifest equality test still passes.
 */
export default function AdminParentsPage() {
  redirect("/admin/families");
}
