"use client";

import { Card } from "@/components/ds/card";
import { Icon } from "@/components/ds/icons";
import { Overline } from "@/components/ds/typography";
import { ComingNextCard } from "./coming-next-card";

const EXPORTS = [
  { name: "payments", title: "Payments CSV", description: "Transactions and billing status." },
  { name: "students", title: "Students CSV", description: "Roster and parent ownership." },
  { name: "attendance", title: "Attendance CSV", description: "Attendance history export." },
];

export function DataPanel() {
  return (
    <section data-testid="admin-settings-data" className="space-y-4">
      <Card p={24}>
        <Overline>Exports</Overline>
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {EXPORTS.map((item) => (
            <div key={item.name} className="rounded-md border border-rally-line p-4">
              <h3 className="font-semibold text-rally-ink">{item.title}</h3>
              <p className="mt-1 min-h-10 text-sm text-rally-muted">{item.description}</p>
              <a
                href={`/api/v2/admin/reports/${item.name}.csv`}
                download
                className="mt-4 inline-flex h-[30px] items-center justify-center gap-2 rounded-lg border border-rally-line bg-white px-3 font-body text-xs font-semibold text-rally-ink shadow-[0_1px_0_rgba(0,0,0,0.02)]"
              >
                {Icon.dl(14, "currentColor")}
                  Download
              </a>
            </div>
          ))}
        </div>
      </Card>
      <ComingNextCard
        title="Deletion controls"
        description="Account deletion and retention workflows need dedicated governance endpoints before destructive data operations are exposed."
      />
    </section>
  );
}
