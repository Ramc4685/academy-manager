import { redirect } from "next/navigation";

export default function AdminPauseRequestsPage() {
  redirect("/admin/inbox?tab=pauses");
}
