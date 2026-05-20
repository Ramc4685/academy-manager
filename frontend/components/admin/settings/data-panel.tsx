"use client";

import { ComingNextCard } from "./coming-next-card";

export function DataPanel() {
  return (
    <section data-testid="admin-settings-data">
      <ComingNextCard
        title="Data controls"
        description="Exports and account deletion controls need the follow-on data governance endpoints before this panel can be operational."
      />
    </section>
  );
}
