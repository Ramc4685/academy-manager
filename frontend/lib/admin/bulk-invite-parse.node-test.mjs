import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BULK_INVITE_MAX_ROWS,
  parseBulkInviteText,
  toBulkInviteItems,
} from "./bulk-invite-parse.ts";

test("parses `email, name` lines and trims whitespace", () => {
  const parsed = parseBulkInviteText("  ana@example.com , Ana Parent \nbo@example.com,Bo Parent");

  assert.equal(parsed.rows.length, 2);
  assert.deepEqual(toBulkInviteItems(parsed), [
    { email: "ana@example.com", display_name: "Ana Parent" },
    { email: "bo@example.com", display_name: "Bo Parent" },
  ]);
  assert.equal(parsed.validCount, 2);
  assert.equal(parsed.invalidCount, 0);
  assert.equal(parsed.duplicateCount, 0);
});

test("accepts the reversed `name, email` column order", () => {
  const parsed = parseBulkInviteText("Ana Parent,ana@example.com");

  assert.deepEqual(toBulkInviteItems(parsed), [
    { email: "ana@example.com", display_name: "Ana Parent" },
  ]);
});

test("skips a CSV header row", () => {
  const parsed = parseBulkInviteText("email,name\nana@example.com,Ana Parent");

  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].email, "ana@example.com");
});

test("derives a display name from the local part when only an email is given", () => {
  const parsed = parseBulkInviteText("jane.doe@example.com");

  assert.deepEqual(toBulkInviteItems(parsed), [
    { email: "jane.doe@example.com", display_name: "Jane Doe" },
  ]);
});

test("lowercases emails and flags in-batch duplicates instead of sending them twice", () => {
  const parsed = parseBulkInviteText(
    "Ana@Example.com,Ana Parent\nana@example.com,Ana Again\nbo@example.com,Bo Parent",
  );

  assert.equal(parsed.rows.length, 3);
  assert.equal(parsed.rows[1].duplicate, true);
  assert.equal(parsed.duplicateCount, 1);
  assert.deepEqual(toBulkInviteItems(parsed), [
    { email: "ana@example.com", display_name: "Ana Parent" },
    { email: "bo@example.com", display_name: "Bo Parent" },
  ]);
});

test("flags malformed emails and over-long names without dropping the row", () => {
  const parsed = parseBulkInviteText(`not-an-email,Nope\nok@example.com,${"n".repeat(121)}`);

  assert.equal(parsed.rows.length, 2);
  assert.match(parsed.rows[0].error ?? "", /email/i);
  assert.match(parsed.rows[1].error ?? "", /name/i);
  assert.equal(parsed.invalidCount, 2);
  assert.deepEqual(toBulkInviteItems(parsed), []);
});

test("ignores blank lines and stray quotes", () => {
  const parsed = parseBulkInviteText('\n"ana@example.com","Ana Parent"\n\n');

  assert.deepEqual(toBulkInviteItems(parsed), [
    { email: "ana@example.com", display_name: "Ana Parent" },
  ]);
});

test("reports when the batch is over the backend's 100-row limit", () => {
  const lines = Array.from(
    { length: BULK_INVITE_MAX_ROWS + 1 },
    (_, i) => `p${i}@example.com,Parent ${i}`,
  );
  const parsed = parseBulkInviteText(lines.join("\n"));

  assert.equal(parsed.validCount, BULK_INVITE_MAX_ROWS + 1);
  assert.equal(parsed.overLimit, true);

  const under = parseBulkInviteText(lines.slice(0, BULK_INVITE_MAX_ROWS).join("\n"));
  assert.equal(under.overLimit, false);
});
