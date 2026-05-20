"use client";

import { ComingNextCard } from "./coming-next-card";

export function RolesPanel() {
  return (
    <section data-testid="admin-settings-roles">
      <ComingNextCard
        title="Role management"
        description="Role changes and invites need the admin identity write endpoints and anti-lockout checks before they are safe to operate here."
      />
    </section>
  );
}
