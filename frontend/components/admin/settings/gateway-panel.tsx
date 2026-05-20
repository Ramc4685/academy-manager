"use client";

import { ComingNextCard } from "./coming-next-card";

export function GatewayPanel() {
  return (
    <section data-testid="admin-settings-gateway">
      <ComingNextCard
        title="Gateway settings"
        description="Stripe Connect status needs the gateway read model before this panel can show live account and manual payment details."
      />
    </section>
  );
}
