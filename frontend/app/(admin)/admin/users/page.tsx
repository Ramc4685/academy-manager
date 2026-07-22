import { Suspense } from "react";

import { AdminUsersDirectory } from "@/components/admin/AdminUsersDirectory";

export default function AdminUsersPage() {
  return (
    <Suspense>
      <AdminUsersDirectory />
    </Suspense>
  );
}
