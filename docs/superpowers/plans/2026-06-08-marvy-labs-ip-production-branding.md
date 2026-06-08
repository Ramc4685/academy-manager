# Marvy Labs IP Production Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Marvy Labs the visible copyright/IP owner, remove non-product V2 language from customer-facing surfaces, and add production-grade legal pages without breaking existing `/api/v2` compatibility.

**Architecture:** Centralize public brand/legal strings in one frontend module, then replace scattered landing/auth/metadata text with those constants. Keep internal versioned API paths (`/api/v2`), env vars (`V2_*`, `NEXT_PUBLIC_API_BASE=/api/v2`), and source directories (`backend/v2`) unchanged because they are runtime contracts, not customer-facing product claims. Add lightweight legal routes in the marketing route group so the landing footer has real destinations.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, FastAPI, repo Markdown docs, Node test runner, ruff/pytest/pnpm verification.

---

## Current Behavior Found

- `README.md` and `LICENSE` identify `CourtMastr`, `RamC Venkatasamy / CourtMastr`, or `Licensor` as the owner.
- `frontend/app/page.tsx` exposes `v2.0`, "v2 frontend", "Next v2", and a nonstandard `(c) 2026 - Academy Manager - v2.0` footer.
- `backend/v2/main.py` exposes OpenAPI title `Academy Manager v2`.
- `backend/pyproject.toml` and `frontend/README.md` describe the app as `v2`.
- There are no visible `terms`, `privacy`, `security`, or legal notice routes under `frontend/app`.
- `/api/v2` is used throughout production deployment, frontend BFF clients, tests, smoke checks, and docs. It must remain unchanged in this plan.

## Files Affected

- Create: `frontend/lib/brand.ts` for public product/legal constants.
- Create: `frontend/lib/brand.node-test.mjs` for constants regression coverage.
- Create: `frontend/app/(marketing)/legal.module.css` for shared legal page styling.
- Create: `frontend/app/(marketing)/terms/page.tsx`.
- Create: `frontend/app/(marketing)/privacy/page.tsx`.
- Create: `frontend/app/(marketing)/security/page.tsx`.
- Modify: `frontend/app/page.tsx` to remove public V2 text and add legal footer links.
- Modify: `frontend/app/layout.tsx` and `frontend/app/(marketing)/layout.tsx` to use production metadata.
- Modify: `frontend/app/(marketing)/login/page.tsx` and `frontend/app/(marketing)/register/page.tsx` to use the shared brand constants in their lockups.
- Modify: `frontend/public/manifest.webmanifest` for PWA install naming.
- Modify: `backend/v2/main.py` to expose a production OpenAPI title while keeping route prefixes.
- Modify: `backend/pyproject.toml` and `frontend/README.md` to remove externally confusing `v2` product wording.
- Modify: `README.md` and `LICENSE` to make Marvy Labs the owner and clarify product marks.
- Modify: `docs/test-results/active/2026-06-08-marvy-labs-ip-protection-and-production-branding-plan.md` through the ledger CLI only.

## Official Source Constraints

- U.S. Copyright Office FAQ says registration requires an application, fee, and nonreturnable deposit copy; software registration details are in Circular 61.
- U.S. Copyright Office notice guidance recognizes notice elements as the copyright word/symbol, year, and copyright owner.
- USPTO guidance treats names/logos/slogans used to identify goods or services as trademark or service-mark issues, not copyright issues.
- Engineering change must use accurate owner text, but final filing strategy and terms/legal language should be reviewed by counsel before production publication.

## Non-Goals

- Do not rename `backend/v2`, `frontend/lib/api/generated/v2.d.ts`, `/api/v2`, `V2_*` env vars, test names, or historical migration docs.
- Do not change production domains from `courtmastr.com` to a Marvy Labs domain in this plan.
- Do not deploy to production.
- Do not perform copyright or trademark filings from the repo.

## Risks

- If Marvy Labs is not the legal assignee/owner yet, the repo can make incorrect ownership claims. Confirm entity ownership before release.
- Legal page copy is a product draft, not legal advice. Counsel review is required before it becomes binding terms.
- Replacing visible "CourtMastr" everywhere would be risky if CourtMastr is still the product mark. This plan keeps CourtMastr as an optional product/service mark and makes Marvy Labs the owner.
- Removing `/api/v2` would break deployment and clients. This plan only removes public marketing/version labels.

---

### Task 1: Centralize Public Brand And Legal Constants

**Files:**
- Create: `frontend/lib/brand.ts`
- Create: `frontend/lib/brand.node-test.mjs`

- [ ] **Step 1: Add the public brand module**

Create `frontend/lib/brand.ts`:

```ts
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
```

- [ ] **Step 2: Add a regression test for public legal strings**

Create `frontend/lib/brand.node-test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";

import { brand, copyrightNotice } from "./brand.ts";

test("public brand owner is Marvy Labs", () => {
  assert.equal(brand.companyName, "Marvy Labs");
  assert.equal(brand.legalOwner, "Marvy Labs");
});

test("copyright notice uses standard ASCII notice format", () => {
  assert.equal(
    copyrightNotice(),
    "Copyright (c) 2024-2026 Marvy Labs. All rights reserved."
  );
});

test("public product copy does not expose implementation versioning", () => {
  const publicValues = [
    brand.companyName,
    brand.productName,
    brand.productFullName,
    brand.productDescriptor,
    copyrightNotice(),
  ].join(" ");

  assert.equal(/\bv2\b|v2\.0|Next v2/i.test(publicValues), false);
});
```

- [ ] **Step 3: Run the focused test and confirm it passes**

Run:

```bash
cd frontend
node --no-warnings --test lib/brand.node-test.mjs
```

Expected:

```txt
pass 1
pass 2
pass 3
```

- [ ] **Step 4: Commit Task 1**

```bash
git add frontend/lib/brand.ts frontend/lib/brand.node-test.mjs
git commit -m "feat(legal): centralize Marvy Labs brand constants"
```

---

### Task 2: Replace Landing Page V2 Labels With Production Copy

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/landing.module.css`

- [ ] **Step 1: Import brand constants**

In `frontend/app/page.tsx`, add:

```ts
import { brand, copyrightNotice } from "@/lib/brand";
```

Keep the existing `Link` and CSS imports.

- [ ] **Step 2: Replace topbar and hero version labels**

Replace:

```tsx
<span className={styles.b1}>Academy Manager</span>
<span className={styles.b2}>Badminton - Operations</span>
```

with:

```tsx
<span className={styles.b1}>{brand.productName}</span>
<span className={styles.b2}>Badminton - Operations</span>
```

Replace:

```tsx
v2.0 - Online
```

with:

```tsx
Production - Online
```

Replace:

```tsx
<span className={styles.badge}>v2.0</span>
Three roles - one operations platform
```

with:

```tsx
<span className={styles.badge}>Live</span>
Three roles - one operations platform
```

Replace:

```tsx
Academy Manager is the v2 frontend for coaches, parents, and admins. Mark
attendance, take payments, manage waitlists, and run the academy from one app.
```

with:

```tsx
{brand.productName} gives coaches, parents, and admins one production workspace.
Mark attendance, take payments, manage waitlists, and run the academy from one app.
```

- [ ] **Step 3: Replace bottom strip implementation language**

Replace:

```tsx
<div className={styles.v}>Next v2</div>
<div className={styles.s}>The only frontend target after cutover</div>
```

with:

```tsx
<div className={styles.v}>Unified</div>
<div className={styles.s}>One web app for every academy role</div>
```

- [ ] **Step 4: Replace the footer with legal links**

Replace the footer block with:

```tsx
<div className={styles.foot}>
  <span>{copyrightNotice()}</span>
  <div className={styles.right}>
    <Link href="/register">Register</Link>
    <Link href={brand.legalLinks.terms}>Terms</Link>
    <Link href={brand.legalLinks.privacy}>Privacy</Link>
    <Link href={brand.legalLinks.security}>Security</Link>
    <a href={brand.statusUrl}>Status</a>
    <Link href="/login">Sign in</Link>
  </div>
</div>
```

- [ ] **Step 5: Make footer links wrap cleanly on mobile**

In `frontend/app/landing.module.css`, find `.foot` and `.foot .right`. If they do not already support wrapping, use this exact shape:

```css
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 32px;
  margin-top: 40px;
  border-top: 1px solid #e2e8f0;
  color: #64748b;
  font-family: var(--font-mono), ui-monospace, monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.foot .right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 14px;
}
```

If the existing media query for small screens already changes `.foot`, preserve the responsive intent and ensure the footer never overflows at `390px` width.

- [ ] **Step 6: Run focused checks**

Run:

```bash
cd frontend
node --no-warnings --test lib/brand.node-test.mjs
pnpm typecheck
pnpm lint
```

Expected:

```txt
brand.node-test.mjs passes
pnpm typecheck passes
pnpm lint passes
```

- [ ] **Step 7: Commit Task 2**

```bash
git add frontend/app/page.tsx frontend/app/landing.module.css
git commit -m "fix(marketing): remove visible v2 launch labels"
```

---

### Task 3: Add Production Legal Routes

**Files:**
- Create: `frontend/app/(marketing)/legal.module.css`
- Create: `frontend/app/(marketing)/terms/page.tsx`
- Create: `frontend/app/(marketing)/privacy/page.tsx`
- Create: `frontend/app/(marketing)/security/page.tsx`

- [ ] **Step 1: Add shared legal page styling**

Create `frontend/app/(marketing)/legal.module.css`:

```css
.page {
  min-height: 100vh;
  background: #f8fafc;
  color: #0f172a;
  font-family: var(--font-manrope), system-ui, sans-serif;
}

.shell {
  width: min(920px, calc(100% - 32px));
  margin: 0 auto;
  padding: 40px 0 64px;
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 24px;
  border-bottom: 1px solid #e2e8f0;
}

.brand {
  font-family: var(--font-outfit), system-ui, sans-serif;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  text-decoration: none;
}

.navLinks {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 13px;
  font-weight: 700;
}

.navLinks a,
.backLink {
  color: #2563eb;
  text-decoration: none;
}

.header {
  padding: 48px 0 28px;
}

.eyebrow {
  margin: 0 0 12px;
  color: #64748b;
  font-family: var(--font-mono), ui-monospace, monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.title {
  margin: 0;
  font-family: var(--font-outfit), system-ui, sans-serif;
  font-size: clamp(40px, 8vw, 72px);
  line-height: 0.95;
  letter-spacing: 0;
}

.intro {
  max-width: 720px;
  margin: 20px 0 0;
  color: #475569;
  font-size: 17px;
  line-height: 1.65;
}

.content {
  display: grid;
  gap: 24px;
}

.section {
  border-top: 1px solid #e2e8f0;
  padding-top: 24px;
}

.section h2 {
  margin: 0 0 10px;
  font-family: var(--font-outfit), system-ui, sans-serif;
  font-size: 22px;
  letter-spacing: 0;
}

.section p,
.section li {
  color: #334155;
  font-size: 15px;
  line-height: 1.7;
}

.section ul {
  margin: 10px 0 0;
  padding-left: 20px;
}

.notice {
  border: 1px solid #fde68a;
  background: #fef9c3;
  color: #713f12;
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 14px;
  line-height: 1.6;
}

.footer {
  margin-top: 40px;
  padding-top: 24px;
  border-top: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
```

- [ ] **Step 2: Add Terms page**

Create `frontend/app/(marketing)/terms/page.tsx`:

```tsx
import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";
import styles from "../legal.module.css";

export const metadata = {
  title: `Terms of Service | ${brand.productName}`,
  description: `Terms for using ${brand.productName}, owned by ${brand.companyName}.`,
};

export default function TermsPage() {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Legal">
          <Link href="/" className={styles.brand}>{brand.productName}</Link>
          <div className={styles.navLinks}>
            <Link href="/privacy">Privacy</Link>
            <Link href="/security">Security</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>Terms of Service</h1>
          <p className={styles.intro}>
            These terms describe access to {brand.productName}, the hosted academy
            operations service owned and operated by {brand.companyName}.
          </p>
        </header>

        <div className={styles.content}>
          <p className={styles.notice}>
            Draft legal terms. Review with counsel before treating this page as a
            binding customer agreement.
          </p>

          <section className={styles.section}>
            <h2>Service Access</h2>
            <p>
              Customers and authorized users receive a limited, revocable,
              non-exclusive, non-transferable right to access the hosted service for
              academy operations. No ownership interest in the software, source code,
              designs, workflows, data schemas, or documentation is transferred.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Ownership</h2>
            <p>
              {brand.companyName} owns the software, service design, source code,
              documentation, data schemas, product experience, and related assets
              unless a signed agreement says otherwise. {copyrightNotice()}
            </p>
          </section>

          <section className={styles.section}>
            <h2>Restrictions</h2>
            <ul>
              <li>Do not copy, mirror, scrape, resell, sublicense, or host the service.</li>
              <li>Do not reverse engineer, decompile, or bypass access controls.</li>
              <li>Do not use the service or repository contents to train machine-learning models.</li>
              <li>Do not interfere with authentication, billing, email, security, or tenant isolation.</li>
            </ul>
          </section>

          <section className={styles.section}>
            <h2>Customer Data</h2>
            <p>
              Academy records, student records, attendance, billing, and messages
              remain customer data. {brand.companyName} processes customer data to
              provide, secure, support, and improve the service.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Contact</h2>
            <p>
              Questions about these terms should be sent to{" "}
              <a href={`mailto:${brand.supportEmail}`}>{brand.supportEmail}</a>.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
```

- [ ] **Step 3: Add Privacy page**

Create `frontend/app/(marketing)/privacy/page.tsx`:

```tsx
import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";
import styles from "../legal.module.css";

export const metadata = {
  title: `Privacy | ${brand.productName}`,
  description: `Privacy overview for ${brand.productName}, owned by ${brand.companyName}.`,
};

export default function PrivacyPage() {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Legal">
          <Link href="/" className={styles.brand}>{brand.productName}</Link>
          <div className={styles.navLinks}>
            <Link href="/terms">Terms</Link>
            <Link href="/security">Security</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>Privacy</h1>
          <p className={styles.intro}>
            This page explains the categories of information {brand.productName}
            handles for academy owners, coaches, parents, and students.
          </p>
        </header>

        <div className={styles.content}>
          <p className={styles.notice}>
            Draft privacy summary. Review with counsel before production publication.
          </p>

          <section className={styles.section}>
            <h2>Information We Process</h2>
            <p>
              The service may process account information, academy membership records,
              student profiles, attendance, billing records, messages, support requests,
              authentication events, device information, and audit logs.
            </p>
          </section>

          <section className={styles.section}>
            <h2>How Information Is Used</h2>
            <p>
              Information is used to operate the service, verify identity, enforce roles,
              process payments, send transactional messages, support academy workflows,
              prevent abuse, and maintain security and auditability.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Service Providers</h2>
            <p>
              The production service uses managed providers for hosting, database,
              authentication, payments, email, monitoring, and backups. Access to data is
              limited to what is needed to provide and secure the service.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Requests</h2>
            <p>
              Privacy or data requests should be sent to{" "}
              <a href={`mailto:${brand.supportEmail}`}>{brand.supportEmail}</a>.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Add Security page**

Create `frontend/app/(marketing)/security/page.tsx`:

```tsx
import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";
import styles from "../legal.module.css";

export const metadata = {
  title: `Security | ${brand.productName}`,
  description: `Security overview for ${brand.productName}, owned by ${brand.companyName}.`,
};

export default function SecurityPage() {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Legal">
          <Link href="/" className={styles.brand}>{brand.productName}</Link>
          <div className={styles.navLinks}>
            <Link href="/terms">Terms</Link>
            <Link href="/privacy">Privacy</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>Security</h1>
          <p className={styles.intro}>
            {brand.productName} is built as a hosted SaaS product with role-aware
            access controls, tenant isolation, encrypted transport, and audited
            operational workflows.
          </p>
        </header>

        <div className={styles.content}>
          <section className={styles.section}>
            <h2>Controls</h2>
            <ul>
              <li>HTTPS-only production access.</li>
              <li>Firebase Authentication with server-side token verification.</li>
              <li>Role and membership checks for admin, coach, and parent workflows.</li>
              <li>Explicit CORS allow-listing.</li>
              <li>Audit logging for sensitive authentication, admin, and payment events.</li>
            </ul>
          </section>

          <section className={styles.section}>
            <h2>Responsible Disclosure</h2>
            <p>
              Send security reports to{" "}
              <a href={`mailto:${brand.securityEmail}?subject=SECURITY%20DISCLOSURE`}>
                {brand.securityEmail}
              </a>{" "}
              with the subject line SECURITY DISCLOSURE. Do not access, modify, or
              exfiltrate data that is not yours.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
```

- [ ] **Step 5: Run route build checks**

Run:

```bash
cd frontend
pnpm typecheck
pnpm lint
pnpm build
```

Expected:

```txt
typecheck passes
lint passes
build passes and includes /terms, /privacy, /security routes
```

- [ ] **Step 6: Commit Task 3**

```bash
git add 'frontend/app/(marketing)/legal.module.css' 'frontend/app/(marketing)/terms/page.tsx' 'frontend/app/(marketing)/privacy/page.tsx' 'frontend/app/(marketing)/security/page.tsx'
git commit -m "feat(legal): add public terms privacy and security pages"
```

---

### Task 4: Update Metadata, Auth Lockups, And PWA Manifest

**Files:**
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/(marketing)/layout.tsx`
- Modify: `frontend/app/(marketing)/login/page.tsx`
- Modify: `frontend/app/(marketing)/register/page.tsx`
- Modify: `frontend/public/manifest.webmanifest`

- [ ] **Step 1: Use brand constants in root metadata**

In `frontend/app/layout.tsx`, import:

```ts
import { brand } from "@/lib/brand";
```

Replace metadata with:

```ts
export const metadata: Metadata = {
  title: brand.productName,
  description: `${brand.productName} is a production operations platform for coaches, parents, and admins.`,
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: brand.productName,
  },
};
```

- [ ] **Step 2: Use brand constants in marketing metadata**

In `frontend/app/(marketing)/layout.tsx`, import:

```ts
import { brand } from "@/lib/brand";
```

Replace:

```ts
export const metadata: Metadata = {
  title: "Academy Manager",
};
```

with:

```ts
export const metadata: Metadata = {
  title: brand.productName,
  description: brand.productDescriptor,
};
```

- [ ] **Step 3: Update login and register brand lockups**

In both `frontend/app/(marketing)/login/page.tsx` and `frontend/app/(marketing)/register/page.tsx`, import:

```ts
import { brand } from "@/lib/brand";
```

Inside `BrandLockup`, replace the hardcoded text:

```tsx
<div className={`font-display text-lg font-bold leading-6 ${text}`}>
  Badminton
</div>
<div className={`text-[11px] uppercase ${subtext}`}>
  Academy Manager
</div>
```

with:

```tsx
<div className={`font-display text-lg font-bold leading-6 ${text}`}>
  {brand.productName}
</div>
<div className={`text-[11px] uppercase ${subtext}`}>
  {brand.companyName}
</div>
```

- [ ] **Step 4: Update the PWA manifest**

In `frontend/public/manifest.webmanifest`, replace the top fields with:

```json
{
  "name": "Academy Manager",
  "short_name": "Academy",
  "description": "Production academy operations for coaches, parents, and admins.",
```

Keep the existing icons, shortcuts, categories, `start_url`, `scope`, `display`, colors, and orientation.

- [ ] **Step 5: Run focused checks**

Run:

```bash
cd frontend
node --no-warnings --test lib/brand.node-test.mjs
pnpm typecheck
pnpm lint
pnpm build
```

Expected:

```txt
brand.node-test.mjs passes
typecheck passes
lint passes
build passes
```

- [ ] **Step 6: Commit Task 4**

```bash
git add frontend/app/layout.tsx 'frontend/app/(marketing)/layout.tsx' 'frontend/app/(marketing)/login/page.tsx' 'frontend/app/(marketing)/register/page.tsx' frontend/public/manifest.webmanifest
git commit -m "fix(frontend): align metadata with Marvy Labs branding"
```

---

### Task 5: Update Repository IP Claims And Product Documentation

**Files:**
- Modify: `README.md`
- Modify: `LICENSE`
- Modify: `frontend/README.md`

- [ ] **Step 1: Update README title and ownership notice**

In `README.md`, keep the product heading if `CourtMastr Academy Manager` remains the service mark. Replace the notice block with:

```md
> Proprietary software. Copyright (c) 2024-2026 Marvy Labs. All rights reserved.
> Access to this repository does **not** grant a license to use, copy, or
> redistribute the software. See [LICENSE](LICENSE).
```

Update the `Trademarks` section to:

```md
### Trademarks

"Academy Manager", "CourtMastr", the CourtMastr logo, and related product
names or marks are trademarks or service marks of Marvy Labs. All other marks
belong to their respective owners.
```

- [ ] **Step 2: Update LICENSE owner and licensor text**

Replace the opening of `LICENSE` with:

```txt
Academy Manager - Proprietary Software License
Copyright (c) 2024-2026 Marvy Labs. All rights reserved.

THIS SOFTWARE IS PROPRIETARY AND CONFIDENTIAL.

1. Ownership. The Academy Manager source code, binaries, schemas, designs,
   documentation, and all related assets (collectively, the "Software") are
   the exclusive property of Marvy Labs ("Licensor"). The Software is licensed,
   not sold. No title or ownership interest is transferred.
```

Replace section 4 heading/body opening with:

```txt
4. Customer / Subscriber Use. Customers of the hosted Academy Manager service
   ("Service") receive only the limited, non-exclusive, non-transferable,
   revocable right to access and use the Service in accordance with the
   separately executed subscription agreement, order form, or terms of service
   governing their account. That right does not extend to the Software itself.
```

Replace section 6 with:

```txt
6. Trademarks. "Academy Manager", "CourtMastr", the CourtMastr logo, and
   related names and marks are trademarks or service marks of the Licensor. No
   license to any trademark or service mark is granted.
```

Keep the rest of the license restrictions intact unless counsel requests changes.

- [ ] **Step 3: Update frontend README wording**

In `frontend/README.md`, replace:

```md
Next.js 15 App Router PWA for academy-manager v2. See [ADR-0002](../docs/adr/0002-nextjs-app-router.md).
```

with:

```md
Next.js 15 App Router PWA for Academy Manager. See [ADR-0002](../docs/adr/0002-nextjs-app-router.md).
```

- [ ] **Step 4: Run docs/brand sweep**

Run:

```bash
rg -n "RamC Venkatasamy|Copyright \\(c\\).*CourtMastr|Academy Manager v2|v2 frontend|v2\\.0|Next v2" README.md LICENSE frontend backend/pyproject.toml backend/v2/main.py
```

Expected:

```txt
Only backend/internal version references remain after Task 6; no README, LICENSE, frontend, or landing matches for public V2 labels.
```

- [ ] **Step 5: Commit Task 5**

```bash
git add README.md LICENSE frontend/README.md
git commit -m "docs(legal): make Marvy Labs the software owner"
```

---

### Task 6: Rename Public Backend Metadata Without Changing API Paths

**Files:**
- Modify: `backend/v2/main.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Update FastAPI metadata**

In `backend/v2/main.py`, replace:

```py
app = FastAPI(
    title="Academy Manager v2",
    version="2.0.0",
    lifespan=_lifespan,
)
```

with:

```py
app = FastAPI(
    title="Academy Manager API",
    version="2.0.0",
    lifespan=_lifespan,
)
```

Do not change any `app.include_router(..., prefix="/api/v2")` lines.

- [ ] **Step 2: Update backend package description**

In `backend/pyproject.toml`, replace:

```toml
description = "Academy Manager v2 backend"
```

with:

```toml
description = "Academy Manager backend"
```

- [ ] **Step 3: Add or update a focused backend metadata assertion**

If an existing FastAPI app metadata test exists, update it. If not, add this assertion to the nearest interface test file that already imports `create_app`; otherwise create `backend/v2/tests/interface/test_app_metadata.py`:

```py
from backend.v2.main import create_app


def test_openapi_title_is_public_product_name() -> None:
    app = create_app()

    assert app.title == "Academy Manager API"
    assert app.version == "2.0.0"
```

- [ ] **Step 4: Run focused backend checks**

Run:

```bash
cd backend
.venv/bin/pytest v2/tests/interface/test_app_metadata.py -q
.venv/bin/ruff check v2
.venv/bin/ruff format --check v2
```

Expected:

```txt
metadata test passes
ruff check passes
ruff format --check passes
```

- [ ] **Step 5: Commit Task 6**

```bash
git add backend/v2/main.py backend/pyproject.toml backend/v2/tests/interface/test_app_metadata.py
git commit -m "fix(api): remove v2 from public OpenAPI title"
```

---

### Task 7: Final Brand Sweep And Production Verification

**Files:**
- Modify: `docs/test-results/active/2026-06-08-marvy-labs-ip-protection-and-production-branding-plan.md` through `scripts/dev/test_result.py`

- [ ] **Step 1: Log implementation details to the test ledger**

Run:

```bash
scripts/dev/test_result.py log marvy-labs-ip-protection-and-production-branding-plan --agent main --status working --message "Implemented Marvy Labs legal owner constants, public legal pages, visible V2 copy removal, repo legal notice updates, and public API metadata cleanup."
```

- [ ] **Step 2: Run targeted public-text sweeps**

Run:

```bash
rg -n "v2 frontend|v2\\.0|Next v2|Academy Manager v2|RamC Venkatasamy|Copyright \\(c\\).*CourtMastr" frontend README.md LICENSE backend/v2/main.py backend/pyproject.toml
```

Expected:

```txt
No matches.
```

Run:

```bash
rg -n "/api/v2|backend/v2|V2_|NEXT_PUBLIC_API_BASE=/api/v2" README.md DEPLOYMENT.md frontend backend docs/agent docs/tickets
```

Expected:

```txt
Matches remain in deployment, tests, API clients, and internal architecture docs. This confirms internal versioned contracts were not renamed.
```

- [ ] **Step 3: Run frontend full verification**

Run:

```bash
cd frontend
node --no-warnings --test lib/brand.node-test.mjs
pnpm typecheck
pnpm lint
pnpm build
```

Expected:

```txt
brand tests pass
typecheck passes
lint passes
build passes
```

- [ ] **Step 4: Run backend focused verification**

Run:

```bash
cd backend
.venv/bin/pytest v2/tests/interface/test_app_metadata.py -q
.venv/bin/ruff check v2
.venv/bin/ruff format --check v2
```

Expected:

```txt
metadata test passes
ruff check passes
ruff format --check passes
```

- [ ] **Step 5: Browser smoke the public pages**

Start the local frontend:

```bash
cd frontend
PORT=3001 pnpm dev
```

Open:

```txt
http://localhost:3001/
http://localhost:3001/terms
http://localhost:3001/privacy
http://localhost:3001/security
http://localhost:3001/login
http://localhost:3001/register
```

Expected:

```txt
Landing page has no visible v2/v2.0/Next v2 wording.
Footer shows Copyright (c) 2024-2026 Marvy Labs. All rights reserved.
Terms, Privacy, and Security pages render without console errors.
Login and Register show Academy Manager with Marvy Labs secondary text.
Footer/legal links fit at 390px mobile width without horizontal overflow.
```

- [ ] **Step 6: Record verification in the ledger**

Run one `verify` command per completed block:

```bash
scripts/dev/test_result.py verify marvy-labs-ip-protection-and-production-branding-plan --message "Frontend brand tests, typecheck, lint, and build passed."
scripts/dev/test_result.py verify marvy-labs-ip-protection-and-production-branding-plan --message "Backend metadata test and ruff checks passed."
scripts/dev/test_result.py verify marvy-labs-ip-protection-and-production-branding-plan --message "Browser smoke verified landing, terms, privacy, security, login, register, and 390px mobile footer."
```

- [ ] **Step 7: Commit final ledger updates**

```bash
git add docs/test-results/active/2026-06-08-marvy-labs-ip-protection-and-production-branding-plan.md test_result.md
git commit -m "test: record Marvy Labs branding verification"
```

---

## Final PR Checklist

- [ ] `git status --short --branch` shows only intentional committed changes.
- [ ] `git diff origin/main...HEAD --stat` contains only legal/brand/public metadata files, legal pages, focused tests, and ledger updates.
- [ ] No production deploy commands were run.
- [ ] No secrets or `.env` files were changed.
- [ ] Internal `/api/v2` compatibility paths remain unchanged.
- [ ] Counsel/owner review is requested before relying on legal pages or filing copyright/trademark claims.

## Self-Review

- Spec coverage: The plan covers Marvy Labs ownership, copyright notice, visible V2 removal, production legal links/pages, metadata cleanup, and verification.
- Placeholder scan: No TBD, TODO, "fill in details", or undefined future work remains.
- Type consistency: `brand`, `copyrightNotice`, `brand.legalLinks`, and route paths are consistent across tasks.
