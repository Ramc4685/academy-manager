import { describe, expect, it } from "vitest";

import { bulkTransferFailures } from "./dialogs";
import { isBulkTransferable } from "./RosterPanel";

describe("bulk roster transfer (A0-8)", () => {
  it("names each refused student with the server's reason, and skips the moved ones", () => {
    const lines = bulkTransferFailures(
      {
        results: [
          { enrollment_id: "e1", ok: true, error_code: null, message: null },
          { enrollment_id: "e2", ok: false, error_code: "Enrollment.CapacityExceeded", message: "target session full" },
          { enrollment_id: "e3", ok: false, error_code: "Enrollment.NotFound", message: null },
        ],
        moved_count: 1,
        failed_count: 2,
      },
      [
        { enrollment_id: "e1", full_name: "Ana Fake" },
        { enrollment_id: "e2", full_name: "Ben Fake" },
      ],
    );
    expect(lines).toEqual([
      "Ben Fake could not move: target session full",
      "A student could not move: refused",
    ]);
  });

  it("only lets live, seat-holding rows be selected", () => {
    expect(isBulkTransferable("active")).toBe(true);
    expect(isBulkTransferable("held")).toBe(true);
    for (const status of ["reclaim_pending", "paused", "dropped", "deleted"] as const) {
      expect(isBulkTransferable(status), status).toBe(false);
    }
  });
});
