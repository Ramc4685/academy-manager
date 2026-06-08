import assert from "node:assert/strict";
import { test } from "node:test";

import { brand, copyrightNotice } from "./brand.ts";

test("public brand owner is Marvy Labs", () => {
  assert.equal(brand.companyName, "Marvy Labs");
  assert.equal(brand.legalOwner, "Marvy Labs");
});

test("copyright notice uses standard ASCII notice format", () => {
  const notice = copyrightNotice();

  assert.match(
    notice,
    /^Copyright \(c\) \d{4}-\d{4} Marvy Labs\. All rights reserved\.$/
  );
  const yearRange = notice.match(/(\d{4})-(\d{4})/);
  assert.ok(yearRange, "Copyright notice should include a year range");

  const [, startYear, endYear] = yearRange;
  assert.ok(Number(endYear) >= Number(startYear), "End year should be >= start year");
});

test("public product copy does not expose implementation versioning", () => {
  const publicValues = [
    brand.companyName,
    brand.productName,
    brand.productFullName,
    brand.productDescriptor,
    copyrightNotice(),
  ].join(" ");

  const versionToken = "v2";
  const forbiddenPattern = new RegExp(
    [`\\b${versionToken}\\b`, `${versionToken}\\.0`, `Next ${versionToken}`].join("|"),
    "i"
  );

  assert.doesNotMatch(publicValues, forbiddenPattern);
});
