import { redirect } from "next/navigation";

export default function AdminLevelUpQueuePage() {
  redirect("/admin/inbox?tab=level-ups");
}
