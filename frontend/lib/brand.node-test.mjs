import assert from "node:assert/strict";
import { test } from "node:test";

import { brand, copyrightNotice } from "./brand.ts";

test("public brand owner is Marvy Labs", () => {
  assert.equal(brand.companyName, "Marvy Labs");
  assert.equal(brand.legalOwner, "Marvy Labs");
});

test("copyright notice uses standard ASCII notice format", () => {
  assert.equal(
    copyrightNotice(),
    "Copyright (c) 2024-2026 Marvy Labs. All rights reserved."
  );
});

test("public product copy does not expose implementation versioning", () => {
  const publicValues = [
    brand.companyName,
    brand.productName,
    brand.productFullName,
    brand.productDescriptor,
    copyrightNotice(),
  ].join(" ");

  assert.equal(/\bv2\b|v2\.0|Next v2/i.test(publicValues), false);
});
