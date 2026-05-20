"use client";

import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

interface ComingNextCardProps {
  title: string;
  description: string;
}

export function ComingNextCard({ title, description }: ComingNextCardProps) {
  return (
    <div data-testid="admin-stub-card">
      <Card p={32} className="max-w-3xl">
        <Overline>Coming next</Overline>
        <h2 className="mt-3 font-display text-[18px] font-semibold text-rally-ink">
          {title}
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-rally-muted">{description}</p>
      </Card>
    </div>
  );
}
