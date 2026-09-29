const COPYRIGHT_START_YEAR = 2024;

function copyrightYears(): string {
  const endYear = Math.max(COPYRIGHT_START_YEAR, new Date().getFullYear());
  return `${COPYRIGHT_START_YEAR}-${endYear}`;
}

export const brand = {
  companyName: "Marvy Labs",
  productName: "CourtMastr",
  productFullName: "CourtMastr",
  productDescriptor: "Academy operations platform",
  copyrightYears: copyrightYears(),
  legalOwner: "Marvy Labs",
  supportEmail: "support@marvylabs.com",
  securityEmail: "security@marvylabs.com",
  publicSiteUrl: "https://academy.courtmastr.com",
  statusUrl: "https://api.academy.courtmastr.com/api/v2/healthz",
  legalLinks: {
    terms: "/terms",
    privacy: "/privacy",
    security: "/security",
  },
} as const;

export function copyrightNotice(): string {
  return `Copyright (c) ${brand.copyrightYears} ${brand.legalOwner}. All rights reserved.`;
}
