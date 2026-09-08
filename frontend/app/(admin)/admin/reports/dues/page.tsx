import { redirect } from "next/navigation";

/**
 * The Dues follow-up page was removed with Month close (spec §6). Its buckets,
 * reminders and WhatsApp link all live on Payments now, and the tuition
 * discount card moved to Month close. The file stays so the route-manifest
 * equality test still passes.
 */
export default function AdminDuesFollowupRedirectPage() {
  redirect("/admin/payments");
}
