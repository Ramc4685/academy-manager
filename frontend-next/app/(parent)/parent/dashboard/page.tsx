"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { listParentPayments } from "@/lib/api/parent";

export default function ParentDashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["parent", "payments"],
    queryFn: listParentPayments,
  });
  const payments = data?.payments ?? [];

  return (
    <section data-testid="parent-dashboard">
      <header className="mb-5">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Parent dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">Payments and onboarding for your family.</p>
      </header>

      <div className="grid grid-cols-2 gap-3">
        <Metric label="Payments" value={isLoading ? "-" : String(payments.length)} />
        <Metric
          label="Refunded"
          value={
            isLoading
              ? "-"
              : String(payments.filter((payment) => payment.refunded_cents > 0).length)
          }
        />
      </div>

      <div className="mt-6 grid gap-3">
        <ActionCard href="/parent/payments" title="Payments" body="Review your payment history." />
        <ActionCard href="/parent/onboarding" title="Register a child" body="Start or resume onboarding." />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-2 font-display text-3xl font-semibold text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}

function ActionCard({ href, title, body }: { href: string; title: string; body: string }) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-blue-300 dark:border-slate-800 dark:bg-slate-950"
    >
      <p className="font-semibold text-slate-950 dark:text-white">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{body}</p>
    </Link>
  );
}
