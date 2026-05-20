"use client";

import { ComingNextCard } from "./coming-next-card";

export function BrandingPanel() {
  return (
    <section data-testid="admin-settings-branding">
      <ComingNextCard
        title="Branding"
        description="Logo upload, color controls, and email signatures need object storage and branding persistence before real values can be edited."
      />
    </section>
  );
}
