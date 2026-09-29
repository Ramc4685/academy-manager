"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

/**
 * Settings overhaul Phase 3 PR 11: the program editor now opens inside
 * Settings -> Curriculum (`?panel=curriculum&program=<id>`). This route
 * redirects so old links to a program keep working.
 */
export default function AdminPathwayDetailPage() {
  const { programId } = useParams<{ programId: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!programId) return;
    router.replace(
      `/admin/settings?panel=curriculum&program=${encodeURIComponent(programId)}` as never,
    );
  }, [programId, router]);

  return null;
}
