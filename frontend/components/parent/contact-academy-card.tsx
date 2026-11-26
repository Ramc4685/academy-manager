"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ContactLinks } from "@/components/ds/contact-links";
import { getParentAcademy } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";

/** D-18: the academy's phone, email, hours and address, always findable. */
export function ContactAcademyCard() {
  const { data: academy } = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  if (!academy) return null;
  return (
    <article
      className="rounded-2xl border border-rally-line bg-white p-4"
      data-testid="parent-contact-academy"
    >
      <h2 className="font-bold text-rally-ink text-[15px]">Contact the academy</h2>
      <p className="mt-1 text-sm font-semibold text-rally-ink">{academy.display_name}</p>
      <ContactLinks
        phone={academy.contact_phone}
        email={academy.contact_email}
        name={academy.display_name}
        className="mt-1 text-sm"
      />
      {academy.hours_text && <p className="mt-1 text-sm text-rally-muted">{academy.hours_text}</p>}
      {academy.address && <p className="mt-1 text-sm text-rally-muted">{academy.address}</p>}
      <Link
        href="/parent/messages#academy"
        className="mt-3 inline-flex min-h-touch items-center rounded-lg border border-rally-line bg-white px-4 text-sm font-semibold text-rally-ink hover:bg-rally-paper"
      >
        Message the academy
      </Link>
    </article>
  );
}
