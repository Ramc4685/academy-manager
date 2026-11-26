/** S23: the register form's password rule and its reload-safe draft. */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_RULE = `At least ${PASSWORD_MIN_LENGTH} characters.`;

export function passwordRuleError(password: string): string | null {
  if (password.length >= PASSWORD_MIN_LENGTH) return null;
  return `Your password needs at least ${PASSWORD_MIN_LENGTH} characters (it has ${password.length}).`;
}

const DRAFT_KEY = "cm_register_draft";

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Keeps only the email across a reload. The password is never stored. */
export function saveRegisterDraft(storage: DraftStorage | null, email: string): void {
  try {
    if (!storage) return;
    if (email) storage.setItem(DRAFT_KEY, JSON.stringify({ email }));
    else storage.removeItem(DRAFT_KEY);
  } catch {
    // Private mode or blocked storage: the form still works, it just forgets.
  }
}

export function loadRegisterDraft(storage: DraftStorage | null): string {
  try {
    const raw = storage?.getItem(DRAFT_KEY);
    const email = raw ? (JSON.parse(raw) as { email?: unknown }).email : "";
    return typeof email === "string" ? email : "";
  } catch {
    return "";
  }
}

export function clearRegisterDraft(storage: DraftStorage | null): void {
  saveRegisterDraft(storage, "");
}

export function sessionDraftStorage(): DraftStorage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}
