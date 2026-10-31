"use client";

import type { ReactNode } from "react";

import type { AdminStudentDetail } from "@/lib/api/v2/students";
import { Avatar } from "@/components/ds/avatar";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";

/**
 * The student identity block — avatar, name, derived lifecycle chip.
 *
 * Issue #896: the Progress tab opened on a bare `<h1>`, so moving between a
 * student's Detail and Progress tabs changed who the page appeared to be
 * about. This is the same treatment the detail page's own header card uses
 * (avatar 56, display name, one `#773` lifecycle chip), lifted into a shared
 * component so the two cannot drift again.
 *
 * `student` is optional because the Progress page renders before its student
 * query resolves; the fallback name keeps the heading stable rather than
 * flashing an empty card.
 */
export function StudentIdentityHeader({
  student,
  fallbackName = "Student",
  subtitle,
  action,
}: {
  student?: AdminStudentDetail | null;
  fallbackName?: string;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  const name = student?.full_name?.trim() || fallbackName;
  const label = student
    ? lifecycleLabel(student.lifecycle, student.lifecycle_as_of)
    : "";

  return (
    <Card p={20} data-testid="admin-student-identity-header">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <Avatar name={student?.full_name ?? ""} size={56} />
          <div className="min-w-0">
            <h1 className="truncate font-display text-xl font-semibold tracking-[-0.01em] text-rally-ink">
              {name}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {label && (
                <Chip variant={lifecycleVariant(student?.lifecycle)} label={label} />
              )}
              {subtitle && <span className="text-sm text-rally-muted">{subtitle}</span>}
            </div>
          </div>
        </div>
        {action && <div className="flex shrink-0 items-start gap-2">{action}</div>}
      </div>
    </Card>
  );
}
