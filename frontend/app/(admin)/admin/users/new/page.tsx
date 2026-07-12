"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { createAdminUser, type AdminUserRole } from "@/lib/api/admin";
import { Button } from "@/components/ds/button";

const roleOptions: AdminUserRole[] = ["parent", "coach", "admin"];

export default function NewAdminUserPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<AdminUserRole>("parent");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createAdminUser({
        role,
        display_name: displayName,
        email,
        phone: phone || null,
        reason: "manual user creation",
      }),
    onSuccess: (user) => {
      router.push(`/admin/users/${user.user_id}`);
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not create user.");
    },
  });

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4">
      <h1 className="text-lg font-semibold text-rally-ink">Add user</h1>
      <p className="text-sm text-slate-500">
        Parents created here get a &ldquo;set your password&rdquo; email
        automatically, so they can log in with any email address — no Google
        account needed.
      </p>
      <form
        className="space-y-3 rounded-lg border border-rally-line bg-white p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        <label className="block text-sm">
          <span className="text-slate-600">Full name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            maxLength={120}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-name"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            maxLength={254}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-email"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Phone (optional)</span>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            maxLength={40}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as AdminUserRole)}
            className="mt-1 w-full rounded-md border border-rally-line px-2 py-1.5 text-sm"
            data-testid="new-user-role"
          >
            {roleOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create user"}
        </Button>
      </form>
    </div>
  );
}
