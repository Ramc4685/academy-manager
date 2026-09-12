import { redirect } from "next/navigation";

/**
 * The Dues follow-up page was removed with Month close (spec §6). Its buckets,
 * reminders and WhatsApp link all live on Payments now, and the tuition
 * discount card moved to Month close.
 *
 * `/admin/reports/dues` is forwarded by `RETIRED_ROUTE_REDIRECTS` in
 * `next.config.ts`, which is matched before route resolution — rendering the
 * `(admin)` layout just to throw a redirect signal is what tripped the
 * Cloudflare Workers resource ceiling (#689). This file stays as the fallback
 * for any request that reaches route resolution anyway, and so the
 * route-manifest equality test still passes.
 */
export default function AdminDuesFollowupRedirectPage() {
  redirect("/admin/payments");
}
