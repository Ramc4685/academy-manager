import { Button } from "@/components/ds/button";
import { WaiverText } from "@/components/waivers/waiver-text";
import type { SignedWaiverCopy } from "@/lib/api/parent";

const PATH_LABEL = { adult: "Participant (18 or over)", minor: "Parent or guardian" } as const;

/**
 * The signed waiver as a document: the exact text that was signed, then the
 * signature and its audit trail. Printing (or "Save as PDF") prints only this.
 */
export function SignedWaiverDocument({
  copy,
  print = () => window.print(),
}: {
  copy: SignedWaiverCopy;
  print?: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex justify-end print:hidden">
        <Button type="button" variant="secondary" onClick={print}>
          Print or save as PDF
        </Button>
      </div>
      <article
        data-testid="signed-waiver-document"
        className="waiver-print space-y-6 rounded-2xl border border-rally-line bg-white p-6 text-sm leading-6 text-rally-ink"
      >
        <header className="space-y-1 border-b border-rally-line pb-4">
          <h1 className="font-display text-xl font-semibold">{copy.title || "Signed waiver"}</h1>
          <p className="text-rally-muted">
            {copy.version ? `Version ${copy.version} · ` : ""}Participant: {copy.student_name}
          </p>
        </header>

        <WaiverText body={copy.body} signedInitials={copy.initials ?? {}} />

        <section className="space-y-3 border-t border-rally-line pt-4">
          <h2 className="font-display text-base font-semibold">Electronic signature</h2>
          {copy.consent_text && <p className="italic">“{copy.consent_text}”</p>}
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <Row label="Signed by" value={copy.signer_name} />
            <Row label="Email" value={copy.signer_email} />
            {copy.signing_path && <Row label="Signed as" value={PATH_LABEL[copy.signing_path]} />}
            <Row label="Signed at" value={formatSignedAt(copy.signed_at)} />
            <Row label="IP address" value={copy.ip_address} />
            <Row label="Device" value={copy.user_agent} />
            <Row label="Signature ID" value={copy.waiver_signature_id} />
            <Row label="Document fingerprint (SHA-256)" value={copy.content_hash} mono />
          </dl>
        </section>
      </article>
      <style>{PRINT_CSS}</style>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-rally-muted">{label}</dt>
      <dd className={`break-all ${mono ? "font-mono text-xs" : ""}`}>{value || "Not recorded"}</dd>
    </div>
  );
}

export function formatSignedAt(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const local = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
  return `${local} (${date.toISOString().replace(".000", "")})`;
}

// Print only the document: the shell, nav and buttons stay off the paper.
const PRINT_CSS = `
@media print {
  html, body { background: #fff !important; }
  body * { visibility: hidden !important; }
  .waiver-print, .waiver-print * { visibility: visible !important; }
  .waiver-print { position: absolute !important; left: 0; top: 0; width: 100%; border: 0 !important; }
}
`;
