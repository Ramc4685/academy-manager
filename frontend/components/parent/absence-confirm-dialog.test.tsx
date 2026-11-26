import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const seen: Array<Record<string, unknown>> = [];
vi.mock("@/components/ds/confirm-action-dialog", () => ({
  ConfirmActionDialog: (props: Record<string, unknown>) => {
    seen.push(props);
    return null;
  },
}));

import { AbsenceConfirmDialog } from "./absence-confirm-dialog";

describe("AbsenceConfirmDialog", () => {
  it("names the child, class and date and offers an optional reason", () => {
    renderToStaticMarkup(
      <AbsenceConfirmDialog
        open
        onOpenChange={() => undefined}
        childName="Alex Chen"
        sessionTitle="Junior Beginners"
        when="Sat, Nov 28 · 10:00 – 11:00 AM"
        reason=""
        onReasonChange={() => undefined}
        pending={false}
        onConfirm={() => undefined}
      />,
    );
    const props = seen.at(-1)!;
    expect(props.title).toBe("Alex Chen will miss this class?");
    expect(props.subject).toBe("Junior Beginners · Sat, Nov 28 · 10:00 – 11:00 AM");
    expect(props.confirmLabel).toBe("Report absence");
    const reason = props.reason as { label: string; required?: boolean };
    expect(reason.label).toBe("Reason (optional)");
    expect(reason.required).toBeFalsy();
  });
});
