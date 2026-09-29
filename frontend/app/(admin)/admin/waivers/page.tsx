"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Settings overhaul Phase 3 PR 10: waiver template management moved into
 * Settings -> Family policies ("Registration & waivers" card), reusing
 * `WaiversManagement` (`components/admin/waivers/waivers-management.tsx`).
 * The sidebar's standalone "Waivers" item was removed with it.
 *
 * This index route redirects rather than duplicating that UI, so there is
 * one place to keep the waiver logic. `/admin/waivers/[waiverId]` and
 * `/admin/waivers/signatures/[signatureId]` are untouched and still work —
 * the "Open"/"Open template" links inside the embedded panel still point at
 * them, from Family policies or from an old bookmark of this page either
 * way.
 */
export default function AdminWaiversPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin/settings?panel=family-policies");
  }, [router]);

  return null;
}
