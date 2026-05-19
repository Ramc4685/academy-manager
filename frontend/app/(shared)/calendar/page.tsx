"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCurrentUser } from "@/lib/api/me";

export default function CalendarPage() {
  const { data } = useQuery({ queryKey: ["me", "calendar"], queryFn: getCurrentUser });
  const roles = data?.roles ?? [];
  const href = roles.includes("admin")
    ? "/admin/sessions"
    : roles.includes("coach")
      ? "/coach/sessions"
      : roles.includes("parent")
        ? "/parent/dashboard"
        : "/login";

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Calendar</h1>
      <p className="mt-2 text-sm text-neutral-500">
        Session schedules are available in the persona workspace backed by the v2 BFF.
      </p>
      <div className="mt-6 rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
        <p className="text-sm text-neutral-600 dark:text-neutral-300">
          Open your workspace schedule to view sessions with the correct persona permissions.
        </p>
        <Link
          href={href}
          className="mt-4 inline-flex min-h-touch items-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
        >
          Open schedule
        </Link>
      </div>
    </main>
  );
}
