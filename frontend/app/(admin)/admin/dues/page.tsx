import { redirect } from "next/navigation";

/**
 * The Dues page was removed with Month close (spec §6). Payments owns chasing
 * balances now; the WhatsApp link moved onto the Past due and Awaiting rows.
 *
 * `/admin/dues` is forwarded by `RETIRED_ROUTE_REDIRECTS` in `next.config.ts`,
 * which is matched before route resolution — rendering the `(admin)` layout
 * just to throw a redirect signal is what tripped the Cloudflare Workers
 * resource ceiling (#689). This file stays as the fallback for any request that
 * reaches route resolution anyway, and so the route-manifest equality test
 * (`test_inventory_manifest_matches_frontend_app_route_tree`) still passes.
 */
export default function AdminDuesRedirectPage() {
  redirect("/admin/payments");
}
