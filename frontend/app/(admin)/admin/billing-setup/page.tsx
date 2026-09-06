import { redirect } from "next/navigation";

/** Billing Setup was folded into Families (spec 2026-09-05-family-billing §6). */
export default function BillingSetupRedirect() {
  redirect("/admin/families");
}
