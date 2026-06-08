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
          <Link href="/" className={styles.brand}>
            {brand.productName}
          </Link>
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
            These terms describe access to {brand.productName}, the hosted academy operations
            service owned and operated by {brand.companyName}.
          </p>
        </header>

        <div className={styles.content}>
          <p className={styles.notice}>
            Draft legal terms. Review with counsel before treating this page as a binding customer
            agreement.
          </p>

          <section className={styles.section}>
            <h2>Service Access</h2>
            <p>
              Customers and authorized users receive a limited, revocable, non-exclusive,
              non-transferable right to access the hosted service for academy operations. No
              ownership interest in the software, source code, designs, workflows, data schemas, or
              documentation is transferred.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Ownership</h2>
            <p>
              {brand.companyName} owns the software, service design, source code, documentation,
              data schemas, product experience, and related assets unless a signed agreement says
              otherwise. {copyrightNotice()}
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
              Academy records, student records, attendance, billing, and messages remain customer
              data. {brand.companyName} processes customer data to provide, secure, support, and
              improve the service.
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
