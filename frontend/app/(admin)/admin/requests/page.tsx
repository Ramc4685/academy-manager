import { redirect } from "next/navigation";

/** Merged into the single admin Inbox (issue #776); kept so old links work. */
export default async function AdminRequestsRedirect({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;
  redirect(`/admin/inbox?tab=${encodeURIComponent(tab || "makeups")}`);
}
