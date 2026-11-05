import { describe, expect, it } from "vitest";

import { mapColumnsErrorMessage } from "@/lib/api/admin-ai-import";

import {
  applyColumnMapping,
  checkImportHeader,
  choicesFromDraft,
  mappingFromChoices,
  parseCsv,
  readHeaders,
} from "./import-column-mapping";

describe("parseCsv", () => {
  it("reads quoted cells with commas, doubled quotes and newlines", () => {
    expect(parseCsv('a,"b, c","say ""hi""","line\none"\r\nx,y,z,w\r\n')).toEqual([
      ["a", "b, c", 'say "hi"', "line\none"],
      ["x", "y", "z", "w"],
    ]);
  });
});

describe("checkImportHeader", () => {
  it("accepts the five import columns in any case and order", () => {
    expect(checkImportHeader("Student_Name,parent_name,parent_email\n")).toEqual({ ok: true });
  });

  it("names unknown and missing columns", () => {
    const check = checkImportHeader("Guardian,Child,parent_email\n");
    expect(check.ok).toBe(false);
    if (!check.ok) {
      expect(check.unknown).toEqual(["guardian", "child"]);
      expect(check.missing).toEqual(["parent_name", "student_name"]);
    }
  });
});

describe("readHeaders", () => {
  it("cuts a header to the backend's 80 characters so the draft can name it", () => {
    const long = "H".repeat(90);
    expect(readHeaders(`${long},B\n1,2\n`)).toEqual(["H".repeat(80), "B"]);
    const out = applyColumnMapping(`${long},B\n1,2\n`, [
      { target: "parent_name", source_headers: ["H".repeat(80)] },
    ]);
    expect(out).toBe("parent_name\r\n1\r\n");
  });
});

describe("applyColumnMapping", () => {
  const csv =
    'First,Last,E-mail,Kid,Notes\r\n' +
    'Jane,"Doe, Jr.",jane@example.org,Sam,"likes ""red"""\r\n' +
    '\r\n' +
    "Ann,Roe,ann@example.org,Kit,\r\n";

  it("joins two sources with a space, keeps column order and drops ignored columns", () => {
    const out = applyColumnMapping(csv, [
      { target: "student_name", source_headers: ["Kid"] },
      { target: "parent_name", source_headers: ["First", "Last"] },
      { target: "parent_email", source_headers: ["E-mail"] },
    ]);
    expect(out).toBe(
      "parent_name,parent_email,student_name\r\n" +
        '"Jane Doe, Jr.",jane@example.org,Sam\r\n' +
        "Ann Roe,ann@example.org,Kit\r\n"
    );
  });

  it("outputs only the mapped columns and an empty cell for a header the file lacks", () => {
    const out = applyColumnMapping("A,B\r\n1,2\r\n", [
      { target: "parent_name", source_headers: ["A"] },
      { target: "student_name", source_headers: ["Nope"] },
    ]);
    expect(out).toBe("parent_name,student_name\r\n1,\r\n");
  });
});

describe("mapColumnsErrorMessage", () => {
  it("maps the AI statuses to plain sentences", () => {
    expect(mapColumnsErrorMessage({ status: 503 })).toBe(
      "AI import help is not enabled for this academy yet"
    );
    expect(mapColumnsErrorMessage({ status: 429 })).toBe(
      "This academy has used its AI drafts for the month"
    );
    expect(mapColumnsErrorMessage({ status: 502 })).toBe("The mapping could not be read, try again");
    expect(mapColumnsErrorMessage(null)).toBe("The columns could not be mapped just now. Try again.");
  });
});

describe("choices round trip", () => {
  it("prefills from the draft and rebuilds the mapping in file order", () => {
    const headers = ["First", "Last", "Kid", "Notes"];
    const choices = choicesFromDraft(headers, {
      mappings: [
        { target: "parent_name", source_headers: ["First", "Last"], confidence: "high", note: "" },
        { target: "student_name", source_headers: ["Kid"], confidence: "high", note: "" },
      ],
    });
    expect(choices).toEqual({ First: "parent_name", Last: "parent_name", Kid: "student_name", Notes: "ignore" });
    expect(mappingFromChoices(headers, { ...choices, Notes: "parent_phone" })).toEqual([
      { target: "parent_name", source_headers: ["First", "Last"] },
      { target: "parent_phone", source_headers: ["Notes"] },
      { target: "student_name", source_headers: ["Kid"] },
    ]);
  });
});
