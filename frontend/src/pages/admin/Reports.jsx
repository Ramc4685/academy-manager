import { Download } from "lucide-react";
import { useAuth } from "../../contexts/AuthContext";

const REPORTS = [
  { key: "revenue", label: "Revenue", description: "All paid payments with student and session info." },
  { key: "pending-payments", label: "Pending payments", description: "All unpaid invoices with parent contact." },
  { key: "attendance", label: "Attendance", description: "All attendance markings (latest 5,000)." },
  { key: "coach-payouts", label: "Coach payouts", description: "All payouts with approval/payment state." },
  { key: "profit", label: "Profit by month", description: "Aggregated revenue, expenses, and net profit per month." },
  { key: "waivers", label: "Waivers", description: "Waiver acceptance records with version and text hash." },
];

export default function AdminReports() {
  const BASE = process.env.REACT_APP_BACKEND_URL;
  const downloadUrl = (k) => `${BASE}/api/reports/${k}.csv`;

  return (
    <div className="space-y-6" data-testid="admin-reports">
      <div>
        <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Reports</h1>
        <p className="text-sm text-slate-600 mt-1">Download CSV exports for finance and operations</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {REPORTS.map((r) => (
          <a
            key={r.key}
            href={downloadUrl(r.key)}
            data-testid={`download-${r.key}`}
            className="block bg-white border border-slate-200 rounded-xl p-6 hover:-translate-y-[2px] hover:shadow-md transition-all duration-200 group"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="font-display font-semibold tracking-tight text-slate-900">{r.label}</div>
                <p className="text-sm text-slate-600 mt-2">{r.description}</p>
              </div>
              <div className="p-2 rounded-lg bg-blue-50 group-hover:bg-blue-100 transition-colors">
                <Download className="w-5 h-5 text-blue-600" />
              </div>
            </div>
            <div className="mt-4 text-xs uppercase tracking-[0.18em] text-blue-600 font-semibold">Download CSV →</div>
          </a>
        ))}
      </div>
    </div>
  );
}
