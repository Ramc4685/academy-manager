import { redirect } from "next/navigation";

export default function SelfServiceSettingsRedirect() {
  redirect("/admin/settings?panel=self-service");
}
