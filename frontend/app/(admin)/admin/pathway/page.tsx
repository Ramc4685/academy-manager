"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Settings overhaul Phase 3 PR 11: authoring (programs, levels, skills,
 * lesson cards) moved into Settings -> Curriculum. The sidebar's "Pathway"
 * item became "Progress" and points at /admin/pathway/progress. This index
 * route redirects so old bookmarks keep working.
 */
export default function AdminPathwayPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin/settings?panel=curriculum");
  }, [router]);

  return null;
}
