/**
 * UIM6 — client-side parsing for the bulk parent invite dialog (#449).
 *
 * The backend's `POST /admin/users/bulk-invite` takes 1-100 `{email, display_name}`
 * rows and sends a real login-invite email per created parent, so every row an
 * admin pastes (or picks from a CSV) is validated and de-duplicated here BEFORE
 * it costs an email. Kept free of React so it can be unit-tested directly.
 */

/** Matches the backend's `BulkInviteRequest.users` max_length. */
export const BULK_INVITE_MAX_ROWS = 100;
/** Matches `BulkInviteItem.email` max_length. */
export const BULK_INVITE_MAX_EMAIL = 254;
/** Matches `BulkInviteItem.display_name` max_length. */
export const BULK_INVITE_MAX_NAME = 120;

export interface BulkInviteItem {
  email: string;
  display_name: string;
}

export interface ParsedBulkInviteRow extends BulkInviteItem {
  /** 1-based line number in the pasted text, for pointing at the bad row. */
  line: number;
  raw: string;
  /** Human-readable reason this row cannot be submitted, or null when it can. */
  error: string | null;
  /** True when an earlier row in the same batch already claimed this email. */
  duplicate: boolean;
}

export interface BulkInviteParseResult {
  rows: ParsedBulkInviteRow[];
  /** Rows that would be sent (error-free and not a duplicate). */
  validCount: number;
  invalidCount: number;
  duplicateCount: number;
  /** True when the sendable rows exceed what the endpoint accepts in one call. */
  overLimit: boolean;
}

// Deliberately loose: the authority on deliverability is the invite email, not
// a regex. This only catches the obvious paste mistakes (missing @, stray
// separators, a name landing in the email column).
const EMAIL_RE = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

function unquote(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function splitFields(line: string): string[] {
  return line.split(/[,\t;]/).map(unquote);
}

function looksLikeEmail(value: string): boolean {
  return value.includes("@");
}

/** "jane.doe@example.com" -> "Jane Doe", so a bare email list still submits. */
function nameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  const words = local
    .split(/[._\-+]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1));
  return words.join(" ") || local;
}

function isHeaderLine(fields: string[]): boolean {
  const first = (fields[0] ?? "").toLowerCase();
  const second = (fields[1] ?? "").toLowerCase();
  const headerish = new Set(["email", "e-mail", "email address", "name", "display name", "parent"]);
  return headerish.has(first) && (fields.length < 2 || headerish.has(second));
}

/**
 * Parse pasted text or CSV file contents into invite rows.
 *
 * Accepted per line: `email`, `email, name`, or `name, email` (comma, tab or
 * semicolon separated, optionally quoted). A leading header row is dropped.
 */
export function parseBulkInviteText(text: string): BulkInviteParseResult {
  const result: ParsedBulkInviteRow[] = [];
  const seen = new Set<string>();
  const lines = text.split(/\r?\n/);

  lines.forEach((rawLine, index) => {
    const raw = rawLine.trim();
    if (!raw) return;

    const fields = splitFields(raw).filter((field) => field.length > 0);
    if (fields.length === 0) return;
    if (result.length === 0 && isHeaderLine(fields)) return;

    const emailField = fields.find(looksLikeEmail) ?? fields[0];
    const nameField = fields.find((field) => field !== emailField && !looksLikeEmail(field));

    const email = emailField.toLowerCase();
    const displayName = nameField ? nameField : nameFromEmail(email);

    let error: string | null = null;
    if (!EMAIL_RE.test(email) || email.length > BULK_INVITE_MAX_EMAIL) {
      error = `Not a valid email address: "${emailField}"`;
    } else if (displayName.length < 1) {
      error = "Name is required";
    } else if (displayName.length > BULK_INVITE_MAX_NAME) {
      error = `Name is longer than ${BULK_INVITE_MAX_NAME} characters`;
    }

    const duplicate = error === null && seen.has(email);
    if (error === null && !duplicate) seen.add(email);

    result.push({
      line: index + 1,
      raw,
      email,
      display_name: displayName,
      error,
      duplicate,
    });
  });

  const invalidCount = result.filter((row) => row.error !== null).length;
  const duplicateCount = result.filter((row) => row.duplicate).length;
  const validCount = result.length - invalidCount - duplicateCount;

  return {
    rows: result,
    validCount,
    invalidCount,
    duplicateCount,
    overLimit: validCount > BULK_INVITE_MAX_ROWS,
  };
}

/** The rows that will actually be sent to the endpoint, in paste order. */
export function toBulkInviteItems(parsed: BulkInviteParseResult): BulkInviteItem[] {
  return parsed.rows
    .filter((row) => row.error === null && !row.duplicate)
    .map((row) => ({ email: row.email, display_name: row.display_name }));
}
