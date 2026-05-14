export const StatusBadge = ({ status }) => {
  const map = {
    active: "bg-emerald-100 text-emerald-700 border-emerald-200",
    paid: "bg-emerald-100 text-emerald-700 border-emerald-200",
    approved: "bg-emerald-100 text-emerald-700 border-emerald-200",
    present: "bg-emerald-100 text-emerald-700 border-emerald-200",
    available: "bg-emerald-100 text-emerald-700 border-emerald-200",
    autopay: "bg-emerald-100 text-emerald-700 border-emerald-200",
    trialing: "bg-emerald-100 text-emerald-700 border-emerald-200",
    pending: "bg-amber-100 text-amber-700 border-amber-200",
    pending_payment: "bg-amber-100 text-amber-700 border-amber-200",
    autopay_pending: "bg-amber-100 text-amber-700 border-amber-200",
    pending_checkout: "bg-amber-100 text-amber-700 border-amber-200",
    waiting: "bg-amber-100 text-amber-700 border-amber-200",
    waitlisted: "bg-amber-100 text-amber-700 border-amber-200",
    offered: "bg-blue-100 text-blue-700 border-blue-200",
    manual: "bg-blue-100 text-blue-700 border-blue-200",
    paused: "bg-blue-100 text-blue-700 border-blue-200",
    calculated: "bg-amber-100 text-amber-700 border-amber-200",
    invited: "bg-amber-100 text-amber-700 border-amber-200",
    late: "bg-amber-100 text-amber-700 border-amber-200",
    excused: "bg-blue-100 text-blue-700 border-blue-200",
    past_due: "bg-red-100 text-red-700 border-red-200",
    failed: "bg-red-100 text-red-700 border-red-200",
    declined: "bg-red-100 text-red-700 border-red-200",
    cancelled: "bg-red-100 text-red-700 border-red-200",
    canceled: "bg-red-100 text-red-700 border-red-200",
    suspended: "bg-red-100 text-red-700 border-red-200",
    absent: "bg-red-100 text-red-700 border-red-200",
    full: "bg-red-100 text-red-700 border-red-200",
    refunded: "bg-red-100 text-red-700 border-red-200",
    partially_refunded: "bg-amber-100 text-amber-700 border-amber-200",
    completed: "bg-slate-100 text-slate-700 border-slate-200",
    deleted: "bg-slate-100 text-slate-500 border-slate-200",
    not_calculated: "bg-slate-100 text-slate-600 border-slate-200",
  };
  const cls = map[status] || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${cls}`}
    >
      {status?.replace(/_/g, " ")}
    </span>
  );
};

export default StatusBadge;
