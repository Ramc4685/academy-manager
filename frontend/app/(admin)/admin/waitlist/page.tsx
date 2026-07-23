import { redirect } from "next/navigation";

export default function AdminWaitlistPage() {
  redirect("/admin/registrations?tab=waitlist");
}
