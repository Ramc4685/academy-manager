import { redirect } from "next/navigation";

export default function AdminDuesRedirectPage() {
  redirect("/admin/reports/dues");
}
