export const brand = {
  companyName: "Marvy Labs",
  productName: "Academy Manager",
  productFullName: "Academy Manager",
  productDescriptor: "Badminton academy operations platform",
  copyrightYears: "2024-2026",
  legalOwner: "Marvy Labs",
  supportEmail: "ramchand4685@gmail.com",
  securityEmail: "ramchand4685@gmail.com",
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
