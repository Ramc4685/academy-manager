"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ds/skeleton";
import { ReceiptDocument } from "@/components/parent/receipt-document";
import { getParentReceipt } from "@/lib/api/parent";

export default function ParentReceiptPage() {
  const params = useParams<{ invoiceId: string }>();
  const invoiceId = decodeURIComponent(params.invoiceId);
  const receiptQuery = useQuery({
    queryKey: ["parent", "receipt", invoiceId],
    queryFn: () => getParentReceipt(invoiceId),
    retry: false,
  });

  return (
    <section data-testid="parent-receipt" className="space-y-4 animate-fade-in-up">
      <Link
        href="/parent/payments"
        className="inline-flex min-h-touch items-center text-sm font-semibold text-rally-cobalt-600 hover:underline print:hidden"
      >
        ← Back to payments
      </Link>
      {receiptQuery.isPending && <Skeleton variant="block" height="24rem" className="rounded-2xl" />}
      {receiptQuery.isError && (
        <div
          data-testid="parent-receipt-error"
          className="rounded-2xl border border-status-red-500/30 bg-status-red-50 p-4 text-sm text-status-red-800"
          role="alert"
        >
          We could not open this receipt. It may not be yours, or it is not paid yet.
        </div>
      )}
      {receiptQuery.data && <ReceiptDocument receipt={receiptQuery.data} />}
    </section>
  );
}
