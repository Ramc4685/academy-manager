import { redirect } from "next/navigation";

export default function AdminPauseRequestsPage() {
  redirect("/admin/requests?tab=pauses");
}
