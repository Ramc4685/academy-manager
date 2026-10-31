import { readFileSync } from "node:fs";
import path from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/lib/query/keys";
import { useManualPaymentMethods } from "./use-manual-payment-methods";

function MethodSelect() {
  const { options, method } = useManualPaymentMethods();
  return (
    <select value={method} onChange={() => {}}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function render(manualMethods?: string[]): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (manualMethods) {
    client.setQueryData(queryKeys.admin.paymentMethods(), { manual_methods: manualMethods });
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MethodSelect />
    </QueryClientProvider>,
  );
}

function optionValues(html: string): string[] {
  return [...html.matchAll(/<option value="([^"]+)"/g)].map((m) => m[1]);
}

function selectedValue(html: string): string | undefined {
  return /<option value="([^"]+)" selected=""/.exec(html)?.[1];
}

describe("useManualPaymentMethods", () => {
  it("BLNO: all six in the old order with cash selected, before and after the read", () => {
    const six = ["cash", "check", "zelle", "venmo", "bank_transfer", "other"];
    for (const html of [render(), render(six)]) {
      expect(optionValues(html)).toEqual(six);
      expect(selectedValue(html)).toBe("cash");
    }
  });

  it("an academy's choice: exactly its methods, first one selected", () => {
    const html = render(["other", "zelle"]);
    expect(optionValues(html)).toEqual(["zelle", "other"]);
    expect(selectedValue(html)).toBe("zelle");
  });
});

/** The incoming-payment dialogs (coach payouts are outgoing and out of scope). */
const DIALOGS = [
  "app/(admin)/admin/payments/buckets/RecordPaymentDialog.tsx",
  "app/(admin)/admin/payments/dialogs.tsx",
  "app/(admin)/admin/students/[studentId]/billing-dialogs.tsx",
];

describe("incoming-payment dialogs read the academy's methods", () => {
  it.each(DIALOGS)("%s uses the hook and hardcodes no method list", (file) => {
    const source = readFileSync(path.resolve(__dirname, "..", file), "utf8");
    expect(source).toContain("useManualPaymentMethods(");
    expect(source).not.toMatch(/<option value="(cash|check|zelle|venmo|bank_transfer|other)"/);
    expect(source).not.toMatch(/useState\("cash"\)/);
  });

  it("payments/dialogs.tsx wires both of its dialogs", () => {
    const source = readFileSync(
      path.resolve(__dirname, "..", "app/(admin)/admin/payments/dialogs.tsx"),
      "utf8",
    );
    expect(source.match(/useManualPaymentMethods\(/g)).toHaveLength(2);
  });

  // MarkPaidDialog and InvoiceDialog are mounted unconditionally by
  // AllInvoicesTab (only their *visibility* toggles on the `payment` prop),
  // so an ungated read fires on every load of that tab, not just when a
  // dialog is actually open. Pin the gate so it can't silently regress.
  it("payments/dialogs.tsx gates both reads on `payment !== null`, not an always-on read", () => {
    const source = readFileSync(
      path.resolve(__dirname, "..", "app/(admin)/admin/payments/dialogs.tsx"),
      "utf8",
    );
    expect(source.match(/useManualPaymentMethods\(payment !== null\)/g)).toHaveLength(2);
  });

  it("a caller that passes enabled: false never fetches", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let fetches = 0;
    client.setQueryDefaults(queryKeys.admin.paymentMethods(), {
      queryFn: () => {
        fetches += 1;
        return Promise.resolve({ manual_methods: ["cash", "check"] });
      },
    });

    function Gated() {
      const { options } = useManualPaymentMethods(false);
      return <span>{options.length}</span>;
    }

    renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <Gated />
      </QueryClientProvider>,
    );

    expect(fetches).toBe(0);
  });
});
