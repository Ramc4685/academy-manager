"use client";

/**
 * Admin payments — two tabs.
 *
 * "Collections" is the six-bucket work list (payments buckets spec §4);
 * "All invoices" is the previous page body, reachable at
 * `/admin/payments?tab=invoices`. The `admin-payments` test id stays on the
 * root so existing specs keep finding the page.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AllInvoicesTab } from "./AllInvoicesTab";
import { CollectionsTab } from "./buckets/CollectionsTab";

type PaymentsTab = "buckets" | "invoices";

const TABS: { id: PaymentsTab; label: string }[] = [
  { id: "buckets", label: "Collections" },
  { id: "invoices", label: "All invoices" },
];

export default function AdminPaymentsPage() {
  return (
    <Suspense fallback={<section data-testid="admin-payments" className="space-y-5" />}>
      <PaymentsTabs />
    </Suspense>
  );
}

function PaymentsTabs() {
  const searchParams = useSearchParams();
  const initialTab: PaymentsTab = searchParams.get("tab") === "invoices" ? "invoices" : "buckets";
  const [tab, setTab] = useState<PaymentsTab>(initialTab);

  return (
    <section data-testid="admin-payments" className="space-y-5">
      <div
        role="tablist"
        aria-label="Payments view"
        className="flex flex-wrap gap-1 rounded-xl bg-neutral-100 p-1 dark:bg-neutral-800"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            data-testid={`payments-tab-${t.id}`}
            className="min-h-touch flex-1 rounded-lg px-3 text-sm font-semibold transition-all duration-150"
            style={
              tab === t.id
                ? { background: "white", color: "var(--rally-ink)", boxShadow: "0 1px 2px rgba(0,0,0,0.06)" }
                : { background: "transparent", color: "var(--rally-muted)" }
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "buckets" && <CollectionsTab />}
      {tab === "invoices" && <AllInvoicesTab />}
    </section>
  );
}
