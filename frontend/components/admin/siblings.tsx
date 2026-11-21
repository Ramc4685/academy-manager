"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Chip } from "@/components/ds";
import { fetchFamilyRecord, type FamilyIndexRow } from "@/lib/api/admin-families";
import { studentHref } from "@/lib/admin/family-index-view";
import { queryKeys } from "@/lib/query/keys";

type SiblingFamily = Pick<FamilyIndexRow, "family_id" | "children" | "sibling_student_ids">;

/**
 * The family's other enrolled children (active, held or paused), by the
 * server's `sibling_student_ids`; empty when it is not a sibling family.
 * Independent of billing and of the sibling discount setting.
 */
export function siblingsOf(
  family: SiblingFamily,
  studentId?: string,
): { student_id: string; name: string }[] {
  const ids = family.sibling_student_ids ?? [];
  if (ids.length < 2 || (studentId !== undefined && !ids.includes(studentId))) return [];
  return family.children.filter((c) => ids.includes(c.student_id) && c.student_id !== studentId);
}

/** "Siblings · 2" on the family list and the family header, or nothing. */
export function SiblingsChip({ family }: { family: SiblingFamily }) {
  const kids = siblingsOf(family);
  if (kids.length === 0) return null;
  return (
    <span
      title={`Enrolled children: ${kids.map((k) => k.name).join(", ")}`}
      data-testid={`family-siblings-${family.family_id}`}
    >
      <Chip variant="makeup" label={`Siblings · ${kids.length}`} />
    </span>
  );
}

/**
 * "Sibling of Ava, Ben" on the student page header, each name a link. Reads
 * the family record (the family page's own query); nothing while it loads,
 * fails or the student has no enrolled sibling.
 */
export function StudentSiblings({
  studentId,
  parentId,
}: {
  studentId: string;
  parentId: string | null | undefined;
}) {
  const record = useQuery({
    queryKey: queryKeys.admin.familyRecord(parentId ?? ""),
    queryFn: () => fetchFamilyRecord(parentId ?? ""),
    enabled: Boolean(parentId),
    retry: false,
  });
  const family = record.data?.family;
  const kids = family ? siblingsOf(family, studentId) : [];
  if (kids.length === 0) return null;
  return (
    <p className="mt-1 text-sm text-rally-muted" data-testid="admin-student-siblings">
      Sibling of{" "}
      {kids.map((kid, i) => (
        <span key={kid.student_id}>
          {i > 0 ? ", " : null}
          <Link
            href={studentHref(kid.student_id)}
            className="font-medium text-rally-cobalt-700 underline decoration-rally-cobalt-600/40 underline-offset-2 hover:decoration-rally-cobalt-600 dark:text-rally-cobalt-100"
            data-testid={`admin-student-sibling-${kid.student_id}`}
          >
            {kid.name}
          </Link>
        </span>
      ))}
    </p>
  );
}
