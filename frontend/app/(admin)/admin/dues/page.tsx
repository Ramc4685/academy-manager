import { redirect } from "next/navigation";

export default function AdminDuesRedirect() {
  redirect("/admin/reports/dues");
}
