import { redirect } from "next/navigation";

export default function AdminLevelUpQueuePage() {
  redirect("/admin/registrations?tab=level-ups");
}
