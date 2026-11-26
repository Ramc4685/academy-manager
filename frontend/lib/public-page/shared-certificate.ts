/**
 * Server-side read of `GET /api/v2/public/certificates/{token}` for `/c/[token]`
 * (L5B): a certificate a parent chose to share. Same anonymous, host-forwarding
 * headers as the academy page read (`buildPublicAcademyRequestHeaders`); the
 * backend picks the academy from the host, never from the token. `no-store`:
 * the URL is the same on every host, and a parent's "stop sharing" must take
 * effect on the next load.
 */

import { cache } from "react";
import { headers } from "next/headers";

import { resolveBffApiOrigin } from "@/lib/api/proxy-origin";

import { isPlatformProductHost } from "./host";
import { buildPublicAcademyRequestHeaders } from "./server-fetch";
import type { PublicBrand } from "./types";
import { formatInAcademyZone } from "@/lib/format/academy-time";

const FETCH_TIMEOUT_MS = 5_000;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,64}$/;

export interface SharedCertificate {
  academy: PublicBrand;
  recipient_name: string;
  level_name: string;
  level_number: number | null;
  level_color: string | null;
  cert_number: string;
  /** `YYYY-MM-DD` in the academy's timezone. */
  issued_on: string;
}

export type SharedCertificateResult =
  | { kind: "found"; certificate: SharedCertificate }
  | { kind: "not_found" }
  | { kind: "unavailable" };

export function classifySharedCertificateResponse(
  status: number,
  body: unknown,
): SharedCertificateResult {
  if (status === 404) return { kind: "not_found" };
  if (status !== 200 || !body || typeof body !== "object")
    return { kind: "unavailable" };
  const cert = body as Partial<SharedCertificate>;
  if (
    typeof cert.recipient_name !== "string" ||
    typeof cert.level_name !== "string" ||
    typeof cert.cert_number !== "string" ||
    typeof cert.issued_on !== "string" ||
    !cert.academy ||
    typeof cert.academy.name !== "string"
  ) {
    return { kind: "unavailable" };
  }
  return {
    kind: "found",
    certificate: {
      ...(cert as SharedCertificate),
      level_number: cert.level_number ?? null,
      level_color: cert.level_color ?? null,
    },
  };
}

async function load(token: string): Promise<SharedCertificateResult> {
  if (!TOKEN_RE.test(token)) return { kind: "not_found" };
  const inbound = await headers();
  if (isPlatformProductHost(inbound.get("host"), process.env))
    return { kind: "not_found" };
  const protocol = process.env.NODE_ENV === "production" ? "https:" : "http:";
  const target = new URL(
    `/api/v2/public/certificates/${encodeURIComponent(token)}`,
    resolveBffApiOrigin(process.env),
  );
  try {
    const response = await fetch(target, {
      method: "GET",
      headers: buildPublicAcademyRequestHeaders(new Headers(inbound), protocol),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    let body: unknown = null;
    if (response.status === 200) {
      try {
        body = await response.json();
      } catch {
        body = null;
      }
    }
    return classifySharedCertificateResponse(response.status, body);
  } catch {
    return { kind: "unavailable" };
  }
}

/** One backend read per request, shared by the page and `generateMetadata`. */
export const loadSharedCertificate = cache(load);

/** "October 30, 2026" from the backend's academy-local `YYYY-MM-DD`. */
export function formatIssuedOn(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return formatInAcademyZone(Date.UTC(y, m - 1, d), "UTC", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}
