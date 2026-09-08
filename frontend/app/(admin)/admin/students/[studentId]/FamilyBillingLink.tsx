"use client";

import Link from "next/link";

import { Button, Card, Overline } from "@/components/ds";

/**
 * Student Billing tab: invoices, payments, autopay and corrections belong to
 * the family, so this panel only points at the family billing page
 * (spec 2026-09-05-family-billing §6).
 */
export function FamilyBillingLink({
  parentId,
  parentName,
}: {
  parentId: string | null | undefined;
  parentName: string | null | undefined;
}) {
  return (
    <Card p={20} data-testid="admin-student-family-billing-link">
      <Overline>Billing</Overline>
      <p className="mt-1 text-sm text-rally-muted">
        Invoices, payments, autopay and corrections live on the family page, which covers every
        sibling.
      </p>
      {parentId ? (
        <Link href={`/admin/families/${encodeURIComponent(parentId)}`} className="mt-3 inline-block">
          <Button size="sm" variant="primary">
            Open family billing{parentName ? ` · ${parentName}` : ""}
          </Button>
        </Link>
      ) : (
        <p className="mt-2 text-sm text-rally-muted">This student has no parent on file.</p>
      )}
    </Card>
  );
}
