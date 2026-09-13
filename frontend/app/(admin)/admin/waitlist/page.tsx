import { redirect } from "next/navigation";

export default function AdminWaitlistPage() {
  redirect("/admin/inbox?tab=waitlist");
}
