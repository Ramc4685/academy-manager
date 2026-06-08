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
          <Link href="/" className={styles.brand}>
            {brand.productName}
          </Link>
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
            This page explains the categories of information {brand.productName} handles for academy
            owners, coaches, parents, and students.
          </p>
        </header>

        <div className={styles.content}>
          <p className={styles.notice}>
            Draft privacy summary. Review with counsel before production publication.
          </p>

          <section className={styles.section}>
            <h2>Information We Process</h2>
            <p>
              The service may process account information, academy membership records, student
              profiles, attendance, billing records, messages, support requests, authentication
              events, device information, and audit logs.
            </p>
          </section>

          <section className={styles.section}>
            <h2>How Information Is Used</h2>
            <p>
              Information is used to operate the service, verify identity, enforce roles, process
              payments, send transactional messages, support academy workflows, prevent abuse, and
              maintain security and auditability.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Service Providers</h2>
            <p>
              The production service uses managed providers for hosting, database, authentication,
              payments, email, monitoring, and backups. Access to data is limited to what is needed
              to provide and secure the service.
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
