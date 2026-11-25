"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Chip } from "@/components/ds/chip";
import { getParentCurrentWaiver } from "@/lib/api/parent";

/**
 * One child's waiver state where a parent looks at that child (usability
 * study: a tester on Profile never found the waiver). Shares Home's query key,
 * so it is usually cached. Renders nothing when no waiver applies or the read
 * failed: a failed read must never claim "signed".
 */
export function ChildWaiverStatus({ studentId }: { studentId: string }) {
  const { data } = useQuery({
    queryKey: ["parent", "waivers", "current"],
    queryFn: getParentCurrentWaiver,
    retry: false,
  });
  if (!data?.required) return null;
  const rows = (data.waivers?.flatMap((w) => w.students) ?? data.students).filter(
    (s) => s.student_id === studentId && s.status !== "not_required",
  );
  if (rows.length === 0) return null;
  const needed = rows.some((s) => s.status === "pending");
  const outdated = rows.some((s) => s.status === "outdated");
  const open = needed || outdated;
  return (
    <div data-testid={`child-waiver-${studentId}`} className="flex items-center gap-2 text-sm">
      <Chip
        variant={open ? "pending" : "approved"}
        label={needed ? "Waiver needed" : outdated ? "Waiver outdated" : "Waiver signed"}
      />
      <Link
        href="/parent/waivers"
        className="inline-flex min-h-touch items-center font-semibold text-rally-cobalt-700 underline underline-offset-2"
      >
        {open ? "Sign now" : "View"}
      </Link>
    </div>
  );
}
