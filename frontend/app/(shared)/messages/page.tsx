"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCurrentUser } from "@/lib/api/me";

export default function MessagesPage() {
  const { data } = useQuery({ queryKey: ["me", "messages"], queryFn: getCurrentUser });
  const isAdmin = data?.roles.includes("admin") ?? false;

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Messages</h1>
      <p className="mt-2 text-sm text-neutral-500">
        Admin broadcast and direct-message tools are available in the v2 communication BFF.
      </p>
      <div className="mt-6 rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
        <p className="text-sm text-neutral-600 dark:text-neutral-300">
          {isAdmin
            ? "Open the admin communication workspace to send broadcasts and direct messages."
            : "Message inbox access is persona-scoped. Admin users can manage communication from the admin workspace."}
        </p>
        <Link
          href={isAdmin ? "/admin/comms" : "/post-login"}
          className="mt-4 inline-flex min-h-touch items-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
        >
          {isAdmin ? "Open admin comms" : "Go to workspace"}
        </Link>
      </div>
    </main>
  );
}
