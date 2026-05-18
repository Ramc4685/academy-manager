"use client";

import { useQuery } from "@tanstack/react-query";

import { listParentChildren, type ParentChild } from "@/lib/api/parent";

export default function ParentChildrenPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });

  return (
    <section data-testid="parent-children">
      <h1 className="mb-4 text-2xl font-semibold">My children</h1>
      {isError ? (
        <p className="text-sm text-red-600">Could not load children.</p>
      ) : isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : (data?.children.length ?? 0) === 0 ? (
        <p className="text-sm text-neutral-500">No children registered yet.</p>
      ) : (
        <div className="grid gap-3">
          {data!.children.map((child) => (
            <ChildCard key={child.student_id} child={child} />
          ))}
        </div>
      )}
    </section>
  );
}

function ChildCard({ child }: { child: ParentChild }) {
  return (
    <article className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{child.full_name}</h2>
          <p className="mt-1 text-xs text-neutral-500">{child.student_id}</p>
        </div>
        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
          {child.status}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
        <Metric label="Sessions" value={child.active_session_count} />
        <Metric label="Present" value={child.attended_count} />
        <Metric label="Absent" value={child.absent_count} />
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-neutral-50 p-3 dark:bg-neutral-800">
      <p className="font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-neutral-500">{label}</p>
    </div>
  );
}
