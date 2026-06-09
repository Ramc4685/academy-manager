export type StudentProgressReturnLink = {
  href: string;
  label: string;
};

type BuildStudentProgressHrefOptions = {
  studentId: string;
  programId?: string | null;
  returnTo?: string | null;
  returnLabel?: string | null;
};

const DEFAULT_RETURN_LINK: StudentProgressReturnLink = {
  href: "/admin/students",
  label: "All students",
};

export function buildStudentProgressHref({
  studentId,
  programId,
  returnTo,
  returnLabel,
}: BuildStudentProgressHrefOptions): string {
  const params = new URLSearchParams();

  if (programId) {
    params.set("program_id", programId);
  }
  if (returnTo) {
    params.set("return_to", returnTo);
  }
  if (returnLabel) {
    params.set("return_label", returnLabel);
  }

  const query = params.toString();
  const base = `/admin/students/${encodeURIComponent(studentId)}/progress`;
  return query ? `${base}?${query}` : base;
}

export function resolveStudentProgressReturn({
  returnTo,
  returnLabel,
}: {
  returnTo?: string | null;
  returnLabel?: string | null;
}): StudentProgressReturnLink {
  if (!returnTo || !isSafeAdminReturnPath(returnTo)) {
    return DEFAULT_RETURN_LINK;
  }

  return {
    href: returnTo,
    label: normalizedReturnLabel(returnLabel),
  };
}

function isSafeAdminReturnPath(returnTo: string): boolean {
  if (returnTo.startsWith("//") || returnTo.includes("://")) {
    return false;
  }

  try {
    const url = new URL(returnTo, "https://academy.local");
    return url.origin === "https://academy.local" && url.pathname.startsWith("/admin");
  } catch {
    return false;
  }
}

function normalizedReturnLabel(returnLabel?: string | null): string {
  const label = returnLabel?.trim();
  return label || DEFAULT_RETURN_LINK.label;
}
