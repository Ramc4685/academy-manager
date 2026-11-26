import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * S69 (D-16): admin copy says "class" and "class date", never "session" or
 * "occurrence". Code names stay (`session_id`, `/admin/sessions`, `Session`
 * types), so this scan only flags the word where it reads as prose: inside a
 * phrase ("Edit session", "no sessions"), or alone as a quoted or JSX label
 * (`"Sessions"`, `>Session<`). Comments are skipped.
 */

const FRONTEND = path.resolve(__dirname, "..");
const ROOTS = [
  "app/(admin)",
  "components/admin",
  "components/messages",
  "components/announcements",
  "lib/format/hold-copy.ts",
  "lib/format/lifecycle-copy.ts",
];

const WORD = String.raw`(?:[Ss]essions?|[Oo]ccurrences?)`;
const PROSE = new RegExp(
  [
    String.raw`[A-Za-z]{2,} ${WORD}\b(?![.?(\[_=])`, // "Edit session", "no sessions"
    String.raw`\b${WORD} [a-z]{2,}`, // "session fee", "Sessions with"
    String.raw`>\s*${WORD}\s*<`, // <th>Session</th>
    String.raw`\} ${WORD}\b(?![.?(\[_=])`, // {count} sessions
    String.raw`\b${WORD}\{`, // session{n === 1 ? "" : "s"}
    // label: "Sessions". Lowercase quoted values ("session", "sessions") are
    // API values, tab ids and query keys, so only a capitalised label counts.
    String.raw`["'\`](?:Sessions?|Occurrences?)["'\`]`,
  ].join("|"),
);
// Code that happens to look like prose.
const CODE = new RegExp(
  String.raw`\b(?:const|let|of|in|return|await|typeof|as|new|function|type|interface|for|if|case|import|export|from|extends|keyof)\s+${WORD}\b`,
);
/** Reviewed exceptions: identifiers, API values and terms that are not ours. */
const ALLOWED = [
  /[Cc]heckout [Ss]ession/, // Stripe's own name for its object
];

function sourceFiles(entry: string): string[] {
  const full = path.join(FRONTEND, entry);
  if (statSync(full).isFile()) return [full];
  return readdirSync(full, { withFileTypes: true }).flatMap((child) =>
    sourceFiles(path.join(entry, child.name)),
  );
}

describe("admin copy says class, not session (S69)", () => {
  const files = ROOTS.flatMap(sourceFiles).filter(
    (file) => /\.(ts|tsx)$/.test(file) && !/\.test\.tsx?$/.test(file),
  );

  it("scans a non-trivial number of files", () => {
    expect(files.length).toBeGreaterThan(200);
  });

  it("finds no session or occurrence in user-facing strings", () => {
    const offenders = files.flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, i) => ({ line, at: `${path.relative(FRONTEND, file)}:${i + 1}` }))
        .filter(({ line }) => !/^\s*(\/\/|\*|\/\*|\{\/\*)/.test(line) && !line.includes("*/"))
        .filter(({ line }) => PROSE.test(line) && !CODE.test(line))
        .filter(({ line }) => !ALLOWED.some((ok) => ok.test(line)))
        .map(({ at, line }) => `${at}  ${line.trim()}`),
    );
    expect(offenders).toEqual([]);
  });
});
