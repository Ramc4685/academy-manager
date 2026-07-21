import { redirect } from "next/navigation";

export default function AdminParentsPage() {
  redirect("/admin/users?role=parent");
}
