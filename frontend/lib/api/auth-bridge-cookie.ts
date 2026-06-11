const BFF_IDENTITY_COOKIE = "__cm_identity";

export function setBffIdentityCookie(token: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${BFF_IDENTITY_COOKIE}=${encodeURIComponent(
    token
  )}; ${baseCookieAttributes(3600)}`;
}

export function clearBffIdentityCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${BFF_IDENTITY_COOKIE}=; ${baseCookieAttributes(0)}`;
}

function baseCookieAttributes(maxAgeSeconds: number): string {
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  return `Path=/; SameSite=Strict; Max-Age=${maxAgeSeconds}${secure}`;
}
