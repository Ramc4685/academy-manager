import { redirect } from "next/navigation";

/**
 * The Dues page was removed with Month close (spec §6). Payments owns chasing
 * balances now; the WhatsApp link moved onto the Past due and Awaiting rows.
 * The file stays so the route-manifest equality test still passes.
 */
export default function AdminDuesRedirectPage() {
  redirect("/admin/payments");
}
