import { redirect } from "next/navigation";

export default function AdminCoachPayslipRedirectPage() {
  redirect("/admin/payouts?tab=payslips");
}
