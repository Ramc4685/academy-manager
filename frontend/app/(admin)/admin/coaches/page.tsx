import { redirect } from "next/navigation";

export default function AdminCoachesPage() {
  redirect("/admin/users?role=coach");
}
