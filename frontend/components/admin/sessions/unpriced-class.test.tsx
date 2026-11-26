import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { UnpricedClassBanner, UnpricedEnrollAcknowledgement } from "./unpriced-class";

const APP = path.resolve(__dirname, "../../../app/(admin)/admin");
const src = (rel: string) => readFileSync(path.join(APP, rel), "utf8");

describe("unpriced class (S10)", () => {
  it("the banner tells staff the owner must set a price", () => {
    expect(renderToStaticMarkup(<UnpricedClassBanner />)).toContain(
      "No price set. The owner must set one before billing.",
    );
  });

  it("the acknowledgement is an unticked checkbox until the admin ticks it", () => {
    const html = renderToStaticMarkup(
      <UnpricedEnrollAcknowledgement checked={false} onChange={() => {}} />,
    );
    expect(html).toContain('type="checkbox"');
    expect(html).not.toContain("checked");
    expect(html).toContain("will not be billed until the owner sets one");
  });

  it("the class header reads the server flag, not the fee", () => {
    const page = src("sessions/[id]/page.tsx");
    expect(page).toContain("{session.unpriced && <UnpricedClassBanner />}");
    expect(page).toContain("unpriced={Boolean(session?.unpriced)}");
  });

  it("enroll and Add-and-enroll wait for the acknowledgement", () => {
    expect(src("sessions/[id]/dialogs.tsx")).toContain(
      "disabled={mutation.isPending || (unpriced && !acknowledged)}",
    );
    expect(src("families/QuickAddFamily.tsx")).toContain(
      "disabled={add.isPending || (chosenUnpriced && !unpricedAck)}",
    );
  });
});
